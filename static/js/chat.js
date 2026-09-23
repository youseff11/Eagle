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

  /* The two operation actions on a client's own message. The template is
     reversed once by Django with a 0 in it, so the routes stay in urls.py
     and this file never hard-codes a path. */
  var confirmTemplate = root.dataset.confirmUrl || "";
  var taskNewUrl = root.dataset.taskNewUrl || "";
  //: message id -> its attachments, for the "pick the files" dialog.
  var filesByMessage = {};

  function confirmUrl(id) {
    return confirmTemplate.replace("0", String(id || 0));
  }

  /* While an open conversation owns the whole screen, the page behind it must
     not scroll. A stray scroll there collapses the browser's address bar, the
     viewport resizes, and the whole panel jumps — which reads as the frame
     sliding along with the messages instead of holding still. */
  (function lockPageBehind() {
    var narrow = window.matchMedia("(max-width: 860px)");
    function apply() {
      var fullScreen = narrow.matches && root.classList.contains("is-open");
      document.documentElement.classList.toggle("chat-locked", fullScreen);
    }
    apply();
    if (narrow.addEventListener) { narrow.addEventListener("change", apply); }
    else if (narrow.addListener) { narrow.addListener(apply); }
  })();

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
    if (msg.forwarded) {
      parts.push('<div class="bub__fwdtag">' + icon("forward", "ic--sm") +
        '<span data-ar="محوّلة" data-en="Forwarded">' +
        esc(E.t("محوّلة", "Forwarded")) + "</span></div>");
    }
    if (msg.quote) {
      parts.push('<div class="bub__quote">' +
        (msg.quote_who ? "<b>" + esc(msg.quote_who) + "</b>" : "") +
        "<span>" + esc(msg.quote) + "</span></div>");
    }
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
          "</div>" + E.voiceHtml(f.url, f.length) + "</div>"
        );
        return;
      }
      var label = f.url
        ? '<a href="' + esc(f.url) + '" target="_blank" rel="noopener">' + esc(f.name) + "</a>"
        : "<span>" + esc(f.name) + "</span>";
      // The "select files" checkbox - mirrors the one in _client_bubble.html.
      // A file already in a task is shown locked, never ticked.
      var pick = "";
      if (msg.actions && f.id) {
        pick = '<input class="bub__pick" type="checkbox" value="' + esc(String(f.id)) +
          '" data-message="' + esc(String(msg.id)) + '"' +
          (msg.task_code
            ? ' disabled title="' + esc(E.t("الملف ده في تاسك " + msg.task_code,
                "Already in " + msg.task_code)) + '"'
            : "") + ">";
      }
      // A photo is shown as a photo - mirrors _client_bubble.html.
      if (f.image && f.url) {
        parts.push('<div class="bub__file bub__file--img">' + pick +
          '<a class="bub__img" href="' + esc(f.url) + '" target="_blank" rel="noopener" title="' +
            esc(f.name) + '"><img src="' + esc(f.url) + '" alt="' + esc(f.name) +
            '" loading="lazy"></a></div>');
        return;
      }
      parts.push('<div class="bub__file">' + pick + icon("paperclip", "ic--sm") + label + "</div>");
    });

    // What the operation does with a client's files, where the files are.
    // A message with no document behind it gets no buttons.
    // Mirrors the same block in _client_bubble.html.
    if (msg.actions && msg.has_docs) {
        var acts = [
          '<button class="btn btn--sm btn--accent" type="button" data-action="' +
            esc(confirmUrl(msg.id)) + '" ' +
            'data-confirm-ar="هيتبعت للعميل رد فيه كلمة confirmed. تمام؟" ' +
            'data-confirm-en="The client will receive a reply saying &quot;confirmed&quot;. Go ahead?">' +
            icon("check", "ic--sm") +
            '<span data-ar="استلمت" data-en="Received">' +
              esc(E.t("استلمت", "Received")) + "</span></button>"
        ];
        if (msg.task_code) {
          acts.push('<span class="chip chip--sm mono">' + esc(msg.task_code) + "</span>");
        } else {
          acts.push('<button class="btn btn--sm" type="button" data-convert="' +
            esc(String(msg.id)) + '">' + icon("arrow-right", "ic--sm") +
            '<span data-ar="تحويل لتاسك" data-en="Convert to task">' +
              esc(E.t("تحويل لتاسك", "Convert to task")) + "</span></button>");
        }
        if (msg.claimed_by) {
          acts.push('<span class="chip chip--sm">' + icon("user-check", "ic--sm") +
            esc(msg.claimed_by) + "</span>");
        }
        parts.push('<div class="bub__actions">' + acts.join("") + "</div>");
    }

    var foot = [];
    if (msg.is_delivery) {
      foot.push('<span class="chip chip--sm">' +
        esc(E.t("تسليم تاسك", "Task delivery")) + "</span>");
    }
    if (msg.task_code) { foot.push('<span class="mono muted">' + esc(msg.task_code) + "</span>"); }
    if (msg.sender) { foot.push('<span class="muted">' + esc(msg.sender) + "</span>"); }
    foot.push('<span class="bub__time mono">' + esc(msg.time) + "</span>");
    if (msg.kind === "out") { foot.push(ticksHtml(msg)); }
    parts.push('<div class="bub__foot">' + foot.join("") + "</div>");

    if (msg.error) { parts.push('<div class="bub__error">' + esc(msg.error) + "</div>"); }

    return '<div class="' + cls + '" data-uid="' + esc(msg.uid) + '"' +
      ' data-date="' + esc(msg.date || "") + '"' +
      ' data-body="' + esc((msg.body || "").slice(0, 90)) + '"' +
      ' data-who="' + esc(msg.kind === "in" ? "العميل" : (msg.sender || "")) + '">' +
      '<button class="bub__reply" type="button" data-reply="' + esc(msg.uid) + '" ' +
        'data-ar-title="رد" data-en-title="Reply" title="' + esc(E.t("رد", "Reply")) + '">' +
        icon("reply", "ic--sm") + "</button>" +
      '<button class="bub__reply bub__fwd" type="button" data-forward="' + esc(msg.uid) + '" ' +
        'data-ar-title="تحويل" data-en-title="Forward" title="' + esc(E.t("تحويل", "Forward")) + '">' +
        icon("forward", "ic--sm") + "</button>" +
      '<span class="bub__sel" aria-hidden="true">' + icon("check", "ic--sm") + "</span>" +
      '<div class="bub__box">' + parts.join("") + "</div></div>";
  }

  /** Mirrors templates/ops/_ticks.html - keep the two in step.
      One grey check: it left. Two grey: it reached the client's phone.
      Two blue: it was read - by the client, or by everyone else in the room. */
  function ticksHtml(msg) {
    var esc = E.escapeHtml;
    var who = (msg.seen_by || []).join(E.t("، ", ", "));
    var seenTitle = who ? E.t("شافها: ", "Seen by: ") + who : "";
    if (msg.status === "failed") { return icon("alert", "ic--sm"); }
    if (msg.receipt === "read") {
      return '<span class="tick tick--read" title="' +
        esc(seenTitle || E.t("اتقرت", "Read")) + '">' + icon("check-double", "ic--sm") + "</span>";
    }
    if (msg.receipt === "delivered") {
      return '<span class="tick" title="' + esc(E.t("وصلت", "Delivered")) + '">' +
        icon("check-double", "ic--sm") + "</span>";
    }
    if (msg.status === "sent" || msg.mine) {
      return '<span class="tick" title="' + esc(seenTitle || E.t("اتبعتت", "Sent")) + '">' +
        icon("check", "ic--sm") + "</span>";
    }
    return "";
  }

  /** Cheap fingerprint so a poll only touches the DOM when something moved.
      Keep in step with data-sig in _client_bubble.html. */
  function signature(msg) {
    return [msg.status || "", (msg.body || "").length, (msg.files || []).length,
      msg.error ? 1 : 0, msg.quote ? 1 : 0,
      msg.claimed_by ? 1 : 0, msg.task_code ? 1 : 0,
      msg.receipt || "", (msg.seen_by || []).length].join("|");
  }

  function renderMessages(messages) {
    if (!stream) { return false; }
    var stick = atBottom();
    var added = false;

    (messages || []).forEach(function (msg) {
      // Remembered whether the bubble is redrawn or not: the "convert to
      // task" dialog reads this, and it may open long after the last poll
      // that actually changed anything on screen.
      if (msg.actions && msg.id) { filesByMessage[msg.id] = msg.files || []; }
      var sig = signature(msg);
      var existing = stream.querySelector('[data-uid="' + msg.uid + '"]');
      if (existing) {
        // Only redraw when the row actually changed (a send flips
        // pending -> sent/failed); otherwise leave the node alone so the
        // user's text selection and scroll position survive the poll.
        if (existing.dataset.sig !== sig) {
          // Detaching an <audio> does not stop it: a voice note playing in a
          // bubble the poll is about to replace would keep sounding from a
          // node nothing on screen can pause any more.
          existing.querySelectorAll("audio").forEach(function (a) { a.pause(); });
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
    restorePicks();
    restoreSelection();
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

  /* Is the conversation actually in front of somebody? Only then does a poll
     count as reading it. On a phone the list and the room are two screens,
     and a background tab polls just the same - neither is reading. */
  function onScreen() {
    return !!(stream && stream.offsetParent !== null &&
      document.visibilityState === "visible");
  }

  function pollThread() {
    if (!activeCode || busy) { return Promise.resolve(); }
    var url = urlFor(root.dataset.threadUrl, activeCode);
    if (onScreen()) { url += (url.indexOf("?") === -1 ? "?" : "&") + "read=1"; }
    return E.get(url).then(function (res) {
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
    // A colleague wears their initials, a group the users icon, a client the
    // digits of their code. item.code is "u12" / "g7" / "CL-0002".
    var face;
    if (item.group) {
      face = '<span class="avatar avatar--group">' + icon("users", "ic--sm") + "</span>";
    } else if (item.staff) {
      face = '<span class="avatar avatar--staff">' +
        E.escapeHtml(item.initials || (item.label || "?").slice(0, 1).toUpperCase()) +
        "</span>";
    } else {
      face = '<span class="avatar avatar--brand">' +
        E.escapeHtml(item.code.slice(3)) + "</span>";
    }
    a.innerHTML = face +
      '<span class="cthread__body">' +
        '<span class="cthread__top">' +
          '<b class="mono">' + E.escapeHtml(item.label) + "</b>" +
          '<span class="muted mono cthread__time"></span>' +
        "</span>" +
        '<span class="cthread__line">' +
          '<span class="cthread__snippet"></span>' +
          '<span class="cthread__unread hidden"></span>' +
        "</span>" +
      "</span>";
    return a;
  }

  function pollList() {
    if (!threadList) { return Promise.resolve(); }
    var listUrl = root.dataset.listUrl;
    // Always sent: there is no "everything" tab any more, and the server
    // answers a missing type with the client list - which a translator is
    // not allowed to see and would simply get back empty.
    var kind = root.dataset.filter || "staff";
    listUrl += (listUrl.indexOf("?") === -1 ? "?" : "&") + "type=" + kind;
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
          // The same ticks the bubble inside carries - see _ticks.html.
          snippet.innerHTML = (item.outgoing
            ? ticksHtml({ status: item.status, receipt: item.receipt, mine: true })
            : "") + E.escapeHtml(item.text);
        }
        if (time) { time.textContent = item.time; }
        drawUnread(row, item);
        threadList.appendChild(row);
      });
    }).catch(function () {});
  }

  /* The green counter on a row. The conversation on screen is being read
     as it arrives, so it never shows one - the server catches up on the
     next poll, and until then the number would only flicker. */
  function drawUnread(row, item) {
    var badge = row.querySelector(".cthread__unread");
    if (!badge) {
      // A row drawn by an older page: give it the slot rather than skip it.
      var line = row.querySelector(".cthread__snippet");
      if (!line) { return; }
      badge = document.createElement("span");
      badge.className = "cthread__unread hidden";
      line.parentNode.insertBefore(badge, line.nextSibling);
    }
    var n = Number(item.unread) || 0;
    if (item.code === activeCode && onScreen()) { n = 0; }
    badge.textContent = n > 99 ? "99+" : String(n);
    badge.classList.toggle("hidden", n === 0);
    row.classList.toggle("has-unread", n > 0);
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
    if (replyUid) { data.append("reply_uid", replyUid); }
    pending.forEach(function (file) { data.append("files", file); });

    deliver(data, function () {
      if (bodyInput) { bodyInput.value = ""; }
      pending = [];
      drawPending();
      clearReply();
    });
  }

  /* -------------------------------------------------------------- replying */

  var replyBar = document.getElementById("replyBar");
  var replyWho = document.getElementById("replyWho");
  var replyText = document.getElementById("replyText");
  var replyCancel = document.getElementById("replyCancel");
  var replyUid = "";

  function setReply(bubble) {
    if (!bubble || !replyBar) { return; }
    replyUid = bubble.dataset.uid || "";
    if (replyWho) { replyWho.textContent = bubble.dataset.who || ""; }
    if (replyText) {
      replyText.textContent = bubble.dataset.body ||
        E.t("مرفق", "Attachment");
    }
    replyBar.classList.remove("hidden");
    if (bodyInput) { bodyInput.focus(); }
  }

  function clearReply() {
    replyUid = "";
    if (replyBar) { replyBar.classList.add("hidden"); }
  }

  if (replyCancel) { replyCancel.addEventListener("click", clearReply); }
  if (bodyInput) {
    bodyInput.addEventListener("keydown", function (event) {
      if (event.key === "Escape") { clearReply(); }
    });
  }

  // Desktop: the button that appears on the bubble.
  if (stream) {
    stream.addEventListener("click", function (event) {
      var button = event.target.closest && event.target.closest(".bub__reply");
      if (button && !button.classList.contains("bub__fwd")) { setReply(button.closest(".bub")); }
    });
  }

  /* Phones: drag a bubble sideways, exactly like WhatsApp.
     The gesture has to lose to a vertical scroll, so the first few pixels
     decide which one it is and the other is left alone from then on. */
  (function swipeToReply() {
    if (!stream) { return; }
    var bubble = null, startX = 0, startY = 0, dx = 0, axis = "";
    var THRESHOLD = 55;      // far enough that a stray nudge is not a reply
    var MAX = 80;

    function reset(animate) {
      if (bubble) {
        bubble.style.transition = animate ? "transform .18s ease" : "";
        bubble.style.transform = "";
        var node = bubble;
        setTimeout(function () { node.style.transition = ""; }, 200);
      }
      bubble = null; dx = 0; axis = "";
    }

    stream.addEventListener("touchstart", function (event) {
      if (event.touches.length !== 1) { return; }
      var target = event.target.closest && event.target.closest(".bub");
      // Not while scrubbing a voice note — that drag means something else.
      if (!target || (event.target.closest && event.target.closest(".voice"))) { return; }
      bubble = target;
      startX = event.touches[0].clientX;
      startY = event.touches[0].clientY;
      dx = 0; axis = "";
    }, { passive: true });

    stream.addEventListener("touchmove", function (event) {
      if (!bubble) { return; }
      var moveX = event.touches[0].clientX - startX;
      var moveY = event.touches[0].clientY - startY;
      if (!axis) {
        if (Math.abs(moveX) < 8 && Math.abs(moveY) < 8) { return; }
        axis = Math.abs(moveX) > Math.abs(moveY) ? "x" : "y";
        if (axis === "y") { reset(false); return; }
      }
      // Right-to-left page: the "pull" direction is mirrored with it.
      var rtl = document.documentElement.getAttribute("dir") === "rtl";
      dx = rtl ? Math.min(0, moveX) : Math.max(0, moveX);
      var shown = Math.max(-MAX, Math.min(MAX, dx));
      bubble.style.transform = "translateX(" + shown + "px)";
      bubble.classList.toggle("is-swiped", Math.abs(dx) > THRESHOLD);
    }, { passive: true });

    function finish() {
      if (!bubble) { return; }
      var target = bubble;
      var hit = Math.abs(dx) > THRESHOLD;
      target.classList.remove("is-swiped");
      reset(true);
      if (hit) { setReply(target); }
    }
    stream.addEventListener("touchend", finish, { passive: true });
    stream.addEventListener("touchcancel", function () {
      if (bubble) { bubble.classList.remove("is-swiped"); }
      reset(true);
    }, { passive: true });
  })();

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
    if (replyUid) { data.append("reply_uid", replyUid); }
    data.append("voice", rec.blob, "voice" + rec.ext);
    if (recSend) { recSend.disabled = true; }
    deliver(data, function () {
      if (bodyInput) { bodyInput.value = ""; }
      clearReply();
    }).then(function () {
      if (recSend) { recSend.disabled = false; }
      recReset();
    });
  }

  /* ------------------------------------------------- work group */

  var teamModal = document.getElementById("newTeamGroupModal");
  var teamOpen = document.getElementById("newTeamGroupBtn");
  var teamSave = document.getElementById("newTeamGroupSave");
  var teamError = document.getElementById("teamError");
  var teamPicker = document.getElementById("teamMembers");
  var teamTitle = document.getElementById("teamTitle");
  // True once the person has typed a name of their own: after that the
  // suggestion stops overwriting it, which is the whole difference between
  // a default and a nuisance.
  var teamTitleTouched = false;

  function showTeamModal(show) {
    if (!teamModal) { return; }
    teamModal.classList.toggle("hidden", !show);
    if (teamError) { teamError.textContent = ""; }
  }

  /* Mirrors services.default_team_group_name - keep the two in step.

     Each name is labelled, so a list of a dozen of these does not have to be
     decoded one by one. Both have to be known: one translator among the
     people picked, and a team leader - you, if you are one, and otherwise
     the single leader you picked. That second path is what lets an admin
     open the group for a pair without losing the name.

     The server works the same name out when the box is left empty, so this
     is a convenience and never the only place the rule lives. */
  function pickedWithRole(role) {
    return Array.prototype.filter.call(
      (teamPicker && teamPicker.selectedOptions) || [],
      function (opt) { return opt.dataset.role === role; }
    );
  }

  function suggestTeamName() {
    if (!teamTitle || !teamPicker || teamTitleTouched) { return; }
    var translators = pickedWithRole("translator");
    if (translators.length !== 1) { teamTitle.value = ""; return; }

    var lead = "";
    if (teamTitle.dataset.meIsLead) {
      lead = teamTitle.dataset.me || "";
    } else {
      var leads = pickedWithRole("team_lead");
      if (leads.length === 1) { lead = leads[0].dataset.name || ""; }
    }
    teamTitle.value = lead
      ? "مترجم: " + translators[0].dataset.name + " · ليدر: " + lead
      : "";
  }

  function createTeamGroup() {
    if (!teamSave) { return; }
    var data = new FormData();
    data.append("title", teamTitle ? teamTitle.value : "");
    var chosen = teamPicker ? (teamPicker.selectedOptions || []) : [];
    if (!chosen.length) {
      if (teamError) {
        teamError.textContent = E.t("اختار عضو واحد على الأقل.", "Pick at least one person.");
      }
      return;
    }
    Array.prototype.forEach.call(chosen, function (opt) {
      data.append("members", opt.value);
    });

    teamSave.disabled = true;
    E.post(teamSave.dataset.url, data).then(function (res) {
      if (res && res.ok && res.url) {
        window.location.href = res.url;
        return;
      }
      if (teamError) {
        teamError.textContent = (res && res.error) ||
          E.t("مقدرتش أعمل الجروب.", "Could not create the group.");
      }
    }).catch(function () {
      if (teamError) {
        teamError.textContent = E.t("مشكلة في الاتصال", "Connection problem");
      }
    }).then(function () {
      teamSave.disabled = false;
    });
  }

  if (teamOpen) { teamOpen.addEventListener("click", function () { showTeamModal(true); }); }
  ["newTeamGroupClose", "newTeamGroupCancel"].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) { el.addEventListener("click", function () { showTeamModal(false); }); }
  });
  if (teamModal) {
    teamModal.addEventListener("click", function (event) {
      if (event.target === teamModal) { showTeamModal(false); }
    });
  }
  if (teamPicker) { teamPicker.addEventListener("change", suggestTeamName); }
  if (teamTitle) {
    teamTitle.addEventListener("input", function () {
      teamTitleTouched = teamTitle.value.trim() !== "";
    });
  }
  if (teamSave) { teamSave.addEventListener("click", createTeamGroup); }

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

  /* ------------------------------------------------- convert to a task */

  /* "تحويل لتاسك" on a client's message: tick which of their files are the
     job, then hand the ids to the task form. The server re-checks every id
     against the message, so this dialog only has to be convenient. */

  var convertModal = document.getElementById("convertModal");
  var convertForm = document.getElementById("convertForm");
  var convertId = document.getElementById("convertMessage");
  var convertFiles = document.getElementById("convertFiles");
  var convertEmpty = document.getElementById("convertNoFiles");

  function showConvert(on) {
    if (convertModal) { convertModal.classList.toggle("hidden", !on); }
  }

  function fillConvert(messageId) {
    if (!convertForm) { return; }
    convertId.value = messageId;
    var files = filesByMessage[messageId] || [];
    convertFiles.innerHTML = files.map(function (f) {
      if (!f.id) { return ""; }
      return '<label class="pick__item">' +
        '<input type="checkbox" name="files" value="' + E.escapeHtml(String(f.id)) + '" checked>' +
        icon("paperclip", "ic--sm") +
        "<span>" + E.escapeHtml(f.name || "") + "</span></label>";
    }).join("");
    var any = convertFiles.children.length > 0;
    convertFiles.classList.toggle("hidden", !any);
    if (convertEmpty) { convertEmpty.classList.toggle("hidden", any); }
    showConvert(true);
  }

  if (convertForm) {
    document.addEventListener("click", function (event) {
      var btn = event.target && event.target.closest &&
        event.target.closest("[data-convert]");
      if (!btn) { return; }
      var id = btn.getAttribute("data-convert");
      if (!id) { return; }
      // A click in the first seconds after load can beat the first poll that
      // fills the file map; fetch once rather than open an empty dialog.
      if (filesByMessage[id]) { fillConvert(id); }
      else { pollThread().then(function () { fillConvert(id); }); }
    });

    ["convertClose", "convertCancel"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) { el.addEventListener("click", function () { showConvert(false); }); }
    });
    convertModal.addEventListener("click", function (event) {
      if (event.target === convertModal) { showConvert(false); }
    });
  }

  /* ------------------------------------------- select files -> one task */

  /* The client sends a contract in one message, the stamps in the next and
     two more pages an hour later. "تحديد ملفات" puts a checkbox on every
     file in the conversation; whatever is ticked, across any number of
     messages, becomes one task. The server re-checks every id against the
     messages and the client, so this only has to be convenient. */

  var pickToggle = document.getElementById("pickToggle");
  var pickBar = document.getElementById("pickBar");
  var pickCount = document.getElementById("pickCount");
  var pickAll = document.getElementById("pickAll");
  var pickCancel = document.getElementById("pickCancel");
  var pickConvert = document.getElementById("pickConvert");
  //: file id -> message id, for everything ticked. Survives a poll redraw.
  var picked = {};

  function picking() {
    return !!(stream && stream.classList.contains("is-picking"));
  }

  function pickBoxes() {
    return stream ? Array.prototype.slice.call(stream.querySelectorAll(".bub__pick")) : [];
  }

  function drawPickBar() {
    var n = Object.keys(picked).length;
    if (pickCount) { pickCount.textContent = String(n); }
    if (pickConvert) { pickConvert.disabled = n === 0; }
    if (pickForwardBtn) { pickForwardBtn.disabled = n === 0; }
    if (pickAll) {
      var free = dayBoxes();
      var all = free.length > 0 && free.every(function (box) { return box.checked; });
      pickAll.textContent = all ? E.t("شيل الكل", "Clear all") : E.t("تحديد الكل", "Select all");
      pickAll.dataset.ar = all ? "شيل الكل" : "تحديد الكل";
      pickAll.dataset.en = all ? "Clear all" : "Select all";
    }
  }

  /* -- one day's files ---------------------------------------------------- */

  var pickDay = document.getElementById("pickDay");
  var pickForwardBtn = document.getElementById("pickForward");

  function boxDay(box) {
    var bubble = box.closest && box.closest(".bub");
    return bubble ? (bubble.dataset.date || "") : "";
  }

  /** The free boxes inside the chosen day (every day when none is chosen). */
  function dayBoxes() {
    var day = pickDay ? pickDay.value : "";
    return pickBoxes().filter(function (box) {
      return !box.disabled && (!day || boxDay(box) === day);
    });
  }

  function isoDay(date) {
    return date.getFullYear() + "-" + ("0" + (date.getMonth() + 1)).slice(-2) +
      "-" + ("0" + date.getDate()).slice(-2);
  }

  function dayLabel(day) {
    var now = new Date();
    var yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
    if (day === isoDay(now)) { return E.t("النهارده", "Today"); }
    if (day === isoDay(yesterday)) { return E.t("امبارح", "Yesterday"); }
    var bits = day.split("-");
    return bits.length === 3 ? bits[2] + "/" + bits[1] + "/" + bits[0] : day;
  }

  /* The days on offer are the days that actually have a file to tick, newest
     first, each with how many. Rebuilt on every poll so a file that arrives
     today adds itself; the chosen day is kept. */
  function fillDays() {
    if (!pickDay) { return; }
    var counts = {};
    pickBoxes().forEach(function (box) {
      if (box.disabled) { return; }
      var day = boxDay(box);
      if (day) { counts[day] = (counts[day] || 0) + 1; }
    });
    var chosen = pickDay.value;
    var days = Object.keys(counts).sort().reverse();
    pickDay.innerHTML = '<option value="">' + E.escapeHtml(E.t("كل الأيام", "All days")) +
      "</option>" + days.map(function (day) {
        return '<option value="' + E.escapeHtml(day) + '">' +
          E.escapeHtml(dayLabel(day) + " (" + counts[day] + ")") + "</option>";
      }).join("");
    pickDay.value = counts[chosen] ? chosen : "";
  }

  if (pickDay) {
    pickDay.addEventListener("change", function () {
      // A day is a selection on its own: that day's files, and nothing else.
      var day = pickDay.value;
      picked = {};
      if (day) {
        dayBoxes().forEach(function (box) { picked[box.value] = box.dataset.message; });
        var first = dayBoxes()[0];
        if (first && first.scrollIntoView) { first.scrollIntoView({ block: "center" }); }
      }
      restorePicks();
      drawPickBar();
    });
  }

  if (pickForwardBtn) {
    pickForwardBtn.addEventListener("click", function () {
      openForward([], Object.keys(picked));
    });
  }

  function restorePicks() {
    pickBoxes().forEach(function (box) {
      box.checked = !box.disabled && !!picked[box.value];
      var holder = box.closest && box.closest(".bub__file");
      if (holder) { holder.classList.toggle("is-picked", box.checked); }
    });
    if (picking()) { fillDays(); drawPickBar(); }
  }

  function setPicking(on) {
    if (!stream || !pickBar) { return; }
    stream.classList.toggle("is-picking", on);
    pickBar.classList.toggle("hidden", !on);
    if (composer) { composer.classList.toggle("hidden", on); }
    if (pickToggle) { pickToggle.classList.toggle("is-on", on); }
    if (on) { setSelecting(false); }
    if (!on) { picked = {}; if (pickDay) { pickDay.value = ""; } }
    restorePicks();
    drawPickBar();
  }

  if (pickToggle) {
    pickToggle.addEventListener("click", function () { setPicking(!picking()); });
  }
  if (pickCancel) { pickCancel.addEventListener("click", function () { setPicking(false); }); }

  if (stream) {
    stream.addEventListener("change", function (event) {
      var box = event.target;
      if (!box || !box.classList || !box.classList.contains("bub__pick")) { return; }
      if (box.checked) { picked[box.value] = box.dataset.message; }
      else { delete picked[box.value]; }
      var holder = box.closest && box.closest(".bub__file");
      if (holder) { holder.classList.toggle("is-picked", box.checked); }
      drawPickBar();
    });

    /* While picking, a tap anywhere on a file - a photo above all, where the
       box is small and the picture is a link - ticks it instead of opening
       it. Photos go into a task exactly like any other file. */
    stream.addEventListener("click", function (event) {
      if (!picking()) { return; }
      var target = event.target;
      if (target.classList && target.classList.contains("bub__pick")) { return; }
      var holder = target.closest && target.closest(".bub__file");
      if (!holder) { return; }
      var box = holder.querySelector(".bub__pick");
      if (!box || box.disabled) { return; }
      event.preventDefault();
      box.checked = !box.checked;
      box.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }

  if (pickAll) {
    pickAll.addEventListener("click", function () {
      var free = dayBoxes();
      var all = free.length > 0 && free.every(function (box) { return box.checked; });
      free.forEach(function (box) {
        box.checked = !all;
        if (box.checked) { picked[box.value] = box.dataset.message; }
        else { delete picked[box.value]; }
      });
      drawPickBar();
    });
  }

  if (pickConvert) {
    pickConvert.addEventListener("click", function () {
      var files = Object.keys(picked);
      if (!files.length || !taskNewUrl) { return; }
      var messages = [];
      files.forEach(function (id) {
        if (messages.indexOf(picked[id]) === -1) { messages.push(picked[id]); }
      });
      window.location.href = taskNewUrl +
        (taskNewUrl.indexOf("?") === -1 ? "?" : "&") +
        "messages=" + encodeURIComponent(messages.join(",")) +
        "&files=" + encodeURIComponent(files.join(","));
    });
  }

  /* ---------------------------------------------- forward messages/files */

  /* "تحويل رسايل" (or the arrow on a bubble) turns the conversation into a
     list you tap: each tap picks or drops a message. The bar underneath sends
     the picked ones to another chat. Links, players and buttons inside a
     bubble keep working - only a tap on the bubble itself picks it. */

  var selectToggle = document.getElementById("selectToggle");
  var selectBar = document.getElementById("selectBar");
  var selectCount = document.getElementById("selectCount");
  var selectCancel = document.getElementById("selectCancel");
  var selectForward = document.getElementById("selectForward");
  var selected = [];            // bubble uids, in the order they were picked

  function selecting() {
    return !!(stream && stream.classList.contains("is-selecting"));
  }

  function drawSelectBar() {
    if (selectCount) { selectCount.textContent = String(selected.length); }
    if (selectForward) { selectForward.disabled = selected.length === 0; }
  }

  function restoreSelection() {
    if (!stream) { return; }
    stream.querySelectorAll(".bub[data-uid]").forEach(function (bubble) {
      bubble.classList.toggle("is-selected", selected.indexOf(bubble.dataset.uid) !== -1);
    });
  }

  function setSelecting(on, firstUid) {
    if (!stream || !selectBar) { return; }
    if (on && picking()) { setPicking(false); }
    stream.classList.toggle("is-selecting", on);
    selectBar.classList.toggle("hidden", !on);
    if (composer) { composer.classList.toggle("hidden", on || picking()); }
    if (selectToggle) { selectToggle.classList.toggle("is-on", on); }
    selected = on && firstUid ? [firstUid] : [];
    restoreSelection();
    drawSelectBar();
  }

  if (selectToggle) {
    selectToggle.addEventListener("click", function () { setSelecting(!selecting()); });
  }
  if (selectCancel) { selectCancel.addEventListener("click", function () { setSelecting(false); }); }
  if (selectForward) {
    selectForward.addEventListener("click", function () { openForward(selected.slice(), []); });
  }

  if (stream) {
    stream.addEventListener("click", function (event) {
      var target = event.target;
      var fwd = target.closest && target.closest("[data-forward]");
      if (fwd) {
        event.preventDefault();
        if (!selecting()) { setSelecting(true, fwd.getAttribute("data-forward")); }
        return;
      }
      if (!selecting()) { return; }
      if (target.closest && target.closest("a, button, audio, input, .voice")) { return; }
      var bubble = target.closest && target.closest(".bub[data-uid]");
      if (!bubble) { return; }
      var uid = bubble.dataset.uid;
      var at = selected.indexOf(uid);
      if (at === -1) { selected.push(uid); } else { selected.splice(at, 1); }
      restoreSelection();
      drawSelectBar();
    });
  }

  /* -- where it goes ------------------------------------------------------ */

  var fwdModal = document.getElementById("forwardModal");
  var fwdList = document.getElementById("forwardList");
  var fwdSearch = document.getElementById("forwardSearch");
  var fwdNote = document.getElementById("forwardNote");
  var fwdSend = document.getElementById("forwardSend");
  var fwdError = document.getElementById("forwardError");
  var fwdCount = document.getElementById("forwardCount");
  var fwdWhat = { uids: [], files: [] };
  var fwdTargets = [];
  var fwdChosen = "";

  function fwdFetch(kind) {
    var url = fwdModal.dataset.listUrl;
    return E.get(url + (url.indexOf("?") === -1 ? "?" : "&") + "type=" + kind)
      .then(function (res) { return (res && res.ok && res.items) || []; })
      .catch(function () { return []; });
  }

  function drawTargets() {
    if (!fwdList) { return; }
    var q = (fwdSearch ? fwdSearch.value : "").trim().toLowerCase();
    var rows = fwdTargets.filter(function (item) {
      return item.code !== activeCode &&
        (!q || (item.label || "").toLowerCase().indexOf(q) !== -1 ||
          (item.code || "").toLowerCase().indexOf(q) !== -1);
    });
    if (!rows.length) {
      fwdList.innerHTML = '<div class="muted">' +
        E.escapeHtml(E.t("مفيش نتايج.", "Nothing matches.")) + "</div>";
      return;
    }
    fwdList.innerHTML = rows.map(function (item) {
      var face = item.group ? icon("users", "ic--sm")
        : item.staff ? E.escapeHtml(item.initials || "?")
        : E.escapeHtml((item.code || "").slice(3));
      var kind = item.group
        ? (item.reaches_client ? E.t("جروب مع العميل", "Group with the client")
          : E.t("جروب", "Group"))
        : item.staff ? E.t("زميل", "Colleague") : E.t("عميل · واتساب", "Client · WhatsApp");
      return '<label class="fwd-row' + (item.code === fwdChosen ? " is-on" : "") + '">' +
        '<input type="radio" name="fwdTarget" value="' + E.escapeHtml(item.code) + '"' +
          (item.code === fwdChosen ? " checked" : "") + ">" +
        '<span class="avatar ' + (item.group ? "avatar--group" : item.staff ? "avatar--staff" : "avatar--brand") +
          '">' + face + "</span>" +
        '<span class="fwd-row__body"><b>' + E.escapeHtml(item.label || item.code) + "</b>" +
        '<span class="muted">' + E.escapeHtml(kind) + "</span></span></label>";
    }).join("");
  }

  function openForward(uids, files) {
    if (!fwdModal) { return; }
    if (!uids.length && !files.length) { return; }
    fwdWhat = { uids: uids, files: files };
    fwdChosen = "";
    if (fwdSend) { fwdSend.disabled = true; }
    if (fwdError) { fwdError.textContent = ""; }
    if (fwdNote) { fwdNote.value = ""; }
    if (fwdSearch) { fwdSearch.value = ""; }
    if (fwdCount) { fwdCount.textContent = String(uids.length + files.length); }
    fwdModal.classList.remove("hidden");
    var kinds = ["staff", "groups"];
    if (fwdModal.dataset.clients) { kinds.push("clients"); }
    Promise.all(kinds.map(fwdFetch)).then(function (lists) {
      fwdTargets = [];
      lists.forEach(function (items) {
        items.forEach(function (item) {
          // Every group in the Groups tab. One that reaches a client gets
          // the client rules on the server (no other client's files).
          fwdTargets.push(item);
        });
      });
      drawTargets();
    });
  }

  function closeForward() {
    if (fwdModal) { fwdModal.classList.add("hidden"); }
  }

  if (fwdModal) {
    ["forwardClose", "forwardCancel"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) { el.addEventListener("click", closeForward); }
    });
    fwdModal.addEventListener("click", function (event) {
      if (event.target === fwdModal) { closeForward(); }
    });
    if (fwdSearch) { fwdSearch.addEventListener("input", drawTargets); }
    if (fwdList) {
      fwdList.addEventListener("change", function (event) {
        if (event.target && event.target.name === "fwdTarget") {
          fwdChosen = event.target.value;
          if (fwdSend) { fwdSend.disabled = !fwdChosen; }
          drawTargets();
        }
      });
    }
    if (fwdSend) {
      fwdSend.addEventListener("click", function () {
        if (!fwdChosen) { return; }
        var data = new FormData();
        data.append("source", activeCode);
        data.append("target", fwdChosen);
        data.append("note", fwdNote ? fwdNote.value : "");
        fwdWhat.uids.forEach(function (uid) { data.append("uids", uid); });
        if (fwdWhat.files.length) { data.append("files", fwdWhat.files.join(",")); }
        fwdSend.disabled = true;
        E.post(fwdModal.dataset.url, data).then(function (res) {
          if (res && res.ok) {
            closeForward();
            setSelecting(false);
            setPicking(false);
            E.toast({ level: "success", title: E.t("اتحوّلت", "Forwarded") });
            if (res.url) { window.location.href = res.url; }
            return;
          }
          if (fwdError) {
            fwdError.textContent = (res && res.error) ||
              E.t("مقدرتش أحوّل.", "Could not forward.");
          }
        }).catch(function () {
          if (fwdError) { fwdError.textContent = E.t("مشكلة في الاتصال", "Connection problem"); }
        }).then(function () {
          fwdSend.disabled = !fwdChosen;
        });
      });
    }
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
