/* =========================================================================
   Client chat — live conversation with a client (/ops/chats/).
   Polls the thread and the conversation list, sends text + files.
   Depends on window.Eagle (app.js) for get/post/toast/escapeHtml.
   ========================================================================= */

(function () {
  "use strict";

  var root = document.getElementById("clientChat");
  if (!root || !window.Eagle) { return; }

  var E = window.Eagle;
  var POLL_MS = (window.EAGLE_CFG && window.EAGLE_CFG.pollMs) || 3000;

  var stream = document.getElementById("chatStream");
  var composer = document.getElementById("chatComposer");
  var bodyInput = document.getElementById("chatBody");
  var fileInput = document.getElementById("chatFiles");
  var fileList = document.getElementById("chatFileList");
  var sendBtn = document.getElementById("chatSend");
  var windowNote = document.getElementById("windowClosed");
  var threadList = document.getElementById("threadList");

  var activeCode = root.dataset.active || "";
  var pending = [];          // files picked but not sent yet
  var seen = {};             // uid -> true, so a poll never duplicates a bubble
  var timer = null;
  var busy = false;

  function urlFor(template, code) {
    return (template || "").replace("CODE", encodeURIComponent(code));
  }

  function atBottom() {
    if (!stream) { return true; }
    return stream.scrollHeight - stream.scrollTop - stream.clientHeight < 80;
  }

  function toBottom() {
    if (stream) { stream.scrollTop = stream.scrollHeight; }
  }

  /* ------------------------------------------------------------- bubbles */

  function icon(name, cls) {
    return '<svg class="ic ' + (cls || "") + '" aria-hidden="true"><use href="#i-' +
      name + '"></use></svg>';
  }

  /** Mirrors templates/ops/_client_bubble.html — keep the two in step. */
  function bubbleHtml(msg) {
    var esc = E.escapeHtml;
    var cls = "bub " + (msg.kind === "out" ? "bub--out" : "bub--in");
    if (msg.status === "failed") { cls += " bub--failed"; }

    var parts = [];
    if (msg.subject) { parts.push('<div class="bub__subject">' + esc(msg.subject) + "</div>"); }
    if (msg.body) {
      parts.push('<div class="bub__text">' + esc(msg.body).replace(/\n/g, "<br>") + "</div>");
    }

    (msg.files || []).forEach(function (f) {
      var label = f.url
        ? '<a href="' + esc(f.url) + '" target="_blank" rel="noopener">' + esc(f.name) + "</a>"
        : "<span>" + esc(f.name) + "</span>";
      parts.push('<div class="bub__file">' + icon("paperclip", "ic--sm") + label + "</div>");
    });

    var foot = [];
    if (msg.is_delivery) {
      foot.push('<span class="chip chip--sm">' +
        esc(E.t("تسليم تاسك", "Task delivery")) + "</span>");
    }
    if (msg.task_code) { foot.push('<span class="mono muted">' + esc(msg.task_code) + "</span>"); }
    if (msg.sender) { foot.push('<span class="muted">' + esc(msg.sender) + "</span>"); }
    foot.push('<span class="bub__time mono">' + esc(msg.time) + "</span>");
    if (msg.kind === "out") {
      if (msg.status === "sent") { foot.push(icon("check", "ic--sm")); }
      else if (msg.status === "failed") { foot.push(icon("alert", "ic--sm")); }
    }
    parts.push('<div class="bub__foot">' + foot.join("") + "</div>");

    if (msg.error) { parts.push('<div class="bub__error">' + esc(msg.error) + "</div>"); }

    return '<div class="' + cls + '" data-uid="' + esc(msg.uid) + '">' +
      '<div class="bub__box">' + parts.join("") + "</div></div>";
  }

  /** Cheap fingerprint so a poll only touches the DOM when something moved. */
  function signature(msg) {
    return [msg.status || "", (msg.body || "").length, (msg.files || []).length,
      msg.error ? 1 : 0].join("|");
  }

  function renderMessages(messages) {
    if (!stream) { return false; }
    var stick = atBottom();
    var added = false;

    (messages || []).forEach(function (msg) {
      var sig = signature(msg);
      var existing = stream.querySelector('[data-uid="' + msg.uid + '"]');
      if (existing) {
        // Only redraw when the row actually changed (a send flips
        // pending -> sent/failed); otherwise leave the node alone so the
        // user's text selection and scroll position survive the poll.
        if (existing.dataset.sig !== sig) {
          var fresh = document.createElement("div");
          fresh.innerHTML = bubbleHtml(msg);
          fresh.firstChild.dataset.sig = sig;
          existing.replaceWith(fresh.firstChild);
        }
        return;
      }
      var wrap = document.createElement("div");
      wrap.innerHTML = bubbleHtml(msg);
      wrap.firstChild.dataset.sig = sig;
      stream.appendChild(wrap.firstChild);
      seen[msg.uid] = true;
      added = true;
    });

    if (added && stick) { toBottom(); }
    return added;
  }

  /* -------------------------------------------------------- 24h window */

  function applyClientState(info) {
    if (!info || !windowNote) { return; }
    // Only WhatsApp has the 24-hour customer-service window; e-mail does not.
    var closed = info.channel === "whatsapp" && info.window_open === false;
    windowNote.classList.toggle("hidden", !closed);
  }

  /* ------------------------------------------------------------ polling */

  function pollThread() {
    if (!activeCode || busy) { return Promise.resolve(); }
    return E.get(urlFor(root.dataset.threadUrl, activeCode)).then(function (res) {
      if (!res || !res.ok) { return; }
      renderMessages(res.messages);
      applyClientState(res.client);
    }).catch(function () { /* a dropped poll is not worth a toast */ });
  }

  function buildRow(item) {
    var a = document.createElement("a");
    a.className = "cthread";
    a.dataset.code = item.code;
    a.href = root.dataset.detailUrl.replace("CODE", encodeURIComponent(item.code));
    a.innerHTML =
      '<span class="avatar avatar--brand">' + E.escapeHtml(item.code.slice(3)) + "</span>" +
      '<span class="cthread__body">' +
        '<span class="cthread__top">' +
          '<b class="mono">' + E.escapeHtml(item.label) + "</b>" +
          '<span class="muted mono cthread__time"></span>' +
        "</span>" +
        '<span class="cthread__snippet"></span>' +
      "</span>";
    return a;
  }

  function pollList() {
    if (!threadList) { return Promise.resolve(); }
    return E.get(root.dataset.listUrl).then(function (res) {
      if (!res || !res.ok) { return; }
      var empty = threadList.querySelector(".empty");
      if (empty && (res.items || []).length) { empty.remove(); }

      // The server hands the list back already ordered by last activity, so
      // re-appending in that order both adds newcomers and re-sorts the rest.
      (res.items || []).forEach(function (item) {
        var row = threadList.querySelector('[data-code="' + item.code + '"]');
        if (!row) {
          row = buildRow(item);
          if (item.code === activeCode) { row.classList.add("is-active"); }
        }
        var snippet = row.querySelector(".cthread__snippet");
        var time = row.querySelector(".cthread__time");
        if (snippet) {
          snippet.innerHTML = (item.outgoing ? icon("check", "ic--sm") : "") +
            E.escapeHtml(item.text);
        }
        if (time) { time.textContent = item.time; }
        threadList.appendChild(row);
      });
    }).catch(function () {});
  }

  function tick() {
    pollThread();
    pollList();
  }

  /* ------------------------------------------------------------ sending */

  function drawPending() {
    if (!fileList) { return; }
    fileList.innerHTML = "";
    pending.forEach(function (file, index) {
      var chip = document.createElement("span");
      chip.className = "chip";
      chip.innerHTML = icon("paperclip", "ic--sm") + E.escapeHtml(file.name) +
        ' <button type="button" aria-label="remove">' + icon("x", "ic--sm") + "</button>";
      chip.querySelector("button").addEventListener("click", function () {
        pending.splice(index, 1);
        drawPending();
      });
      fileList.appendChild(chip);
    });
  }

  function send(event) {
    if (event) { event.preventDefault(); }
    if (busy || !activeCode) { return; }

    var text = (bodyInput ? bodyInput.value : "").trim();
    if (!text && !pending.length) { return; }

    var data = new FormData();
    data.append("body", text);
    pending.forEach(function (file) { data.append("files", file); });

    busy = true;
    if (sendBtn) { sendBtn.disabled = true; }

    E.post(urlFor(root.dataset.sendUrl, activeCode), data).then(function (res) {
      if (res && res.messages) {
        renderMessages(res.messages);
        applyClientState(res.client);
        toBottom();
      }
      if (res && res.ok) {
        if (bodyInput) { bodyInput.value = ""; }
        pending = [];
        drawPending();
      } else {
        E.toast({
          level: "danger",
          title: E.t("الرسالة مروحتش", "The message was not sent"),
          body: (res && res.error) || ""
        });
      }
    }).catch(function () {
      E.toast({
        level: "danger",
        title: E.t("مشكلة في الاتصال", "Connection problem")
      });
    }).then(function () {
      busy = false;
      if (sendBtn) { sendBtn.disabled = false; }
    });
  }

  /* --------------------------------------------------------------- init */

  if (stream) {
    stream.querySelectorAll("[data-uid]").forEach(function (node) {
      seen[node.dataset.uid] = true;
    });
    toBottom();
  }

  if (composer) { composer.addEventListener("submit", send); }

  if (bodyInput) {
    bodyInput.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && !event.shiftKey) { send(event); }
    });
  }

  if (fileInput) {
    fileInput.addEventListener("change", function () {
      Array.prototype.forEach.call(fileInput.files, function (file) { pending.push(file); });
      fileInput.value = "";
      drawPending();
    });
  }

  // Pause polling while the tab is hidden — no point burning requests.
  function start() {
    if (timer) { return; }
    timer = setInterval(tick, POLL_MS);
  }
  function stop() {
    if (timer) { clearInterval(timer); timer = null; }
  }
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) { stop(); } else { tick(); start(); }
  });

  if (activeCode) { pollThread(); }
  start();
})();
