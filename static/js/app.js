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

  function showPending(pending) {
    if (!pending) { hidePending(); return; }
    if (state.pendingId === pending.id) { return; }
    state.pendingId = pending.id;

    var backdrop = $("#assignModal");
    if (!backdrop) { return; }
    backdrop.classList.remove("hidden");
    $("#assignTask").textContent = pending.task_code + " · " + pending.task_title;
    $("#assignClient").textContent = pending.client;
    $("#assignFrom").textContent = pending.assigned_by || "—";
    $("#assignDeadline").textContent = pending.deadline || "—";
    $("#assignNote").textContent = pending.note || "";
    $("#assignOpen").setAttribute("href", pending.task_url);

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
      post(cfg.declineUrl.replace("0", pending.id), {}).then(function () { hidePending(); });
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
        wrap.className = "bubble" + (message.mine ? " bubble--mine" : "");
        var attachments = (message.attachments || []).map(function (a) {
          return '<a class="file-pill" href="' + a.url + '" target="_blank" rel="noopener">' +
            svgIcon("paperclip", "ic--sm") + escapeHtml(a.name) +
            ' <span class="muted">' + escapeHtml(a.size) + "</span></a>";
        }).join("");
        wrap.innerHTML =
          '<div class="bubble__meta">' + escapeHtml(message.sender) + " · " + message.time + "</div>" +
          '<div class="bubble__box">' + escapeHtml(message.body) +
          (attachments ? '<div class="files">' + attachments + "</div>" : "") + "</div>";
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
        if (!data || !data.items || !data.items.length) { return; }
        data.items.forEach(function (item) {
          var holder = document.createElement("div");
          holder.innerHTML = item.html.trim();
          var node = holder.firstElementChild;
          if (!node) { return; }
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

  /* ----------------------------------------------------------------- boot */

  function init() {
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
    applyLang: applyLang, applyTheme: applyTheme, escapeHtml: escapeHtml
  };
})();
