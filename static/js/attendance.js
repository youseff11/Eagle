/* =========================================================================
   Eagle — attendance: the check-in screen and the attendance card
   -------------------------------------------------------------------------
   Loaded on every page for a signed-in person, because the check-in screen
   has to open wherever they are when their shift starts.

   1. Ask the browser for a position ONCE, at the moment a button is pressed,
      and send it with that one request. There is no watchPosition anywhere in
      this file, and there is not supposed to be: section 14 of the spec rules
      out continuous tracking, and the way to keep that promise is to have no
      code that could break it.

   2. Keep a random token in localStorage so the server can tell one browser
      from another. The token identifies the browser and nothing else - it is
      generated here, never derived from the machine, and a person can wipe it
      by clearing site data (they then land in HR's approval queue, which is
      exactly what should happen).

   3. The check-in screen (partials/attendance_gate.html). The server decides
      when it shows - at page load and on every heartbeat - and it cannot be
      closed until the person checks in. After the shift it comes back as a
      reminder: check out, or press Extra time.

   4. The card on /attendance/: redraw the buttons from whatever the server
      says the day looks like, so it never offers an action the server would
      refuse.

   Every time shown is Egypt time on a twelve-hour clock.
   ========================================================================= */

(function () {
  "use strict";

  var cfg = window.EAGLE_CFG || {};
  if (!cfg.attPunchUrl) { return; }

  var TEXT = {
    locating: ["بنحدد الموقع...", "Finding your location..."],
    denied: [
      "الموقع مرفوض من المتصفح — التسجيل هيتبعت من غيره والـHR هتراجعه.",
      "Location was blocked - the punch goes without it and HR will review it."
    ],
    sending: ["بنسجل...", "Recording..."],
    failed: ["مانفعش يتسجل. جرب تاني.", "Could not record it. Try again."],
    done: ["اتسجل", "Recorded"]
  };

  function lang() { return (window.EAGLE_CFG && window.EAGLE_CFG.lang) || "ar"; }
  function t(pair) { return lang() === "en" ? pair[1] : pair[0]; }
  function pick(both) { return both ? (lang() === "en" ? both.en : both.ar) : ""; }
  function ampm(text) { return window.Eagle ? window.Eagle.ampm(text) : (text || ""); }
  function nowClock() {
    return window.Eagle ? window.Eagle.cairoClock(new Date()) : "";
  }
  function toast(message, level) {
    if (window.Eagle && message) { window.Eagle.toast(message, level); }
  }

  /* ------------------------------------------------------------- the token */

  function deviceToken() {
    var key = "eagle.device";
    var token = "";
    try { token = window.localStorage.getItem(key) || ""; } catch (err) { token = ""; }
    if (token) { return token; }

    // A plain random value. Nothing about it is derived from the device.
    var bytes = new Uint8Array(16);
    if (window.crypto && window.crypto.getRandomValues) {
      window.crypto.getRandomValues(bytes);
    } else {
      for (var i = 0; i < bytes.length; i++) { bytes[i] = Math.floor(Math.random() * 256); }
    }
    token = Array.prototype.map.call(bytes, function (b) {
      return ("0" + b.toString(16)).slice(-2);
    }).join("");
    try { window.localStorage.setItem(key, token); } catch (err) { /* private mode */ }
    return token;
  }

  /* ---------------------------------------------------------- the position */

  function position() {
    // Resolves with null rather than rejecting: a refused or unavailable fix
    // is a thing to record and flag, not a reason to stop somebody clocking in.
    return new Promise(function (resolve) {
      if (!navigator.geolocation) { resolve(null); return; }
      var settled = false;
      var done = function (value) {
        if (settled) { return; }
        settled = true;
        resolve(value);
      };
      navigator.geolocation.getCurrentPosition(
        function (pos) {
          done({
            lat: pos.coords.latitude,
            lng: pos.coords.longitude,
            accuracy: Math.round(pos.coords.accuracy || 0)
          });
        },
        function () { done(null); },
        { enableHighAccuracy: true, timeout: 12000, maximumAge: 0 }
      );
      // Some browsers never call either callback when a permission prompt is
      // dismissed rather than answered.
      window.setTimeout(function () { done(null); }, 13000);
    });
  }

  /* --------------------------------------------------------------- sending */

  function send(action, coords) {
    var body = new FormData();
    body.append("action", action);
    body.append("device", deviceToken());
    if (coords) {
      body.append("lat", coords.lat);
      body.append("lng", coords.lng);
      body.append("accuracy", coords.accuracy);
    }
    return fetch(cfg.attPunchUrl, {
      method: "POST",
      body: body,
      credentials: "same-origin",
      headers: {
        "X-CSRFToken": (document.cookie.match(/(^| )csrftoken=([^;]+)/) || [])[2] || "",
        "X-Requested-With": "XMLHttpRequest"
      }
    }).then(function (response) { return response.json(); });
  }

  /* One punch, start to finish. ``say`` reports progress to whoever asked. */
  function punch(action, needsLocation, say) {
    say = say || function () {};
    var wantsLocation = needsLocation && (action === "check_in" || action === "check_out");
    var step = wantsLocation
      ? (say(TEXT.locating), position())
      : Promise.resolve(null);

    return step.then(function (coords) {
      if (wantsLocation && !coords) { say(TEXT.denied, "warn"); }
      else { say(TEXT.sending); }
      return send(action, coords);
    });
  }

  /* What the server said, as a message: a refusal, lateness, extra time. */
  function outcome(action, data) {
    if (!data || !data.ok) {
      var message = data && (lang() === "en" ? data.en : data.ar);
      return { ok: false, text: message || t(TEXT.failed), level: "warning" };
    }
    var at = ampm(data.at);
    if (action === "check_in" && data.late_minutes) {
      return {
        ok: true, level: "warning",
        text: lang() === "en"
          ? "Checked in at " + at + " - " + data.late_minutes + " minutes late. This went to HR."
          : "اتسجل حضورك " + at + " — متأخر " + data.late_minutes + " دقيقة، والتأخير اتحوّل للـHR."
      };
    }
    if (action === "check_out" && data.overtime_minutes) {
      return {
        ok: true, level: "success",
        text: lang() === "en"
          ? "Checked out at " + at + " - " + data.overtime_minutes + " minutes of extra time sent to HR for review."
          : "اتسجل انصرافك " + at + " — " + data.overtime_minutes + " دقيقة اكسترا تايم اتبعتت للـHR تراجعها."
      };
    }
    if (action === "extra_start") {
      return {
        ok: true, level: "success",
        text: lang() === "en"
          ? "Extra time started at " + at + ". Remember to check out when you finish."
          : "الاكسترا تايم بدأ " + at + ". متنساش تسجل انصراف لما تخلص."
      };
    }
    return { ok: true, level: "success", text: t(TEXT.done) + " " + at };
  }

  function onAttendancePage() { return !!document.getElementById("punchCard"); }

  /* ======================================================= the check-in gate */

  var gateBox = document.getElementById("attendanceGate");
  var gateData = null;
  var gateBusy = false;
  var dismissed = {};

  function dismissKey(data) { return data ? data.kind + ":" + data.date : ""; }

  function readDismissed() {
    try {
      var raw = window.sessionStorage.getItem("eagle.gate.dismissed");
      if (raw) { dismissed[raw] = true; }
    } catch (err) { /* nothing kept */ }
  }

  function gateSay(pair, tone) {
    var node = gateBox && gateBox.querySelector("[data-gate-status]");
    if (!node) { return; }
    node.textContent = pair ? (typeof pair === "string" ? pair : t(pair)) : "";
    node.className = "punch__status " + (tone || "muted");
  }

  function fill(name, value) {
    if (!gateBox) { return; }
    Array.prototype.forEach.call(
      gateBox.querySelectorAll('[data-gate-field="' + name + '"]'),
      function (node) { node.textContent = value || "—"; }
    );
  }

  function paintGate() {
    if (!gateBox || !gateData) { return; }
    gateBox.dataset.kind = gateData.kind;
    Array.prototype.forEach.call(gateBox.querySelectorAll("[data-gate]"), function (part) {
      part.hidden = part.getAttribute("data-gate") !== gateData.kind;
    });
    fill("shift", gateData.shift);
    fill("start", pick(gateData.start));
    fill("end", pick(gateData.end));
    fill("grace_until", pick(gateData.grace_until));
    fill("deadline", pick(gateData.deadline));
    fill("grace", String(gateData.grace || 0));
    fill("checkout_after", String(gateData.checkout_after || 0));
    fill("late_now", String(gateData.late_now || 0));
    var late = gateBox.querySelector("[data-gate-late]");
    if (late) { late.hidden = !gateData.late_now; }
    var clock = gateBox.querySelector("[data-gate-clock]");
    if (clock) { clock.textContent = nowClock(); }
    Array.prototype.forEach.call(gateBox.querySelectorAll("[data-gate-punch]"), function (b) {
      b.disabled = gateBusy;
    });
  }

  function openGate(data) {
    gateData = data;
    if (!gateBox) { return; }
    paintGate();
    gateBox.classList.remove("hidden");
    document.documentElement.classList.add("has-gate");
  }

  function closeGate() {
    if (!gateBox) { return; }
    gateBox.classList.add("hidden");
    document.documentElement.classList.remove("has-gate");
    gateSay(null);
  }

  /* Called at load and from every heartbeat with what the server decided. */
  function gate(data) {
    if (gateBusy) { return; }
    if (!data) { gateData = null; closeGate(); return; }
    // The reminder after the shift can be put off; the check-in cannot.
    if (data.kind === "check_out" && dismissed[dismissKey(data)]) { return; }
    openGate(data);
  }

  function gatePunch(action) {
    if (gateBusy || !gateData) { return; }
    gateBusy = true;
    paintGate();
    punch(action, !!gateData.needs_location, gateSay).then(function (data) {
      var result = outcome(action, data);
      if (!result.ok) {
        gateSay(result.text, "warn");
        toast(result.text, "warning");
        return;
      }
      toast(result.text, result.level);
      gateData = null;
      closeGate();
      if (onAttendancePage()) { window.location.reload(); }
    }).catch(function () {
      gateSay(TEXT.failed, "warn");
    }).then(function () {
      gateBusy = false;
      paintGate();
    });
  }

  if (gateBox) {
    readDismissed();
    gateBox.addEventListener("click", function (event) {
      var button = event.target.closest("[data-gate-punch]");
      if (button) { gatePunch(button.getAttribute("data-gate-punch")); return; }
      if (event.target.closest("[data-gate-later]") && gateData && gateData.kind === "check_out") {
        var key = dismissKey(gateData);
        dismissed[key] = true;
        try { window.sessionStorage.setItem("eagle.gate.dismissed", key); } catch (err) { /* ok */ }
        closeGate();
      }
    });
    // No Escape, no click-outside: the check-in screen stays until check-in.
    var initial = document.getElementById("attendanceGateData");
    if (initial) {
      try { gate(JSON.parse(initial.textContent || "null")); } catch (err) { /* bad json */ }
    }
    window.setInterval(function () {
      var clock = gateBox.querySelector("[data-gate-clock]");
      if (clock && !gateBox.classList.contains("hidden")) { clock.textContent = nowClock(); }
    }, 15000);
  }

  window.EagleAttendance = { gate: gate, punch: punch };

  /* ======================================================= the card itself */

  var card = document.getElementById("punchCard");
  if (!card) { return; }

  var statusBox = document.getElementById("punchStatus");
  var clockBox = document.getElementById("punchClock");
  var busy = false;

  function say(pair, tone) {
    if (!statusBox) { return; }
    statusBox.textContent = pair ? (typeof pair === "string" ? pair : t(pair)) : "";
    statusBox.className = "punch__status " + (tone || "muted");
  }

  function setText(field, value) {
    var node = card.querySelector('[data-field="' + field + '"]');
    if (node) { node.textContent = value; }
  }

  function afterShift() {
    var end = card.dataset.shiftEnd;
    return !!end && Date.now() >= Date.parse(end);
  }

  function render(day) {
    if (!day) { return; }
    card.dataset.state = day.state || "none";
    card.dataset.onBreak = day.on_break ? "1" : "0";
    card.dataset.extra = day.extra_running ? "1" : "0";
    setText("check_in", ampm(day.check_in) || "—");
    setText("check_out", ampm(day.check_out) || "—");
    setText("break_minutes", (day.break_minutes || 0) + "د");
    setText("hours", day.hours || "0:00");
    var extra = card.querySelector("[data-extra-line]");
    if (extra) {
      extra.hidden = !day.extra_started_at;
      setText("extra_started_at", ampm(day.extra_started_at) || "—");
    }
    paintButtons();
  }

  function paintButtons() {
    var state = card.dataset.state;
    var onBreak = card.dataset.onBreak === "1";
    var extraRunning = card.dataset.extra === "1";
    var show = {
      check_in: state === "none",
      break_start: state === "open" && !onBreak,
      break_end: state === "open" && onBreak,
      extra_start: state === "open" && !onBreak && !extraRunning && afterShift(),
      check_out: state === "open"
    };
    Object.keys(show).forEach(function (action) {
      var button = card.querySelector('[data-punch="' + action + '"]');
      if (!button) { return; }
      button.hidden = !show[action];
      button.disabled = busy;
    });
  }

  function cardPunch(action) {
    if (busy) { return; }
    busy = true;
    paintButtons();

    punch(action, card.dataset.needsLocation === "1", say).then(function (data) {
      var result = outcome(action, data);
      if (!result.ok) {
        say(result.text, "warn");
        toast(result.text, "warning");
        return;
      }
      render(data.day);
      say(result.text, result.level === "warning" ? "warn" : "ok");
      toast(result.text, result.level);
      if (window.EagleAttendance) { gate(null); }
    }).catch(function () {
      say(TEXT.failed, "warn");
    }).then(function () {
      busy = false;
      paintButtons();
    });
  }

  function tick() {
    if (clockBox) { clockBox.textContent = nowClock(); }
    paintButtons();
  }

  card.addEventListener("click", function (event) {
    var button = event.target.closest("[data-punch]");
    if (button) { cardPunch(button.dataset.punch); }
  });

  tick();
  window.setInterval(tick, 20000);
})();
