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

  // A group's endpoints are fixed (they carry a room id, not a client code),
  // so only the 1:1 URLs need the placeholder swapped.
  var isGroup = activeCode.charAt(0) === "g" && /^g\d+$/.test(activeCode);

  function urlFor(template, code) {
    if (isGroup) { return template || ""; }
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
      // Anything the browser can play gets a player, not a download link —
      // one click and you hear it.
      if (f.audio && f.url) {
        parts.push(
          '<div class="bub__voice"><div class="bub__voice-head">' +
            icon("mic", "ic--sm") +
            '<span data-ar="رسالة صوتية" data-en="Voice note">' +
              esc(E.t("رسالة صوتية", "Voice note")) + "</span>" +
            (f.length ? '<span class="mono muted">' + esc(f.length) + "</span>" : "") +
          '</div><audio controls preload="metadata" src="' + esc(f.url) + '"></audio></div>'
        );
        return;
      }
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
    // The server hands back the destination for both kinds — a group's URL
    // carries a room id, not a client code, so it cannot be built from a
    // template here.
    a.href = item.url ||
      root.dataset.detailUrl.replace("CODE", encodeURIComponent(item.code));
    var face = item.group
      ? '<span class="avatar avatar--group">' + icon("users", "ic--sm") + "</span>"
      : '<span class="avatar avatar--brand">' + E.escapeHtml(item.code.slice(3)) + "</span>";
    a.innerHTML = face +
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
    var listUrl = root.dataset.listUrl;
    var kind = root.dataset.filter || "all";
    if (kind !== "all") {
      listUrl += (listUrl.indexOf("?") === -1 ? "?" : "&") + "type=" + kind;
    }
    return E.get(listUrl).then(function (res) {
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

  /** Post one FormData to the send endpoint and fold the reply into the stream. */
  function deliver(data, onSent) {
    busy = true;
    if (sendBtn) { sendBtn.disabled = true; }

    return E.post(urlFor(root.dataset.sendUrl, activeCode), data).then(function (res) {
      if (res && res.messages) {
        renderMessages(res.messages);
        applyClientState(res.client);
        toBottom();
      }
      if (res && res.ok) {
        if (onSent) { onSent(); }
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

  function send(event) {
    if (event) { event.preventDefault(); }
    if (busy || !activeCode) { return; }

    var text = (bodyInput ? bodyInput.value : "").trim();
    if (!text && !pending.length) { return; }

    var data = new FormData();
    data.append("body", text);
    pending.forEach(function (file) { data.append("files", file); });

    deliver(data, function () {
      if (bodyInput) { bodyInput.value = ""; }
      pending = [];
      drawPending();
    });
  }

  /* ---------------------------------------------------------- recording */

  // Browsers disagree on what they can record. The first two are formats
  // WhatsApp accepts untouched; the WebM fallback is converted server-side.
  var REC_TYPES = [
    { mime: "audio/ogg;codecs=opus", ext: ".ogg" },
    { mime: "audio/mp4", ext: ".m4a" },
    { mime: "audio/webm;codecs=opus", ext: ".webm" },
    { mime: "audio/webm", ext: ".webm" }
  ];
  var REC_MAX_SECONDS = 300;

  var micBtn = document.getElementById("micBtn");
  var recBar = document.getElementById("recBar");
  var recTime = document.getElementById("recTime");
  var recDotEl = document.getElementById("recDot");
  var recState = document.getElementById("recState");
  var recPreview = document.getElementById("recPreview");
  var recStop = document.getElementById("recStop");
  var recSend = document.getElementById("recSend");
  var recCancel = document.getElementById("recCancel");

  var rec = {
    recorder: null, stream: null, chunks: [], ticker: null,
    seconds: 0, blob: null, ext: ".webm", url: "", aborted: false
  };

  function recType() {
    if (!window.MediaRecorder) { return null; }
    for (var i = 0; i < REC_TYPES.length; i += 1) {
      try {
        if (MediaRecorder.isTypeSupported(REC_TYPES[i].mime)) { return REC_TYPES[i]; }
      } catch (err) { /* older browsers throw instead of returning false */ }
    }
    return { mime: "", ext: ".webm" };
  }

  function clock(seconds) {
    return Math.floor(seconds / 60) + ":" + ("0" + (seconds % 60)).slice(-2);
  }

  function recRelease() {
    if (rec.ticker) { clearInterval(rec.ticker); rec.ticker = null; }
    if (rec.stream) {
      rec.stream.getTracks().forEach(function (track) { track.stop(); });
      rec.stream = null;
    }
    rec.recorder = null;
  }

  function recReset() {
    recRelease();
    if (rec.url) { URL.revokeObjectURL(rec.url); rec.url = ""; }
    rec.chunks = [];
    rec.blob = null;
    rec.seconds = 0;
    rec.aborted = false;
    if (recBar) { recBar.classList.add("hidden"); }
    if (recPreview) { recPreview.classList.add("hidden"); recPreview.removeAttribute("src"); }
    if (recStop) { recStop.classList.remove("hidden"); }
    if (recSend) { recSend.classList.add("hidden"); }
    if (recDotEl) { recDotEl.classList.remove("hidden"); }
    if (recTime) { recTime.textContent = "0:00"; }
    if (micBtn) { micBtn.classList.remove("is-live"); micBtn.disabled = false; }
    if (recState) {
      recState.textContent = E.t("بسجّل…", "Recording…");
      recState.dataset.ar = "بسجّل…";
      recState.dataset.en = "Recording…";
    }
  }

  function recReady() {
    // Recording stopped and we have something to listen to before sending.
    if (rec.url) { URL.revokeObjectURL(rec.url); }
    rec.url = URL.createObjectURL(rec.blob);
    if (recPreview) {
      recPreview.src = rec.url;
      recPreview.classList.remove("hidden");
    }
    if (recStop) { recStop.classList.add("hidden"); }
    if (recSend) { recSend.classList.remove("hidden"); }
    if (recDotEl) { recDotEl.classList.add("hidden"); }
    if (micBtn) { micBtn.classList.remove("is-live"); }
    if (recState) {
      recState.textContent = E.t("اسمعها قبل ما تبعتها", "Listen before sending");
      recState.dataset.ar = "اسمعها قبل ما تبعتها";
      recState.dataset.en = "Listen before sending";
    }
  }

  function startRecording() {
    if (!activeCode || rec.recorder) { return; }

    var type = recType();
    if (!type || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      E.toast({
        level: "danger",
        title: E.t("المتصفح ده مش بيسجّل صوت", "This browser cannot record audio")
      });
      return;
    }

    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      rec.stream = stream;
      rec.chunks = [];
      rec.seconds = 0;
      rec.ext = type.ext;
      rec.aborted = false;
      rec.recorder = type.mime
        ? new MediaRecorder(stream, { mimeType: type.mime })
        : new MediaRecorder(stream);

      rec.recorder.ondataavailable = function (event) {
        if (event.data && event.data.size) { rec.chunks.push(event.data); }
      };
      rec.recorder.onstop = function () {
        var mime = (rec.recorder && rec.recorder.mimeType) || type.mime || "audio/webm";
        var blob = new Blob(rec.chunks, { type: mime });
        recRelease();
        if (rec.aborted || !blob.size) { recReset(); return; }
        rec.blob = blob;
        recReady();
      };
      rec.recorder.start();

      if (recBar) { recBar.classList.remove("hidden"); }
      if (micBtn) { micBtn.classList.add("is-live"); micBtn.disabled = true; }
      rec.ticker = setInterval(function () {
        rec.seconds += 1;
        if (recTime) { recTime.textContent = clock(rec.seconds); }
        if (rec.seconds >= REC_MAX_SECONDS) { stopRecording(); }
      }, 1000);
    }).catch(function () {
      E.toast({
        level: "danger",
        title: E.t("مفيش إذن للمايك", "Microphone permission denied"),
        body: E.t("اسمح للموقع يستخدم المايك من إعدادات المتصفح.",
          "Allow this site to use the microphone in your browser settings.")
      });
    });
  }

  function stopRecording() {
    if (rec.recorder && rec.recorder.state !== "inactive") {
      rec.recorder.stop();
    } else {
      recReset();
    }
  }

  function cancelRecording() {
    rec.aborted = true;
    if (rec.recorder && rec.recorder.state !== "inactive") {
      rec.recorder.stop();     // onstop sees `aborted` and throws the blob away
    } else {
      recReset();
    }
  }

  function sendRecording() {
    if (busy || !rec.blob || !activeCode) { return; }
    var data = new FormData();
    data.append("body", (bodyInput ? bodyInput.value : "").trim());
    data.append("seconds", String(rec.seconds));
    data.append("voice", rec.blob, "voice" + rec.ext);
    if (recSend) { recSend.disabled = true; }
    deliver(data, function () {
      if (bodyInput) { bodyInput.value = ""; }
    }).then(function () {
      if (recSend) { recSend.disabled = false; }
      recReset();
    });
  }

  /* ------------------------------------------------------- new group */

  var groupModal = document.getElementById("newGroupModal");
  var groupOpen = document.getElementById("newGroupBtn");
  var groupSave = document.getElementById("newGroupSave");
  var groupError = document.getElementById("groupError");

  function showGroupModal(show) {
    if (!groupModal) { return; }
    groupModal.classList.toggle("hidden", !show);
    if (groupError) { groupError.textContent = ""; }
  }

  function createGroup() {
    if (!groupSave) { return; }
    var client = (document.getElementById("groupClient") || {}).value || "";
    if (!client) {
      if (groupError) {
        groupError.textContent = E.t("اختار عميل الأول.", "Pick a client first.");
      }
      return;
    }

    var data = new FormData();
    data.append("client", client);
    data.append("title", (document.getElementById("groupTitle") || {}).value || "");
    data.append("task", (document.getElementById("groupTask") || {}).value || "");
    var picker = document.getElementById("groupMembers");
    if (picker) {
      Array.prototype.forEach.call(picker.selectedOptions || [], function (opt) {
        data.append("members", opt.value);
      });
    }

    groupSave.disabled = true;
    E.post(groupSave.dataset.url, data).then(function (res) {
      if (res && res.ok && res.url) {
        window.location.href = res.url;
        return;
      }
      if (groupError) {
        groupError.textContent = (res && res.error) ||
          E.t("مقدرتش أعمل الجروب.", "Could not create the group.");
      }
    }).catch(function () {
      if (groupError) {
        groupError.textContent = E.t("مشكلة في الاتصال", "Connection problem");
      }
    }).then(function () {
      groupSave.disabled = false;
    });
  }

  if (groupOpen) { groupOpen.addEventListener("click", function () { showGroupModal(true); }); }
  ["newGroupClose", "newGroupCancel"].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) { el.addEventListener("click", function () { showGroupModal(false); }); }
  });
  if (groupModal) {
    groupModal.addEventListener("click", function (event) {
      if (event.target === groupModal) { showGroupModal(false); }
    });
  }
  if (groupSave) { groupSave.addEventListener("click", createGroup); }

  /* ---------------------------------------------------- add members */

  var memberModal = document.getElementById("addMemberModal");
  var memberOpen = document.getElementById("addMemberBtn");
  var memberSave = document.getElementById("addMemberSave");
  var memberError = document.getElementById("addMemberError");

  function showMemberModal(show) {
    if (!memberModal) { return; }
    memberModal.classList.toggle("hidden", !show);
    if (memberError) { memberError.textContent = ""; }
  }

  function addMembers() {
    if (!memberSave) { return; }
    var picker = document.getElementById("addMemberPicker");
    var chosen = picker ? Array.prototype.slice.call(picker.selectedOptions || []) : [];
    if (!chosen.length) {
      if (memberError) {
        memberError.textContent = E.t("اختار حد الأول.", "Pick somebody first.");
      }
      return;
    }

    var data = new FormData();
    chosen.forEach(function (opt) { data.append("members", opt.value); });

    memberSave.disabled = true;
    E.post(memberSave.dataset.url, data).then(function (res) {
      if (res && res.ok) {
        window.location.reload();
        return;
      }
      if (memberError) {
        memberError.textContent = (res && res.error) ||
          E.t("مقدرتش أضيف.", "Could not add them.");
      }
    }).catch(function () {
      if (memberError) {
        memberError.textContent = E.t("مشكلة في الاتصال", "Connection problem");
      }
    }).then(function () {
      memberSave.disabled = false;
    });
  }

  if (memberOpen) { memberOpen.addEventListener("click", function () { showMemberModal(true); }); }
  ["addMemberClose", "addMemberCancel"].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) { el.addEventListener("click", function () { showMemberModal(false); }); }
  });
  if (memberModal) {
    memberModal.addEventListener("click", function (event) {
      if (event.target === memberModal) { showMemberModal(false); }
    });
  }
  if (memberSave) { memberSave.addEventListener("click", addMembers); }

  if (micBtn) { micBtn.addEventListener("click", startRecording); }
  if (recStop) { recStop.addEventListener("click", stopRecording); }
  if (recSend) { recSend.addEventListener("click", sendRecording); }
  if (recCancel) { recCancel.addEventListener("click", cancelRecording); }
  window.addEventListener("beforeunload", recRelease);

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
