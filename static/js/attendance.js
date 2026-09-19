/* =========================================================================
   Eagle — the attendance card
   -------------------------------------------------------------------------
   Three jobs, and deliberately nothing else:

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

   3. Redraw the four buttons from whatever the server says the day looks
      like, so the card can never offer an action the server would refuse.
   ========================================================================= */

(function () {
  "use strict";

  var cfg = window.EAGLE_ATTENDANCE || {};
  var card = document.getElementById("punchCard");
  if (!card || !cfg.punchUrl) { return; }

  var statusBox = document.getElementById("punchStatus");
  var clockBox = document.getElementById("punchClock");
  var busy = false;

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

  function t(pair) {
    var lang = (window.EAGLE_CFG && window.EAGLE_CFG.lang) || "ar";
    return lang === "en" ? pair[1] : pair[0];
  }

  function say(pair, tone) {
    if (!statusBox) { return; }
    statusBox.textContent = pair ? t(pair) : "";
    statusBox.className = "punch__status " + (tone || "muted");
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

  /* ------------------------------------------------------------- rendering */

  function setText(field, value) {
    var node = card.querySelector('[data-field="' + field + '"]');
    if (node) { node.textContent = value; }
  }

  function render(day) {
    if (!day) { return; }
    card.dataset.state = day.state || "none";
    card.dataset.onBreak = day.on_break ? "1" : "0";
    setText("check_in", day.check_in || "—");
    setText("check_out", day.check_out || "—");
    setText("break_minutes", (day.break_minutes || 0) + "د");
    setText("hours", day.hours || "0:00");
    paintButtons();
  }

  function paintButtons() {
    var state = card.dataset.state;
    var onBreak = card.dataset.onBreak === "1";
    var show = {
      check_in: state === "none",
      break_start: state === "open" && !onBreak,
      break_end: state === "open" && onBreak,
      check_out: state === "open"
    };
    Object.keys(show).forEach(function (action) {
      var button = card.querySelector('[data-punch="' + action + '"]');
      if (!button) { return; }
      button.hidden = !show[action];
      button.disabled = busy;
    });
  }

  /* --------------------------------------------------------------- punching */

  function send(action, coords) {
    var body = new FormData();
    body.append("action", action);
    body.append("device", deviceToken());
    if (coords) {
      body.append("lat", coords.lat);
      body.append("lng", coords.lng);
      body.append("accuracy", coords.accuracy);
    }
    return fetch(cfg.punchUrl, {
      method: "POST",
      body: body,
      credentials: "same-origin",
      headers: {
        "X-CSRFToken": (document.cookie.match(/(^| )csrftoken=([^;]+)/) || [])[2] || "",
        "X-Requested-With": "XMLHttpRequest"
      }
    }).then(function (response) { return response.json(); });
  }

  function punch(action) {
    if (busy) { return; }
    busy = true;
    paintButtons();

    var wantsLocation = card.dataset.needsLocation === "1" &&
      (action === "check_in" || action === "check_out");

    var step = wantsLocation
      ? (say(TEXT.locating), position())
      : Promise.resolve(null);

    step.then(function (coords) {
      if (wantsLocation && !coords) { say(TEXT.denied, "warn"); }
      else { say(TEXT.sending); }
      return send(action, coords);
    }).then(function (data) {
      if (!data || !data.ok) {
        var lang = (window.EAGLE_CFG && window.EAGLE_CFG.lang) || "ar";
        var message = data && (lang === "en" ? data.en : data.ar);
        say(message ? [message, message] : TEXT.failed, "warn");
        if (window.Eagle && message) { window.Eagle.toast(message, "warning"); }
        return;
      }
      render(data.day);
      say([t(TEXT.done) + " " + data.at, t(TEXT.done) + " " + data.at], "ok");
      if (window.Eagle) { window.Eagle.toast(t(TEXT.done) + " " + data.at, "success"); }
    }).catch(function () {
      say(TEXT.failed, "warn");
    }).then(function () {
      busy = false;
      paintButtons();
    });
  }

  /* ------------------------------------------------------------------ clock */

  function tick() {
    if (!clockBox) { return; }
    var now = new Date();
    clockBox.textContent =
      ("0" + now.getHours()).slice(-2) + ":" + ("0" + now.getMinutes()).slice(-2);
  }

  card.addEventListener("click", function (event) {
    var button = event.target.closest("[data-punch]");
    if (button) { punch(button.dataset.punch); }
  });

  paintButtons();
  tick();
  window.setInterval(tick, 20000);
})();
