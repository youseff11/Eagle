/* =========================================================================
   Eagle Dashboard — front-end runtime
   - bilingual UI (translations live in the HTML: data-ar / data-en)
   - dark / light theme
   - polling heartbeat: notifications, sounds, 60s accept modal
   - task chat
   ========================================================================= */

window.Eagle = (function () {
  "use strict";

  var cfg = window.EAGLE_CFG || {};
  var state = {
    lang: cfg.lang || "ar",
    theme: cfg.theme || "dark",
    lastNotification: cfg.lastNotification || 0,
    pendingId: null,
    audio: null,
    timer: null,
    countdownTimer: null
  };

  /* ------------------------------------------------------------ utilities */

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function cookie(name) {
    var match = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
    return match ? decodeURIComponent(match[2]) : "";
  }

  function csrf() { return cookie("csrftoken"); }

  function post(url, data) {
    var body;
    if (data instanceof FormData) {
      body = data;
    } else {
      body = new FormData();
      Object.keys(data || {}).forEach(function (k) { body.append(k, data[k]); });
    }
    return fetch(url, {
      method: "POST",
      headers: { "X-CSRFToken": csrf(), "X-Requested-With": "XMLHttpRequest" },
      body: body,
      credentials: "same-origin"
    }).then(function (r) { return r.json().catch(function () { return { ok: false }; }); });
  }

  function get(url) {
    return fetch(url, {
      headers: { "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin"
    }).then(function (r) { return r.json(); });
  }

  function escapeHtml(text) {
    var div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
  }

  /** Markup for one sprite icon (see templates/partials/icons.html). */
  function svgIcon(name, cls) {
    return '<svg class="ic ' + (cls || "") + '" aria-hidden="true">' +
      '<use href="#i-' + name + '"></use></svg>';
  }

  var TOAST_ICON = {
    info: "info", success: "check-circle", warning: "alert", danger: "alert"
  };

  /* ----------------------------------------------------------------- i18n */

  function applyLang(lang, persist) {
    state.lang = lang;
    var root = document.documentElement;
    root.setAttribute("lang", lang === "ar" ? "ar" : "en");
    root.setAttribute("dir", lang === "ar" ? "rtl" : "ltr");

    $$("[data-ar]").forEach(function (el) {
      var value = el.getAttribute("data-" + lang);
      if (value === null || value === undefined) { return; }
      // data-html opts a node into rich markup (authored in our own templates).
      if (el.hasAttribute("data-html")) { el.innerHTML = value; } else { el.textContent = value; }
    });
    $$("[data-ar-ph]").forEach(function (el) {
      var value = el.getAttribute("data-" + lang + "-ph");
      if (value) { el.setAttribute("placeholder", value); }
    });
    $$("[data-ar-title]").forEach(function (el) {
      var value = el.getAttribute("data-" + lang + "-title");
      if (value) { el.setAttribute("title", value); }
    });

    $$("[data-lang-btn]").forEach(function (el) {
      el.classList.toggle("is-active", el.getAttribute("data-lang-btn") === lang);
    });

    if (persist !== false) {
      document.cookie = "eagle_lang=" + lang + ";path=/;max-age=31536000;samesite=Lax";
      post(cfg.prefsUrl, { lang: lang });
    }
  }

  function t(ar, en) { return state.lang === "ar" ? ar : en; }

  /* ---------------------------------------------------------------- theme */

  function applyTheme(theme, persist) {
    state.theme = theme;
    document.documentElement.setAttribute("data-theme", theme);
    var themeIcon = $("#themeIcon use");
    if (themeIcon) { themeIcon.setAttribute("href", theme === "dark" ? "#i-moon" : "#i-sun"); }
    if (persist !== false) {
      document.cookie = "eagle_theme=" + theme + ";path=/;max-age=31536000;samesite=Lax";
      post(cfg.prefsUrl, { theme: theme });
    }
  }

  /* ---------------------------------------------------------------- sound */

  function audioCtx() {
    if (!state.audio) {
      var Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) { return null; }
      state.audio = new Ctx();
    }
    if (state.audio.state === "suspended") { state.audio.resume(); }
    return state.audio;
  }

  function beep(times, frequency) {
    var ctx = audioCtx();
    if (!ctx) { return; }
    var count = times || 1;
    for (var i = 0; i < count; i++) {
      (function (index) {
        var osc = ctx.createOscillator();
        var gain = ctx.createGain();
        var start = ctx.currentTime + index * 0.28;
        osc.type = "sine";
        osc.frequency.setValueAtTime(frequency || 880, start);
        gain.gain.setValueAtTime(0.0001, start);
        gain.gain.exponentialRampToValueAtTime(0.28, start + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.22);
        osc.connect(gain).connect(ctx.destination);
        osc.start(start);
        osc.stop(start + 0.24);
      })(i);
    }
  }

  /* --------------------------------------------------------------- toasts */

  function toast(options) {
    var host = $("#toasts");
    if (!host) { return; }
    var level = options.level || "info";
    var el = document.createElement("div");
    el.className = "toast toast--" + level;
    el.innerHTML =
      svgIcon(TOAST_ICON[level] || "info") +
      "<div>" +
      '<div class="toast__title">' + escapeHtml(options.title) + "</div>" +
      (options.body ? '<div class="toast__body">' + escapeHtml(options.body) + "</div>" : "") +
      "</div>";
    if (options.url) {
      el.style.cursor = "pointer";
      el.addEventListener("click", function () { window.location.href = options.url; });
    }
    host.appendChild(el);
    setTimeout(function () {
      el.style.opacity = "0";
      setTimeout(function () { el.remove(); }, 300);
    }, options.sticky ? 15000 : 7000);
  }

  /* ------------------------------------------------- 60s assignment modal */

  /* "باقي يومين و3 ساعات" until the deadline - or how late it already is.
     Counted in the browser from the ISO time the server sends, so it keeps
     moving between polls. */
  function deadlineLeft(iso) {
    if (!iso) { return { text: "", late: false }; }
    var ms = new Date(iso).getTime() - Date.now();
    if (isNaN(ms)) { return { text: "", late: false }; }
    var late = ms < 0;
    var minutes = Math.floor(Math.abs(ms) / 60000);
    var days = Math.floor(minutes / 1440);
    var hours = Math.floor((minutes % 1440) / 60);
    var mins = minutes % 60;
    var ar = [], en = [];
    if (days) { ar.push(days + " يوم"); en.push(days + (days === 1 ? " day" : " days")); }
    if (hours) { ar.push(hours + " ساعة"); en.push(hours + (hours === 1 ? " hour" : " hours")); }
    if (!days && (mins || !hours)) {
      ar.push(mins + " دقيقة"); en.push(mins + (mins === 1 ? " minute" : " minutes"));
    }
    var span = t(ar.join(" و"), en.join(" "));
    return {
      late: late,
      text: late ? t("الديدلاين فات من " + span, "Deadline passed " + span + " ago")
                 : t("باقي " + span + " على الديدلاين", span + " left until the deadline")
    };
  }

  function paintDeadlineLeft(node, iso) {
    if (!node) { return; }
    var left = deadlineLeft(iso);
    node.textContent = left.text;
    node.classList.toggle("hidden", !left.text);
    node.classList.toggle("is-late", left.late);
  }

  function showPending(pending) {
    if (!pending) { hidePending(); return; }
    if (state.pendingId === pending.id) { return; }
    // Already on this hand-off's own page: the countdown, accept and decline
    // are on the page itself, so the popup would only cover them.
    var preview = $("#assignPreview");
    if (preview && preview.getAttribute("data-id") === String(pending.id)) {
      state.pendingId = pending.id;
      return;
    }
    state.pendingId = pending.id;
    state.pendingDeadline = pending.deadline_iso || "";

    var backdrop = $("#assignModal");
    if (!backdrop) { return; }
    backdrop.classList.remove("hidden");
    $("#assignTask").textContent = pending.task_code + " · " + pending.task_title;
    $("#assignClient").textContent = pending.client;
    $("#assignFrom").textContent = pending.assigned_by || "—";
    $("#assignDeadline").textContent = pending.deadline || "—";
    $("#assignNote").textContent = pending.note || "";
    $("#assignOpen").setAttribute("href", pending.task_url);

    // Reading the files is not answering the hand-off: the window keeps
    // running, and the visit is recorded so "they opened it and said nothing"
    // is a fact rather than a guess.
    var files = $("#assignFiles");
    var reason = $("#assignReason");
    if (reason) { reason.value = ""; }
    if (files) {
      files.classList.toggle("hidden", !pending.files_url);
      files.onclick = function () {
        post(pending.open_url, {}).then(function (res) {
          window.location.href = (res && res.url) || pending.files_url;
        }).catch(function () {
          window.location.href = pending.files_url;
        });
      };
    }

    var accept = $("#assignAccept");
    accept.onclick = function () {
      accept.disabled = true;
      post(cfg.acceptUrl.replace("0", pending.id), {}).then(function (res) {
        accept.disabled = false;
        if (res.ok) {
          hidePending();
          toast({ level: "success", title: t("تم الاستلام", "Accepted") });
          window.location.href = pending.task_url;
        } else {
          toast({
            level: "danger",
            title: t("الوقت خلص", "Too late"),
            body: t("التاسك رجعت لمين بعتها.", "The task went back to the sender.")
          });
          hidePending();
        }
      });
    };
    var decline = $("#assignDecline");
    decline.onclick = function () {
      // A refusal has to say why: without one the sender only learns it came
      // back, and has to go and ask before they can do anything about it.
      var why = reason ? reason.value.trim() : "";
      if (!why) {
        if (reason) { reason.focus(); }
        toast({
          level: "warning",
          title: t("اكتب سبب الرفض", "Say why"),
          body: t("اللي بعتلك محتاج يعرف يعمل إيه بعد كده.",
                  "The sender needs to know what to do next.")
        });
        return;
      }
      decline.disabled = true;
      post(cfg.declineUrl.replace("0", pending.id), { reason: why })
        .then(function (res) {
          decline.disabled = false;
          if (res && res.ok) { hidePending(); return; }
          toast({
            level: "danger",
            title: t("مقدرتش أرفض", "Could not decline"),
            body: (res && res.error) || ""
          });
        }).catch(function () { decline.disabled = false; });
    };

    beep(3, 980);
    runCountdown(pending.seconds_left, pending.window || 60);
  }

  function runCountdown(seconds, total) {
    clearInterval(state.countdownTimer);
    var ring = $("#assignRing");
    var num = $("#assignSeconds");
    var left = seconds;

    function paint() {
      if (!ring || !num) { return; }
      paintDeadlineLeft($("#assignDeadlineLeft"), state.pendingDeadline);
      num.textContent = Math.max(0, left);
      ring.style.setProperty("--pct", Math.max(0, (left / total) * 100));
      ring.classList.toggle("is-critical", left <= 15);
      if (left === 20 || left === 10 || left === 5) { beep(1, 1200); }
      if (left <= 0) {
        clearInterval(state.countdownTimer);
        hidePending();
        toast({
          level: "danger",
          title: t("عدى وقت الرد", "Response window expired"),
          body: t("اتخصم من تقييمك.", "A rating penalty was applied.")
        });
      }
      left -= 1;
    }
    paint();
    state.countdownTimer = setInterval(paint, 1000);
  }

  function hidePending() {
    state.pendingId = null;
    clearInterval(state.countdownTimer);
    var backdrop = $("#assignModal");
    if (backdrop) { backdrop.classList.add("hidden"); }
  }

  /* ------------------------------------------------------------ heartbeat */

  function tick() {
    get(cfg.heartbeatUrl + "?after=" + state.lastNotification)
      .then(function (data) {
        if (!data || !data.ok) { return; }

        (data.notifications || []).forEach(function (n) {
          state.lastNotification = Math.max(state.lastNotification, n.id);
          toast({
            level: n.level,
            title: state.lang === "ar" ? n.title_ar : n.title_en,
            body: state.lang === "ar" ? n.body_ar : n.body_en,
            url: n.url,
            sticky: n.level === "danger"
          });
          if (n.sound) { beep(2, 760); }
        });

        var bell = $("#bellCount");
        if (bell) {
          bell.textContent = data.unread || "";
          bell.classList.toggle("hidden", !data.unread);
        }

        Object.keys(data.counters || {}).forEach(function (key) {
          var node = $('[data-counter="' + key + '"]');
          if (!node) { return; }
          var value = Number(data.counters[key]) || 0;
          node.textContent = value;
          node.classList.toggle("is-hot", value > 0);
          node.classList.toggle("hidden", value === 0);
        });
        rollUpNavCounts();

        showPending(data.pending);
      })
      .catch(function () { /* offline: try again on the next tick */ });
  }

  function startHeartbeat() {
    if (!cfg.heartbeatUrl) { return; }
    tick();
    state.timer = setInterval(tick, cfg.pollMs || 3000);
  }

  /* ------------------------------------------------------------ task chat */

  function initChat() {
    var box = $("#chatBody");
    if (!box) { return; }
    var roomId = box.getAttribute("data-room");
    // The client-chat page (/ops/chats/) uses the same id for its composer
    // input, which carries no data-room. Without this guard that page polls
    // /api/rooms/null/messages/ every few seconds and fills the log with 404s.
    if (!roomId || roomId === "null") { return; }
    var last = Number(box.getAttribute("data-last") || 0);
    var form = $("#chatForm");
    var input = $("#chatInput");
    var files = $("#chatFiles");
    var fileList = $("#chatFileList");

    box.scrollTop = box.scrollHeight;

    function render(message) {
      var wrap = document.createElement("div");
      if (message.system) {
        wrap.className = "bubble bubble--system";
        wrap.innerHTML = '<div class="bubble__box">' + escapeHtml(message.body) + "</div>";
      } else {
        // Mirrors templates/shared/task_detail.html — keep the two in step.
        wrap.className = "bubble" +
          (message.from_client ? " bubble--client" : (message.mine ? " bubble--mine" : "")) +
          (message.relay_status === "failed" ? " bubble--failed" : "");

        var attachments = (message.attachments || []).map(function (a) {
          if (a.audio) { return voiceHtml(a.url, a.length); }
          return '<a class="file-pill" href="' + escapeHtml(a.url) +
            '" target="_blank" rel="noopener">' +
            svgIcon("paperclip", "ic--sm") + escapeHtml(a.name) +
            ' <span class="muted">' + escapeHtml(a.size) + "</span></a>";
        }).join("");

        var who = message.from_client
          ? svgIcon("phone", "ic--sm") +
            '<span data-ar="العميل" data-en="Client">' +
            escapeHtml(t("العميل", "Client")) + "</span>"
          : escapeHtml(message.sender) +
            (message.relay_status === "sent" ? svgIcon("check", "ic--sm") : "") +
            (message.relay_status === "failed" ? svgIcon("alert", "ic--sm") : "");

        wrap.innerHTML =
          '<div class="bubble__meta">' + who + " · " + message.time + "</div>" +
          '<div class="bubble__box">' + escapeHtml(message.body) +
          (attachments ? '<div class="files">' + attachments + "</div>" : "") + "</div>" +
          (message.relay_error
            ? '<div class="bubble__error">' + escapeHtml(message.relay_error) + "</div>"
            : "");
      }
      box.appendChild(wrap);
    }

    function poll() {
      get(cfg.chatFetchUrl.replace("0", roomId) + "?after=" + last).then(function (data) {
        if (!data || !data.messages || !data.messages.length) { return; }
        var stick = box.scrollTop + box.clientHeight >= box.scrollHeight - 60;
        data.messages.forEach(function (m) { render(m); last = Math.max(last, m.id); });
        if (stick) { box.scrollTop = box.scrollHeight; }
      }).catch(function () {});
    }

    if (files && fileList) {
      files.addEventListener("change", function () {
        fileList.innerHTML = Array.prototype.map.call(files.files, function (f) {
          return '<span class="file-pill">' + svgIcon("paperclip", "ic--sm") +
            escapeHtml(f.name) + "</span>";
        }).join("");
      });
    }

    if (form) {
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        var body = (input.value || "").trim();
        if (!body && (!files || !files.files.length)) { return; }
        var data = new FormData();
        data.append("body", body);
        if (files) {
          Array.prototype.forEach.call(files.files, function (f) { data.append("files", f); });
        }
        var button = form.querySelector("button[type=submit]");
        button.disabled = true;
        post(cfg.chatSendUrl.replace("0", roomId), data).then(function (res) {
          button.disabled = false;
          if (res.ok) {
            input.value = "";
            if (files) { files.value = ""; }
            if (fileList) { fileList.innerHTML = ""; }
            render(res.message);
            last = Math.max(last, res.message.id);
            box.scrollTop = box.scrollHeight;
            // The message is saved either way; only the trip to WhatsApp failed.
            if (res.relay_error) {
              toast({
                level: "danger",
                title: t("الرسالة محفوظة بس مروحتش للعميل",
                  "Saved, but it did not reach the client"),
                body: res.relay_error
              });
            }
          }
        });
      });

      input.addEventListener("keydown", function (event) {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          form.dispatchEvent(new Event("submit", { cancelable: true }));
        }
      });
    }

    setInterval(poll, cfg.pollMs || 3000);
  }

  /* --------------------------------------------------------- page actions */

  /**
   * Delegated so buttons inside content injected later (live inbox rows)
   * work without re-binding.
   */
  function initActions() {
    document.addEventListener("click", function (event) {
      var el = event.target && event.target.closest && event.target.closest("[data-action]");
      if (!el || el.disabled) { return; }

      var url = el.getAttribute("data-action");
      var confirmAr = el.getAttribute("data-confirm-ar");
      if (confirmAr && !window.confirm(t(confirmAr, el.getAttribute("data-confirm-en") || confirmAr))) {
        return;
      }
      el.disabled = true;
      var payload = {};
      var fieldId = el.getAttribute("data-field");
      if (fieldId) {
        var field = document.getElementById(fieldId);
        if (field) { payload[el.getAttribute("data-field-name") || "user"] = field.value; }
      }
      // Everything named inside this element rides along - for the buttons
      // that carry more than one value, like the hand-off that also sets
      // the translator's deadline.
      var extraId = el.getAttribute("data-extra");
      if (extraId) {
        var extra = document.getElementById(extraId);
        if (extra) {
          $$("input[name], select[name], textarea[name]", extra).forEach(function (input) {
            payload[input.name] = input.value;
          });
        }
      }
      post(url, payload).then(function (res) {
        el.disabled = false;
        if (res.ok) {
          toast({ level: "success", title: t("تم", "Done") });
          setTimeout(function () { window.location.reload(); }, 500);
        } else {
          toast({
            level: "danger",
            title: t("مش ممكن", "Not possible"),
            body: res.error || ""
          });
        }
      });
    });
  }

  /* -------------------------------------------------------- live inbox */

  function initInboxLive() {
    var list = $("#inboxList");
    if (!list) { return; }

    var url = list.getAttribute("data-live-url");
    var last = Number(list.getAttribute("data-last") || 0);
    var empty = $("#inboxEmpty");
    var params = "&state=" + encodeURIComponent(list.getAttribute("data-state") || "") +
      "&q=" + encodeURIComponent(list.getAttribute("data-q") || "");

    function poll() {
      get(url + "?after=" + last + params).then(function (data) {
        if (!data) { return; }
        if (data.last) { last = Math.max(last, Number(data.last) || 0); }
        if (!data.items || !data.items.length) {
          list.setAttribute("data-last", last);
          return;
        }
        data.items.forEach(function (item) {
          var holder = document.createElement("div");
          holder.innerHTML = item.html.trim();
          var node = holder.firstElementChild;
          if (!node) { return; }
          // One row per conversation: a reply replaces its conversation's
          // row instead of adding a second one, then rises to the top.
          if (item.thread) {
            $$("[data-thread]", list).forEach(function (row) {
              if (row.getAttribute("data-thread") === item.thread) { row.remove(); }
            });
          }
          node.classList.add("is-new");
          // Newest first, directly under the empty-state placeholder.
          list.insertBefore(node, empty ? empty.nextSibling : list.firstChild);
          last = Math.max(last, item.id);
        });
        list.setAttribute("data-last", last);
        if (empty) { empty.classList.add("hidden"); }
        applyLang(state.lang, false);   // translate the freshly injected markup
      }).catch(function () { /* offline: next tick will retry */ });
    }

    setInterval(poll, cfg.pollMs || 3000);
  }

  /* ------------------------------------------------ one open conversation */

  /**
   * The conversation page: the client's next reply appears at the bottom of
   * the letters already on screen, open, the way it would in Gmail.
   */
  function initMailThread() {
    var list = $("#threadList");
    if (!list) { return; }

    var expandAll = $("#threadExpandAll");
    if (expandAll) {
      expandAll.addEventListener("click", function () {
        $$(".mail", list).forEach(function (mail) {
          var open = mail.querySelector(".mail__open");
          if (!open) { return; }
          mail.classList.add("is-open");
          open.classList.remove("hidden");
        });
      });
    }

    // Opened from a notification or a long list: land on the open letter.
    var opened = $$(".mail.is-open", list);
    if (opened.length && list.children.length > 2 && opened[0].scrollIntoView) {
      opened[0].scrollIntoView({ block: "start" });
    }

    var url = list.getAttribute("data-live-url");

    // The cursors live on the list itself, because the reply box appends to
    // it too: a reply sent from this page must not come back a second time
    // from the poller.
    function poll() {
      var last = Number(list.getAttribute("data-last") || 0);
      var lastOut = Number(list.getAttribute("data-last-out") || 0);
      get(url + "?after=" + last + "&after_out=" + lastOut).then(function (data) {
        if (!data || !data.items || !data.items.length) { return; }
        data.items.forEach(function (item) {
          appendToThread(list, item.kind, item.id, item.html);
        });
      }).catch(function () { /* offline: next tick will retry */ });
    }

    setInterval(poll, cfg.pollMs || 3000);
  }

  /**
   * Put one letter ("in") or one of our replies ("out") at the bottom of an
   * open conversation, once, and move the matching cursor past it.
   */
  function appendToThread(list, kind, id, html) {
    var isOut = kind === "out";
    var attr = isOut ? "data-reply" : "data-message";
    var cursor = isOut ? "data-last-out" : "data-last";
    id = Number(id) || 0;
    if (list.querySelector("[" + attr + '="' + id + '"]')) { return; }

    var holder = document.createElement("div");
    holder.innerHTML = (html || "").trim();
    var node = holder.firstElementChild;
    if (!node) { return; }
    node.classList.add("is-new");
    list.appendChild(node);

    list.setAttribute(cursor, Math.max(Number(list.getAttribute(cursor) || 0), id));
    var count = $("#threadCount");
    if (count) { count.textContent = String(list.querySelectorAll(".mail").length); }
    applyLang(state.lang, false);
  }

  /* ------------------------------------------------------ replying to mail */

  /**
   * The reply box under a conversation: text, files, or both, sent to the
   * client by e-mail. Files are kept in an array rather than read off the
   * <input>, so they can be picked in several goes and removed one by one.
   */
  function initMailReply() {
    var form = $("#mailReply");
    if (!form) { return; }

    var LIMIT = 25 * 1024 * 1024;
    var list = $("#threadList");
    var pick = $("#mailReplyPick");
    var box = $("#mailReplyFiles");
    var body = form.querySelector("textarea[name=body]");
    var sendBtn = $("#mailReplySend");
    var files = [];

    function totalSize() {
      return files.reduce(function (sum, file) { return sum + (file.size || 0); }, 0);
    }

    function prettySize(bytes) {
      if (bytes < 1024) { return bytes + " B"; }
      if (bytes < 1024 * 1024) { return (bytes / 1024).toFixed(0) + " KB"; }
      return (bytes / 1024 / 1024).toFixed(1) + " MB";
    }

    function render() {
      box.innerHTML = files.map(function (file, index) {
        return '<span class="file-pill">' + svgIcon("paperclip", "ic--sm") +
          "<span>" + escapeHtml(file.name) + "</span>" +
          '<small class="muted mono">' + prettySize(file.size) + "</small>" +
          '<button type="button" class="file-pill__x" data-remove="' + index + '" ' +
          'title="' + escapeHtml(t("شيل الملف", "Remove the file")) + '">' +
          svgIcon("x", "ic--sm") + "</button></span>";
      }).join("");
    }

    if (pick) {
      pick.addEventListener("change", function () {
        Array.prototype.forEach.call(pick.files || [], function (file) { files.push(file); });
        pick.value = "";          // picking the same file again must still fire
        render();
        if (totalSize() > LIMIT) {
          toast({
            level: "warning",
            title: t("الملفات أكبر من 25 ميجا", "Files are over 25 MB"),
            body: t("شيل ملف أو اتنين قبل ما تبعت.", "Remove a file or two before sending.")
          });
        }
      });
    }

    box.addEventListener("click", function (event) {
      var x = event.target && event.target.closest && event.target.closest("[data-remove]");
      if (!x) { return; }
      files.splice(Number(x.getAttribute("data-remove")), 1);
      render();
    });

    var jump = $("#threadReplyJump");
    if (jump) {
      jump.addEventListener("click", function () {
        form.scrollIntoView({ behavior: "smooth", block: "start" });
        setTimeout(function () { body.focus(); }, 250);
      });
    }

    function send() {
      var text = (body.value || "").trim();
      if (!text && !files.length) {
        toast({ level: "warning", title: t("اكتب رد أو ارفق ملف", "Write a reply or attach a file") });
        body.focus();
        return;
      }
      if (totalSize() > LIMIT) {
        toast({ level: "danger", title: t("الملفات أكبر من 25 ميجا", "Files are over 25 MB") });
        return;
      }

      var data = new FormData();
      data.append("body", text);
      files.forEach(function (file) { data.append("files", file, file.name); });

      form.classList.add("is-sending");
      sendBtn.disabled = true;
      post(form.getAttribute("data-url"), data).then(function (res) {
        form.classList.remove("is-sending");
        sendBtn.disabled = false;
        // A failed send comes back rendered too, marked, so it is not lost.
        if (res && res.html && list) { appendToThread(list, "out", res.id, res.html); }
        if (res && res.ok) {
          body.value = "";
          files = [];
          render();
          // Replying claims the letters nobody had claimed yet.
          $$(".mail.is-unread", list).forEach(function (mail) { mail.classList.remove("is-unread"); });
          toast({ level: "success", title: t("الرد اتبعت", "Reply sent") });
        } else {
          toast({
            level: "danger",
            title: t("الرد متبعتش", "The reply was not sent"),
            body: (res && res.error) || ""
          });
        }
      }).catch(function () {
        form.classList.remove("is-sending");
        sendBtn.disabled = false;
        toast({ level: "danger", title: t("الرد متبعتش", "The reply was not sent") });
      });
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      send();
    });
    body.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        send();
      }
    });
  }

  /* ------------------------------------------------------------- the mail */

  /**
   * Open a letter in place. Delegated, so rows the live feed injects a minute
   * from now behave the same as the ones that came with the page.
   *
   * Clicks on the controls *inside* an open letter (the file checkboxes, the
   * convert button) must not fold it shut again, which is why only the row
   * button itself is listened for.
   */
  function initMailList() {
    document.addEventListener("click", function (event) {
      var row = event.target && event.target.closest &&
        event.target.closest("[data-mail-open]");
      if (!row) { return; }
      var mail = row.closest(".mail");
      if (!mail) { return; }
      var open = mail.querySelector(".mail__open");
      if (!open) { return; }
      var isOpen = mail.classList.toggle("is-open");
      open.classList.toggle("hidden", !isOpen);
    });

    var fetchBtn = $("#fetchMailBtn");
    if (!fetchBtn) { return; }
    fetchBtn.addEventListener("click", function () {
      fetchBtn.disabled = true;
      post(fetchBtn.getAttribute("data-url"), {}).then(function (res) {
        fetchBtn.disabled = false;
        if (!res.ok) {
          toast({ level: "danger", title: t("الجلب فشل", "Fetch failed"), body: res.error || "" });
          return;
        }
        var count = Number(res.created) || 0;
        toast({
          level: count ? "success" : "info",
          title: count
            ? t("وصل " + count + " ميل", count + " new e-mail")
            : t("مفيش ميلات جديدة", "No new mail")
        });
        // Only reload when there is something new to show; a reload that
        // changes nothing just loses the letter somebody had open.
        if (count) { setTimeout(function () { window.location.reload(); }, 600); }
      });
    });
  }

  function initAiCheck() {
    var button = $("#aiCheckBtn");
    if (!button) { return; }
    button.addEventListener("click", function () {
      var out = $("#aiResult");
      button.disabled = true;
      out.innerHTML = '<div class="muted">' + t("جاري المراجعة…", "Reviewing…") + "</div>";
      post(button.getAttribute("data-url"), {
        source_text: ($("#aiSource") || {}).value || "",
        translated_text: ($("#aiTranslated") || {}).value || ""
      }).then(function (res) {
        button.disabled = false;
        if (!res.ok) {
          out.innerHTML = '<div class="note note--high">' + svgIcon("alert") +
            "<div>" + escapeHtml(res.error || "error") + "</div></div>";
          return;
        }
        if (!res.issues || !res.issues.length) {
          out.innerHTML = '<div class="note note--ok">' + svgIcon("check-circle") + "<div>" +
            escapeHtml(t("مفيش أخطاء واضحة. ابعت الملفات في الشات للمراجعة.",
              "No obvious issues. Send the files in the chat for review.")) + "</div></div>";
          return;
        }
        var severityClass = { high: "note--high", medium: "note--warn", low: "note--info" };
        out.innerHTML =
          '<div class="muted" style="margin-bottom:10px;font-size:.84rem">' +
          escapeHtml(res.summary || "") + "</div>" +
          res.issues.map(function (issue) {
            var severity = issue.severity || "medium";
            return '<div class="note ' + (severityClass[severity] || "note--warn") + '">' +
              svgIcon("map-pin") + "<div>" +
              '<div class="note__where">' + escapeHtml(issue.location || "") + "</div>" +
              "<div>" + escapeHtml(state.lang === "ar" ? (issue.issue_ar || issue.issue_en) : (issue.issue_en || issue.issue_ar)) + "</div>" +
              "</div></div>";
          }).join("");
      });
    });
  }

  /* ------------------------------------------------- deliver to the client */

  function initDeliver() {
    var box = $("#deliverBox");
    if (!box) { return; }
    var url = box.getAttribute("data-url");
    var out = $("#deliverResult");
    var sendBtn = $("#deliverBtn");
    var skipBtn = $("#deliverSkipBtn");

    function run(send, button) {
      var data = new FormData();
      $$('input[name="attachments"]:checked', box).forEach(function (el) {
        data.append("attachments", el.value);
      });
      data.append("note", ($("#deliverNote") || {}).value || "");
      data.append("send", send ? "1" : "0");

      button.disabled = true;
      out.innerHTML = '<div class="muted mt" style="font-size:.8rem">' +
        escapeHtml(t("بيتبعت…", "Sending…")) + "</div>";

      post(url, data).then(function (res) {
        button.disabled = false;
        if (res.ok) {
          out.innerHTML = '<div class="note note--ok mt">' + svgIcon("check-circle") +
            "<div>" + escapeHtml(t("اتبعت وتم إقفال التاسك.", "Sent and the task is closed.")) +
            "</div></div>";
          toast({ level: "success", title: t("تم التسليم", "Delivered") });
          setTimeout(function () { window.location.reload(); }, 1200);
        } else {
          out.innerHTML = '<div class="note note--high mt">' + svgIcon("alert") +
            "<div>" + escapeHtml(res.error || t("التسليم فشل.", "Delivery failed.")) +
            "</div></div>";
        }
      });
    }

    sendBtn.addEventListener("click", function () { run(true, sendBtn); });
    skipBtn.addEventListener("click", function () {
      if (window.confirm(t("تقفل التاسك من غير ما تبعت للعميل؟",
        "Close the task without sending anything to the client?"))) {
        run(false, skipBtn);
      }
    });
  }

  /* --------------------------------------------- integration test buttons */

  function renderReport(target, res, okLabel) {
    if (res.ok) {
      var detail = [];
      if (res.number) { detail.push(res.number); }
      if (res.name) { detail.push(res.name); }
      if (res.quality) { detail.push("quality: " + res.quality); }
      if (res.host) { detail.push(res.host); }
      if (res.user) { detail.push(res.user); }
      if (res.sent) { detail.push(t("واتبعت رسالة اختبار", "test message sent")); }
      target.innerHTML = '<div class="note note--ok">' + svgIcon("check-circle") +
        "<div><strong>" + escapeHtml(okLabel) + "</strong>" +
        (detail.length ? '<div class="muted mono">' + escapeHtml(detail.join(" · ")) + "</div>" : "") +
        "</div></div>";
    } else {
      target.innerHTML = '<div class="note note--high">' + svgIcon("alert") + "<div>" +
        escapeHtml(state.lang === "ar" ? (res.error_ar || res.error_en) : (res.error_en || res.error_ar)) +
        "</div></div>";
    }
  }

  /** Save the settings form first — testing reads the database, not the page. */
  function saveSettingsForm() {
    var form = $("#settingsForm");
    if (!form) { return Promise.resolve({ ok: true }); }
    return fetch(form.getAttribute("action") || window.location.href, {
      method: "POST",
      headers: { "X-CSRFToken": csrf(), "X-Requested-With": "XMLHttpRequest" },
      body: new FormData(form),
      credentials: "same-origin"
    })
      .then(function (r) { return r.json().catch(function () { return { ok: r.ok }; }); })
      .catch(function () { return { ok: false }; });
  }

  function bindTest(buttonId, inputId, resultId, okLabelAr, okLabelEn) {
    var button = $("#" + buttonId);
    if (!button) { return; }
    var out = $("#" + resultId);

    button.addEventListener("click", function () {
      button.disabled = true;
      out.innerHTML = '<div class="muted" style="font-size:.8rem">' +
        escapeHtml(t("بيحفظ الإعدادات…", "Saving settings…")) + "</div>";

      saveSettingsForm().then(function (saved) {
        if (!saved.ok) {
          button.disabled = false;
          var fields = Object.keys(saved.errors || {});
          out.innerHTML = '<div class="note note--high">' + svgIcon("alert") + "<div>" +
            escapeHtml(t("الحفظ فشل — فيه حقل غلط: ", "Save failed — invalid field: ")) +
            escapeHtml(fields.join(", ") || t("راجع الحقول.", "check the fields.")) +
            "</div></div>";
          return;
        }
        out.innerHTML = '<div class="muted" style="font-size:.8rem">' +
          escapeHtml(t("بيجرب الاتصال…", "Testing the connection…")) + "</div>";
        return post(button.getAttribute("data-url"), { to: ($("#" + inputId) || {}).value || "" })
          .then(function (res) {
            button.disabled = false;
            renderReport(out, res, t(okLabelAr, okLabelEn));
          });
      });
    });
  }

  /* ------------------------------------------------------------ nav groups */

  /* The nav's sections fold. The one holding the page you are on is opened by
     the server, so nothing moves after the paint; anything you open or shut
     yourself is remembered in this browser. localStorage and not a cookie:
     it is a per-screen preference that the server has no use for, and a
     cookie would ride along on every request for the rest of the year. */

  var NAV_OPEN_KEY = "eagle_nav_open";

  function navOpenState() {
    try { return JSON.parse(localStorage.getItem(NAV_OPEN_KEY)) || {}; }
    catch (error) { return {}; }
  }

  /* A closed section still has to say what is waiting inside it - the mail
     badge is the whole reason anyone looks at the nav. */
  function rollUpNavCounts() {
    $$("[data-nav-group]").forEach(function (group) {
      var roll = $("[data-nav-roll]", group);
      if (!roll) { return; }
      var total = 0;
      $$("[data-counter]", group).forEach(function (node) {
        total += Number(node.textContent) || 0;
      });
      roll.textContent = total;
      roll.classList.toggle("is-hot", total > 0);
      roll.classList.toggle("hidden", total === 0);
    });
  }

  /* ------------------------------------------------------------ nav search */

  /* Type what you want - "كلمات الحظر", "باسورد الإيميل", "اجازات" - and go
     straight there. The index (nav.search_index) holds every page this
     person may open plus the sections inside pages, each with the words
     people actually use for it. Matching is forgiving on purpose: Arabic
     spelled any of the usual ways, filler words ignored, and the result
     that matches most of what you typed comes first. */

  var SEARCH_FILLER = ("عايز عاوز عايزه انا اروح روح فين ازاي ايه اعمل اشوف شوف افتح" +
    " احدث حدث تحديث اعدل عدل تعديل اغير غير تغيير صفحه صفحة بتاعت بتاع في من على عن" +
    " لل ال و يا i want to go open the page change update edit set how where a of")
    .split(" ");

  function normAr(text) {
    return String(text || "").toLowerCase()
      .replace(/[\u064B-\u0652\u0640]/g, "")
      .replace(/[\u0623\u0625\u0622]/g, "\u0627")
      .replace(/\u0629/g, "\u0647")
      .replace(/\u0649/g, "\u064A")
      .replace(/\u0624/g, "\u0648")
      .replace(/\u0626/g, "\u064A")
      .replace(/\s+/g, " ").trim();
  }

  function searchTokens(query) {
    var filler = SEARCH_FILLER.map(normAr);
    return normAr(query).split(" ").filter(function (tok) {
      return tok && filler.indexOf(tok) === -1;
    }).map(function (tok) {
      // "الحظر" should find "حظر": try the word without its article too.
      var bare = tok.length > 4 && tok.indexOf("\u0627\u0644") === 0 ? tok.slice(2) : tok;
      return { full: tok, bare: bare };
    });
  }

  function searchScore(row, tokens) {
    var name = normAr(row.ar + " " + row.en);
    var rest = normAr(row.keywords + " " + row.where_ar + " " + row.where_en);
    var score = 0, hits = 0;
    tokens.forEach(function (tok) {
      var inName = name.indexOf(tok.full) !== -1 || name.indexOf(tok.bare) !== -1;
      var inRest = rest.indexOf(tok.full) !== -1 || rest.indexOf(tok.bare) !== -1;
      if (inName) { score += 3; hits += 1; }
      else if (inRest) { score += 2; hits += 1; }
    });
    if (!hits) { return 0; }
    // Every word you typed found in one place beats a scatter of partials.
    if (hits === tokens.length) { score += 4; }
    // A section inside a page is the more exact answer when both match.
    if (row.href.indexOf("#") !== -1) { score += 1; }
    return score;
  }

  function initNavSearch() {
    var box = $("#navSearch");
    var input = $("#navSearchInput");
    var list = $("#navSearchResults");
    var data = $("#navSearchIndex");
    if (!box || !input || !list || !data) { return; }
    var index = [];
    try { index = JSON.parse(data.textContent) || []; } catch (error) { index = []; }
    var shown = [];
    var cursor = 0;

    function close() {
      list.classList.add("hidden");
      list.innerHTML = "";
      shown = [];
    }

    /* Pages come from the index in the page; tasks come from the server,
       because there are thousands and each person may open only theirs
       (api/search/tasks - Task.can_view as a queryset). The pages draw at
       once and the tasks join a moment later, under their own heading. */
    var tasksUrl = box.getAttribute("data-tasks-url") || "";
    var pages = [];
    var tasks = [];
    var taskTimer = null;
    var asked = 0;

    function pageRows() {
      return pages.map(function (row) {
        var label = state.lang === "ar" ? row.ar : row.en;
        var where = state.lang === "ar" ? row.where_ar : row.where_en;
        return '<a class="nav-search__row" role="option" href="' +
          escapeHtml(row.href) + '">' + svgIcon(row.icon, "ic--sm") +
          '<span class="nav-search__body"><b>' + escapeHtml(label) + "</b>" +
          '<span class="nav-search__where">' + escapeHtml(where) + "</span></span></a>";
      });
    }

    function taskRows() {
      return tasks.map(function (task) {
        var status = state.lang === "ar" ? task.status_ar : task.status_en;
        return '<a class="nav-search__row" role="option" href="' +
          escapeHtml(task.href) + '">' + svgIcon("layers", "ic--sm") +
          '<span class="nav-search__body"><b><span class="mono">' + escapeHtml(task.code) +
          "</span> " + escapeHtml(task.title) + "</b>" +
          '<span class="nav-search__where">' +
          escapeHtml([task.client, status].filter(Boolean).join(" · ")) +
          "</span></span></a>";
      });
    }

    function render() {
      shown = pages.concat(tasks);
      cursor = 0;
      var html = pageRows();
      if (tasks.length) {
        html.push('<div class="nav-search__head">' +
          escapeHtml(t("تاسكات", "Tasks")) + "</div>");
        html = html.concat(taskRows());
      }
      if (!shown.length) {
        list.innerHTML = '<div class="nav-search__empty">' +
          escapeHtml(t("مفيش حاجة بالاسم ده.", "Nothing by that name.")) + "</div>";
      } else {
        list.innerHTML = html.join("");
        var first = $(".nav-search__row", list);
        if (first) { first.classList.add("is-active"); }
      }
      list.classList.remove("hidden");
    }

    function askTasks(query) {
      clearTimeout(taskTimer);
      if (!tasksUrl || query.replace(/\s/g, "").length < 2) { return; }
      var ticket = ++asked;
      taskTimer = setTimeout(function () {
        get(tasksUrl + "?q=" + encodeURIComponent(query)).then(function (res) {
          // A slower answer to an older query must not paint over a newer one.
          if (ticket !== asked || !res || !res.ok) { return; }
          tasks = res.items || [];
          if (input.value.trim()) { render(); }
        }).catch(function () {});
      }, 220);
    }

    function draw() {
      var raw = input.value.trim();
      if (!raw) { asked += 1; close(); return; }
      var tokens = searchTokens(raw);
      pages = !tokens.length ? [] : index.map(function (row) {
        return { row: row, score: searchScore(row, tokens) };
      }).filter(function (hit) { return hit.score > 0; })
        .sort(function (a, b) { return b.score - a.score; })
        .slice(0, 8).map(function (hit) { return hit.row; });
      tasks = [];
      render();
      askTasks(raw);
    }

    function move(step) {
      var rows = $$(".nav-search__row", list);
      if (!rows.length) { return; }
      rows[cursor].classList.remove("is-active");
      cursor = (cursor + step + rows.length) % rows.length;
      rows[cursor].classList.add("is-active");
      rows[cursor].scrollIntoView({ block: "nearest" });
    }

    function go(row) {
      if (!row) { return; }
      var here = window.location.pathname;
      var bits = row.href.split("#");
      window.location.href = row.href;
      // Same page, different section: the browser only scrolls, so make
      // sure the highlight replays and the search gets out of the way.
      if (bits[0] === here && bits[1]) {
        var target = document.getElementById(bits[1]);
        if (target) {
          target.classList.remove("is-found");
          void target.offsetWidth;
          target.classList.add("is-found");
          target.scrollIntoView({ behavior: "smooth", block: "start" });
        }
        input.value = "";
        close();
      }
    }

    input.addEventListener("input", draw);
    input.addEventListener("focus", draw);
    input.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown") { event.preventDefault(); move(1); }
      else if (event.key === "ArrowUp") { event.preventDefault(); move(-1); }
      else if (event.key === "Enter") { event.preventDefault(); go(shown[cursor]); }
      else if (event.key === "Escape") { input.value = ""; close(); input.blur(); }
    });
    document.addEventListener("click", function (event) {
      if (!box.contains(event.target)) { close(); }
    });

    // Ctrl+K anywhere, or "/" when you are not already typing somewhere.
    document.addEventListener("keydown", function (event) {
      var typing = /^(INPUT|TEXTAREA|SELECT)$/.test((event.target || {}).tagName || "") ||
        (event.target && event.target.isContentEditable);
      var ctrlK = (event.ctrlKey || event.metaKey) && (event.key === "k" || event.key === "K");
      if (ctrlK || (event.key === "/" && !typing)) {
        event.preventDefault();
        var bar = $(".sidebar");
        if (bar && window.matchMedia("(max-width: 860px)").matches) { bar.classList.add("is-open"); }
        input.focus();
        input.select();
      }
    });

    // Arrived on a section from the search (or any #link): show where it is.
    if (window.location.hash) {
      var landed = document.getElementById(window.location.hash.slice(1));
      if (landed) { landed.classList.add("is-found"); }
    }
  }

  /* ---------------------------------------------------------- reset tasks */

  /* The admin's "start the tasks over" form (/panel/reset-tasks/). Posted
     from here so the backup that comes back can be saved as a file and the
     page can then move on; a refusal (wrong password) comes back as the
     page itself, and only its error line is lifted out of it. */
  /* -------------------------------------------------- hand-off preview page */

  /* /assignments/<id>/: the job's files and text, the time left to confirm,
     the time left to the deadline, and the two answers - the popup's job,
     on a page where the files can actually be read. */
  function initAssignPreview() {
    var root = $("#assignPreview");
    if (!root) { return; }
    var id = root.getAttribute("data-id");
    var deadline = root.getAttribute("data-deadline") || "";
    var taskUrl = root.getAttribute("data-task-url");
    var leftNode = $("#previewDeadlineLeft");
    paintDeadlineLeft(leftNode, deadline);
    setInterval(function () { paintDeadlineLeft(leftNode, deadline); }, 30000);

    if (!root.getAttribute("data-pending")) { return; }
    var seconds = Number(root.getAttribute("data-seconds")) || 0;
    var secNode = $("#previewSeconds");
    var accept = $("#previewAccept");
    var decline = $("#previewDecline");
    var reason = $("#previewReason");

    function closed(message) {
      if (accept) { accept.disabled = true; }
      if (decline) { decline.disabled = true; }
      toast({ level: "danger", title: message });
    }

    var timer = setInterval(function () {
      seconds -= 1;
      if (secNode) {
        secNode.textContent = Math.max(0, seconds) + "s";
        secNode.classList.toggle("is-critical", seconds <= 15);
      }
      if (seconds <= 0) {
        clearInterval(timer);
        closed(t("الوقت خلص — التاسك رجعت لمين بعتها.", "Time is up - the task went back."));
      }
    }, 1000);

    if (accept) {
      accept.addEventListener("click", function () {
        accept.disabled = true;
        post(cfg.acceptUrl.replace("0", id), {}).then(function (res) {
          if (res && res.ok) {
            clearInterval(timer);
            window.location.href = taskUrl;
            return;
          }
          closed(t("الوقت خلص", "Too late"));
        }).catch(function () { accept.disabled = false; });
      });
    }
    if (decline) {
      decline.addEventListener("click", function () {
        var why = reason ? reason.value.trim() : "";
        if (!why) {
          if (reason) { reason.focus(); }
          toast({ level: "warning", title: t("اكتب سبب الرفض", "Say why") });
          return;
        }
        decline.disabled = true;
        post(cfg.declineUrl.replace("0", id), { reason: why }).then(function (res) {
          if (res && res.ok) {
            clearInterval(timer);
            window.location.href = "/";
            return;
          }
          decline.disabled = false;
          toast({ level: "danger", title: t("مقدرتش أرفض", "Could not decline"),
                  body: (res && res.error) || "" });
        }).catch(function () { decline.disabled = false; });
      });
    }
  }

  /* The one-tap language buttons on the task form: fill the field, and mark
     which one is in it - typing by hand keeps the marks honest too. */
  function initLangPicks() {
    var picks = $$("[data-lang-pick]");
    if (!picks.length) { return; }
    function mark(fieldId) {
      var field = document.getElementById(fieldId);
      var value = field ? field.value.trim().toUpperCase() : "";
      picks.forEach(function (btn) {
        if (btn.getAttribute("data-lang-target") === fieldId) {
          btn.classList.toggle("is-on", btn.getAttribute("data-lang-pick") === value);
        }
      });
    }
    var fields = {};
    picks.forEach(function (btn) {
      var id = btn.getAttribute("data-lang-target");
      fields[id] = true;
      btn.addEventListener("click", function () {
        var field = document.getElementById(id);
        if (!field) { return; }
        field.value = btn.getAttribute("data-lang-pick");
        field.dispatchEvent(new Event("input", { bubbles: true }));
        mark(id);
      });
    });
    Object.keys(fields).forEach(function (id) {
      var field = document.getElementById(id);
      if (field) { field.addEventListener("input", function () { mark(id); }); }
      mark(id);
    });
  }

  function initResetTasks() {
    var form = $("#resetTasksForm");
    if (!form) { return; }
    var box = $("#resetError");
    var button = $("#resetSubmit");
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (button) { button.disabled = true; }
      fetch(window.location.pathname, {
        method: "POST",
        body: new FormData(form),
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin"
      }).then(function (res) {
        var next = res.headers.get("X-Eagle-Next");
        if (res.ok && next) {
          var name = "eagle-tasks-backup.json";
          var match = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "");
          if (match) { name = match[1]; }
          return res.blob().then(function (blob) {
            var link = document.createElement("a");
            link.href = URL.createObjectURL(blob);
            link.download = name;
            document.body.appendChild(link);
            link.click();
            setTimeout(function () { window.location.href = next; }, 600);
          });
        }
        return res.text().then(function (html) {
          var page = new DOMParser().parseFromString(html, "text/html");
          var error = page.getElementById("resetError");
          if (box) {
            box.textContent = error ? error.textContent.trim()
              : t("حصلت مشكلة. محدش اتمسح.", "Something went wrong. Nothing was deleted.");
            box.classList.remove("hidden");
          }
          var pass = $("#resetPassword");
          if (pass) { pass.value = ""; pass.focus(); }
          if (button) { button.disabled = false; }
        });
      }).catch(function () {
        if (box) {
          box.textContent = t("مشكلة في الاتصال. محدش اتمسح.", "Connection problem. Nothing was deleted.");
          box.classList.remove("hidden");
        }
        if (button) { button.disabled = false; }
      });
    });
  }

  function initNavGroups() {
    var groups = $$("[data-nav-group]");
    if (!groups.length) { return; }

    var saved = navOpenState();
    var settling = true;

    groups.forEach(function (group) {
      var key = group.getAttribute("data-nav-group");
      var standingHere = !!$(".nav__item.is-active", group);
      // The section you are standing in opens whatever was saved: a nav
      // that hides the page you are looking at is worse than no nav.
      if (!standingHere && saved[key] === false) { group.open = false; }
      if (!standingHere && saved[key] === true) { group.open = true; }

      group.addEventListener("toggle", function () {
        if (settling) { return; }
        var now = navOpenState();
        now[key] = group.open;
        try { localStorage.setItem(NAV_OPEN_KEY, JSON.stringify(now)); }
        catch (error) { /* private window: this session only, then */ }
        rollUpNavCounts();
      });
    });

    // Everything shut is a nav you have to click twice to use.
    if (!groups.some(function (group) { return group.open; })) {
      groups[0].open = true;
    }
    setTimeout(function () { settling = false; }, 0);
    rollUpNavCounts();
  }

  /* ------------------------------------------------------------- deadlines */

  /* The boxes ask "in how long", because that is how a client says it. This
     answers "which moment is that", live, underneath them - a number of
     hours is easy to type and hard to picture, and 48 where you meant 4 is
     otherwise a mistake you find out about two days later. */

  var DEADLINE_DAYS_AR = ["الحد", "الاتنين", "التلات", "الأربع", "الخميس", "الجمعة", "السبت"];
  var DEADLINE_DAYS_EN = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  var DEADLINE_UNIT_MINUTES = { days: 1440, hours: 60, minutes: 1 };

  function initDeadlineBoxes() {
    function pad(number) { return (number < 10 ? "0" : "") + number; }

    function speak(box) {
      var out = $("[data-deadline-out]", box);
      if (!out) { return; }

      var total = 0, typed = false, hasClock = false, bad = false;
      $$(".dur__num", box).forEach(function (input) {
        var unit = input.name.split("_").pop();
        if (unit === "hours" || unit === "minutes") { hasClock = true; }
        var raw = (input.value || "").trim();
        if (!raw) { return; }
        typed = true;
        var value = parseInt(raw, 10);
        if (isNaN(value) || value < 0) { bad = true; return; }
        total += value * (DEADLINE_UNIT_MINUTES[unit] || 0);
      });

      var was = $('input[type="hidden"]', box);
      var ar, en, quiet = true;
      if (bad) {
        ar = "الأرقام بس.";
        en = "Numbers only.";
      } else if (!typed) {
        // Blank leaves the deadline where it is - which on a new form is
        // nowhere. Say which of the two this is.
        ar = was && was.value ? "هيفضل زي ما هو" : "من غير ديدلاين";
        en = was && was.value ? "Left as it is" : "No deadline";
      } else if (total <= 0) {
        ar = "من غير ديدلاين";
        en = "No deadline";
      } else {
        var when = new Date(Date.now() + total * 60000);
        var day = pad(when.getDate()) + "-" + pad(when.getMonth() + 1) + "-" + when.getFullYear();
        var clock = pad(when.getHours()) + ":" + pad(when.getMinutes());
        ar = "يعني " + DEADLINE_DAYS_AR[when.getDay()] + " " + day
           + (hasClock ? " الساعة " + clock : "");
        en = DEADLINE_DAYS_EN[when.getDay()] + " " + day
           + (hasClock ? " at " + clock : "");
        quiet = false;
      }

      out.classList.toggle("is-none", quiet);
      out.setAttribute("data-ar", ar);
      out.setAttribute("data-en", en);
      out.textContent = t(ar, en);
    }

    $$("[data-deadline]").forEach(function (box) {
      box.addEventListener("input", function () { speak(box); });
      speak(box);
    });
  }

  /* --------------------------------------------------------- copy to clipboard */

  function initCopy() {
    $$("[data-copy]").forEach(function (button) {
      button.addEventListener("click", function () {
        var source = document.getElementById(button.getAttribute("data-copy"));
        if (!source) { return; }
        var text = source.textContent.trim();
        var done = function () { toast({ level: "success", title: t("اتنسخ", "Copied") }); };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done, function () {});
        } else {
          var helper = document.createElement("textarea");
          helper.value = text;
          document.body.appendChild(helper);
          helper.select();
          try { document.execCommand("copy"); done(); } catch (err) { /* ignore */ }
          helper.remove();
        }
      });
    });
  }

  /* --------------------------------------------------------- voice notes */

  /** Mirrors templates/partials/voice.html — keep the two in step. */
  function voiceHtml(url, length) {
    return '<div class="voice" data-voice>' +
      '<button class="voice__play" type="button" ' +
        'data-ar-title="تشغيل" data-en-title="Play" title="' +
        escapeHtml(t("تشغيل", "Play")) + '">' +
        '<span class="voice__icon voice__icon--play">' + svgIcon("play", "ic--sm") + "</span>" +
        '<span class="voice__icon voice__icon--pause">' + svgIcon("pause", "ic--sm") + "</span>" +
      "</button>" +
      '<div class="voice__bar" role="slider" tabindex="0" aria-label="Seek">' +
        '<span class="voice__fill"></span>' +
      "</div>" +
      '<span class="voice__time mono">' + escapeHtml(length || "0:00") + "</span>" +
      '<audio class="voice__audio" preload="metadata" src="' + escapeHtml(url) + '"></audio>' +
      "</div>";
  }

  /**
   * Voice notes, played by our own control.
   *
   * Every browser draws <audio controls> differently — Android Chrome renders
   * a squashed white pill that looks broken next to everything else — so the
   * markup carries a play button and a bar, and the <audio> element behind it
   * is only the engine. Bound once on the document so a bubble inserted by a
   * poll five minutes from now works without re-binding anything.
   */
  function initVoice() {
    var playing = null;   // only one voice note at a time, like a phone

    function clock(seconds) {
      if (!isFinite(seconds) || seconds < 0) { seconds = 0; }
      var whole = Math.floor(seconds);
      return Math.floor(whole / 60) + ":" + ("0" + (whole % 60)).slice(-2);
    }

    function paint(box) {
      var audio = box.querySelector(".voice__audio");
      var fill = box.querySelector(".voice__fill");
      var time = box.querySelector(".voice__time");
      var bar = box.querySelector(".voice__bar");
      if (!audio) { return; }
      var total = audio.duration;
      if (fill) {
        fill.style.width = (isFinite(total) && total > 0)
          ? ((audio.currentTime / total) * 100) + "%" : "0%";
      }
      if (time) {
        // Counting up while playing, total length while idle — the two
        // numbers people actually want at those two moments. Until metadata
        // arrives the browser reports NaN (or Infinity for a WebM recording),
        // so the length the server already rendered is left alone.
        if (!audio.paused || audio.currentTime) {
          time.textContent = clock(audio.currentTime);
        } else if (isFinite(total) && total > 0) {
          time.textContent = clock(total);
        }
      }
      if (bar) {
        bar.setAttribute("aria-valuemin", "0");
        bar.setAttribute("aria-valuemax", isFinite(total) ? Math.floor(total) : 0);
        bar.setAttribute("aria-valuenow", Math.floor(audio.currentTime || 0));
      }
    }

    function wire(box) {
      var audio = box.querySelector(".voice__audio");
      if (!audio || box.dataset.wired) { return audio; }
      box.dataset.wired = "1";
      audio.addEventListener("timeupdate", function () { paint(box); });
      audio.addEventListener("loadedmetadata", function () { paint(box); });
      audio.addEventListener("ended", function () {
        box.classList.remove("is-playing");
        audio.currentTime = 0;
        paint(box);
      });
      audio.addEventListener("error", function () {
        box.classList.add("is-broken");
        var time = box.querySelector(".voice__time");
        if (time) { time.textContent = t("مش متاح", "unavailable"); }
      });
      paint(box);
      return audio;
    }

    function stop(box) {
      var audio = box && box.querySelector(".voice__audio");
      if (audio) { audio.pause(); }
      if (box) { box.classList.remove("is-playing"); }
    }

    document.addEventListener("click", function (event) {
      var button = event.target.closest && event.target.closest(".voice__play");
      if (button) {
        var box = button.closest(".voice");
        var audio = wire(box);
        if (!audio) { return; }
        if (audio.paused) {
          if (playing && playing !== box) { stop(playing); }
          playing = box;
          box.classList.add("is-playing");
          audio.play().catch(function () { box.classList.remove("is-playing"); });
        } else {
          stop(box);
        }
        return;
      }

      var bar = event.target.closest && event.target.closest(".voice__bar");
      if (bar) {
        var seekBox = bar.closest(".voice");
        var seekAudio = wire(seekBox);
        if (!seekAudio || !isFinite(seekAudio.duration)) { return; }
        var rect = bar.getBoundingClientRect();
        var ratio = (event.clientX - rect.left) / rect.width;
        // The bar runs right-to-left in Arabic, so the same pixel means the
        // opposite fraction of the recording.
        if (document.documentElement.getAttribute("dir") === "rtl") {
          ratio = 1 - ratio;
        }
        seekAudio.currentTime = Math.max(0, Math.min(1, ratio)) * seekAudio.duration;
        paint(seekBox);
      }
    });

    // It announces itself as a slider and takes a tab stop, so it has to be
    // operable without a mouse — the native control it replaced was.
    document.addEventListener("keydown", function (event) {
      var bar = event.target.closest && event.target.closest(".voice__bar");
      if (!bar) { return; }
      var box = bar.closest(".voice");
      var audio = wire(box);
      if (!audio) { return; }

      var rtl = document.documentElement.getAttribute("dir") === "rtl";
      var back = rtl ? "ArrowRight" : "ArrowLeft";
      var forward = rtl ? "ArrowLeft" : "ArrowRight";

      if (event.key === " " || event.key === "Enter") {
        event.preventDefault();
        box.querySelector(".voice__play").click();
      } else if (event.key === back || event.key === forward) {
        if (!isFinite(audio.duration)) { return; }
        event.preventDefault();
        var step = event.key === forward ? 5 : -5;
        audio.currentTime = Math.max(0, Math.min(audio.duration, audio.currentTime + step));
        paint(box);
      }
    });

    // Metadata (and therefore the length) only loads once the element exists.
    document.addEventListener("play", function (event) {
      if (event.target && event.target.classList.contains("voice__audio")) {
        wire(event.target.closest(".voice"));
      }
    }, true);
  }

  /* -------------------------------------------------------------- presence */

  /* Mirrors PRESENCE_STATES in dashboard/templatetags/eagle_tags.py.
     "free" and "on" are the same condition worded for two different boards —
     the team screen asks who can take work, the staff screen who is signed in
     — so a cell keeps whichever of the two the server chose for it. */
  var PRESENCE_LABELS = {
    on:    { dot: "on",    ar: "نشط", en: "Online" },
    free:  { dot: "on",    ar: "فاضي", en: "Free" },
    busy:  { dot: "busy",  ar: "مشغول", en: "Busy" },
    shift: { dot: "shift", ar: "في الشيفت — مش فاتح", en: "On shift — not open" },
    off:   { dot: "off",   ar: "أوفلاين", en: "Offline" }
  };

  /**
   * Keeps the status dots current without a page refresh.
   *
   * Online means the site is open right now, so the value goes stale within a
   * couple of minutes of rendering — a dot that only told the truth at page
   * load could not answer "can I give this to them this minute", which is the
   * only reason the column exists.
   */
  function initPresence() {
    var cells = $$("[data-presence]");
    if (!cells.length || !cfg.presenceUrl) { return; }

    function paint(cell, state, seenAr, seenEn) {
      var words = PRESENCE_LABELS[state] || PRESENCE_LABELS.off;
      cell.dataset.state = state;

      var dot = cell.querySelector(".dot");
      if (dot) { dot.className = "dot dot--" + words.dot; }

      var label = cell.querySelector(".presence__state");
      if (label) {
        label.setAttribute("data-ar", words.ar);
        label.setAttribute("data-en", words.en);
        label.textContent = t(words.ar, words.en);
      }
      var seen = cell.querySelector(".presence__seen");
      if (seen && seenAr) {
        seen.setAttribute("data-ar", seenAr);
        seen.setAttribute("data-en", seenEn);
        seen.textContent = t(seenAr, seenEn);
        cell.setAttribute("title", t(seenAr, seenEn));
      }
    }

    function refresh() {
      get(cfg.presenceUrl).then(function (res) {
        if (!res || !res.ok) { return; }
        var byId = {};
        (res.people || []).forEach(function (row) { byId[row.id] = row; });
        $$("[data-presence]").forEach(function (cell) {
          var row = byId[cell.dataset.presence];
          if (!row) { return; }
          var state;
          if (row.online) {
            // Keep this board's own word for "available" — the server chose it.
            state = row.busy ? "busy" : (cell.dataset.free || "on");
          } else {
            state = row.on_shift ? "shift" : "off";
          }
          paint(cell, state, row.seen_ar, row.seen_en);
        });
      }).catch(function () { /* a dropped poll fixes itself next tick */ });
    }

    refresh();
    setInterval(function () {
      // No point asking while nobody is looking at the answer.
      if (!document.hidden) { refresh(); }
    }, 20000);
  }

  /* ----------------------------------------------------------------- boot */

  function init() {
    initVoice();
    initPresence();
    applyLang(state.lang, false);
    applyTheme(state.theme, false);

    $$("[data-lang-btn]").forEach(function (el) {
      el.addEventListener("click", function () { applyLang(el.getAttribute("data-lang-btn")); });
    });
    var themeBtn = $("#themeToggle");
    if (themeBtn) {
      themeBtn.addEventListener("click", function () {
        applyTheme(state.theme === "dark" ? "light" : "dark");
      });
    }
    var menuBtn = $(".menu-toggle");
    if (menuBtn) {
      menuBtn.addEventListener("click", function () {
        var bar = $(".sidebar");
        if (bar) { bar.classList.toggle("is-open"); }
      });
    }

    // Browsers block audio until the user interacts once.
    document.addEventListener("click", function unlock() {
      audioCtx();
      document.removeEventListener("click", unlock);
    });

    initActions();
    initChat();
    initAiCheck();
    initDeliver();
    initInboxLive();
    initMailThread();
    initMailReply();
    initMailList();
    initNavGroups();
    initNavSearch();
    initResetTasks();
    initLangPicks();
    initAssignPreview();
    initDeadlineBoxes();
    initCopy();
    bindTest("waTestBtn", "waTestTo", "waTestResult",
      "الاتصال بواتساب شغال", "WhatsApp connection is working");
    bindTest("mailTestBtn", "mailTestTo", "mailTestResult",
      "الاتصال بالإيميل شغال", "E-mail connection is working");
    startHeartbeat();
  }

  document.addEventListener("DOMContentLoaded", init);

  return {
    t: t, toast: toast, beep: beep, post: post, get: get,
    applyLang: applyLang, applyTheme: applyTheme, escapeHtml: escapeHtml,
    voiceHtml: voiceHtml, svgIcon: svgIcon
  };
})();
