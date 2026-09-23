/* =========================================================================
   Calls between colleagues - voice or video, browser to browser (WebRTC).

   The server only keeps the record and passes the two browsers' connection
   details between them (/api/calls/...). A ringing call reaches the callee
   through the heartbeat, so it rings on whatever page they have open.
   Nothing here involves a client.
   Depends on window.Eagle (app.js) for post/get/toast/t/beep.
   ========================================================================= */

(function () {
  "use strict";

  var E = window.Eagle;
  var overlay = document.getElementById("callOverlay");
  if (!E || !overlay) { return; }

  var RING_SECONDS = 45;

  var el = {
    face: document.getElementById("callFace"),
    who: document.getElementById("callWho"),
    state: document.getElementById("callState"),
    accept: document.getElementById("callAccept"),
    mute: document.getElementById("callMute"),
    cam: document.getElementById("callCam"),
    hang: document.getElementById("callHang"),
    remote: document.getElementById("callRemote"),
    self: document.getElementById("callSelf"),
    audio: document.getElementById("callAudio")
  };

  var s = {
    call: null,          // {id, status, video, caller, other, initials}
    pc: null,
    local: null,
    after: 0,            // last signal id seen
    poll: null,
    ring: null,
    clock: null,
    giveUp: null,
    pendingIce: [],
    declined: {}         // ids already turned down here, so the heartbeat
                         // does not ring them again before the server catches up
  };

  function url(name, id) {
    return (overlay.getAttribute("data-" + name + "-url") || "").replace("0", String(id));
  }

  function csrf() {
    var match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? match[1] : "";
  }

  /* ------------------------------------------------------------ the panel */

  function show(name, initials, state) {
    el.who.textContent = name || "—";
    el.face.textContent = initials || "?";
    el.state.textContent = state || "";
    overlay.classList.remove("hidden");
  }

  function setState(text) { el.state.textContent = text; }

  function buttons(mode) {
    // mode: "incoming" | "outgoing" | "live"
    el.accept.classList.toggle("hidden", mode !== "incoming");
    el.mute.classList.toggle("hidden", mode !== "live");
    el.cam.classList.toggle("hidden", mode !== "live" || !(s.call && s.call.video));
  }

  function startRinging() {
    stopRinging();
    E.beep(2, 880);
    s.ring = setInterval(function () { E.beep(2, 880); }, 2200);
  }

  function stopRinging() {
    if (s.ring) { clearInterval(s.ring); s.ring = null; }
  }

  function startClock(fromIso) {
    var start = fromIso ? new Date(fromIso).getTime() : Date.now();
    clearInterval(s.clock);
    function paint() {
      var sec = Math.max(0, Math.floor((Date.now() - start) / 1000));
      setState(Math.floor(sec / 60) + ":" + ("0" + (sec % 60)).slice(-2));
    }
    paint();
    s.clock = setInterval(paint, 1000);
  }

  /* ------------------------------------------------------------- plumbing */

  function media(video) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      return Promise.reject(new Error("unsupported"));
    }
    return navigator.mediaDevices.getUserMedia({ audio: true, video: !!video });
  }

  function send(kind, payload) {
    if (!s.call) { return; }
    E.post(url("signals", s.call.id), { kind: kind, payload: JSON.stringify(payload) })
      .catch(function () {});
  }

  function connection(ice) {
    var pc = new RTCPeerConnection({ iceServers: ice || [] });
    s.local.getTracks().forEach(function (track) { pc.addTrack(track, s.local); });
    pc.onicecandidate = function (event) {
      if (event.candidate) { send("ice", event.candidate.toJSON()); }
    };
    pc.ontrack = function (event) {
      var stream = event.streams[0];
      el.audio.srcObject = stream;
      if (s.call && s.call.video) {
        el.remote.srcObject = stream;
        el.remote.classList.remove("hidden");
        overlay.classList.add("is-video");
      }
    };
    pc.onconnectionstatechange = function () {
      if (pc.connectionState === "failed") {
        setState(E.t("الاتصال فشل - الشبكة مش سامحة", "Could not connect - the network is blocking it"));
      }
    };
    if (s.call && s.call.video) {
      el.self.srcObject = s.local;
      el.self.classList.remove("hidden");
    }
    return pc;
  }

  function addIce(candidate) {
    if (!s.pc) { return; }
    if (!s.pc.remoteDescription) { s.pendingIce.push(candidate); return; }
    s.pc.addIceCandidate(candidate).catch(function () {});
  }

  function flushIce() {
    var queue = s.pendingIce;
    s.pendingIce = [];
    queue.forEach(addIce);
  }

  function handle(signal) {
    var data;
    try { data = JSON.parse(signal.payload); } catch (err) { return; }
    if (signal.kind === "offer" && s.pc && !s.call.caller) {
      s.pc.setRemoteDescription(data).then(function () {
        flushIce();
        return s.pc.createAnswer();
      }).then(function (answer) {
        return s.pc.setLocalDescription(answer).then(function () { send("answer", answer); });
      }).catch(function () {});
    } else if (signal.kind === "answer" && s.pc && s.call.caller) {
      s.pc.setRemoteDescription(data).then(flushIce).catch(function () {});
    } else if (signal.kind === "ice") {
      addIce(data);
    }
  }

  function pollSignals() {
    if (!s.call) { return; }
    E.get(url("signals", s.call.id) + "?after=" + s.after).then(function (res) {
      if (!res || !res.ok || !s.call) { return; }
      (res.signals || []).forEach(function (signal) {
        s.after = Math.max(s.after, signal.id);
        handle(signal);
      });
      var call = res.call || {};
      if (call.status === "active" && s.call.status !== "active") {
        s.call.status = "active";
        stopRinging();
        clearTimeout(s.giveUp);
        buttons("live");
        startClock(call.answered_at);
      }
      if (call.status && call.status !== "ringing" && call.status !== "active") {
        var why = {
          declined: E.t("رفض المكالمة", "Declined"),
          missed: E.t("مردّش", "No answer"),
          ended: E.t("المكالمة خلصت", "Call ended")
        }[call.status] || "";
        finish(why);
      }
    }).catch(function () {});
  }

  function finish(message) {
    stopRinging();
    clearInterval(s.poll);
    clearInterval(s.clock);
    clearTimeout(s.giveUp);
    if (s.pc) { try { s.pc.close(); } catch (err) { /* already closed */ } }
    if (s.local) { s.local.getTracks().forEach(function (track) { track.stop(); }); }
    el.remote.srcObject = null;
    el.self.srcObject = null;
    el.audio.srcObject = null;
    el.remote.classList.add("hidden");
    el.self.classList.add("hidden");
    overlay.classList.remove("is-video");
    s.pc = null; s.local = null; s.pendingIce = []; s.after = 0;
    var ended = s.call;
    s.call = null;
    if (message) { setState(message); }
    setTimeout(function () {
      if (!s.call) { overlay.classList.add("hidden"); }
    }, message ? 1400 : 0);
    return ended;
  }

  function hangUp(reason) {
    if (!s.call) { overlay.classList.add("hidden"); return; }
    var id = s.call.id;
    if (reason === "declined") { s.declined[id] = true; }
    E.post(url("end", id), { reason: reason || "ended" }).catch(function () {});
    finish(reason === "declined" ? E.t("رفضت المكالمة", "Declined") : E.t("المكالمة خلصت", "Call ended"));
  }

  /* ---------------------------------------------------------- placing one */

  function placeCall(userId, name, initials, video) {
    if (s.call) { return; }
    show(name, initials, E.t("بفتح المايك…", "Opening the microphone…"));
    buttons("outgoing");
    media(video).then(function (stream) {
      s.local = stream;
      return E.post(overlay.getAttribute("data-start-url"), { user: userId, video: video ? "1" : "" });
    }).then(function (res) {
      if (!res || !res.ok) {
        finish((res && res.error) || E.t("مقدرتش أتصل.", "Could not call."));
        return;
      }
      s.call = res.call;
      s.pc = connection(res.ice);
      setState(E.t("بيرن…", "Ringing…"));
      startRinging();
      s.poll = setInterval(pollSignals, 1000);
      s.giveUp = setTimeout(function () { hangUp("missed"); }, RING_SECONDS * 1000);
      return s.pc.createOffer().then(function (offer) {
        return s.pc.setLocalDescription(offer).then(function () { send("offer", offer); });
      });
    }).catch(function () {
      finish(E.t("لازم تسمح للمتصفح يستخدم المايك.", "Allow the browser to use the microphone."));
    });
  }

  /* --------------------------------------------------------- taking one */

  function incoming(info) {
    if (!info || s.call || s.declined[info.id]) { return; }
    s.call = { id: info.id, status: "ringing", video: info.video, caller: false };
    show(info.from, info.initials,
      info.video ? E.t("مكالمة فيديو جاية…", "Incoming video call…")
                 : E.t("مكالمة صوتية جاية…", "Incoming voice call…"));
    buttons("incoming");
    startRinging();
    // Stop ringing if the caller gives up before this is answered.
    s.poll = setInterval(function () {
      if (s.call && s.call.status === "ringing" && !s.pc) {
        E.get(url("signals", s.call.id) + "?after=0").then(function (res) {
          var st = res && res.call && res.call.status;
          if (st && st !== "ringing" && s.call && !s.pc) {
            finish(E.t("مكالمة فايتة", "Missed call"));
          }
        }).catch(function () {});
      }
    }, 2000);
  }

  function answer() {
    if (!s.call || s.pc) { return; }
    stopRinging();
    clearInterval(s.poll);
    setState(E.t("بوصّل…", "Connecting…"));
    var id = s.call.id;
    media(s.call.video).then(function (stream) {
      s.local = stream;
      return E.post(url("answer", id), {});
    }).then(function (res) {
      if (!res || !res.ok) { finish(E.t("المكالمة خلصت.", "The call is over.")); return; }
      s.call = res.call;
      s.pc = connection(res.ice);
      buttons("live");
      startClock(res.call.answered_at);
      s.poll = setInterval(pollSignals, 1000);
      pollSignals();
    }).catch(function () {
      hangUp("declined");
      E.toast({ level: "danger",
        title: E.t("لازم تسمح للمتصفح يستخدم المايك.", "Allow the browser to use the microphone.") });
    });
  }

  /* ------------------------------------------------------------- buttons */

  el.accept.addEventListener("click", answer);
  el.hang.addEventListener("click", function () {
    if (!s.call) { overlay.classList.add("hidden"); return; }
    hangUp(s.call.status === "ringing" && !s.call.caller ? "declined"
      : s.call.status === "ringing" ? "missed" : "ended");
  });
  el.mute.addEventListener("click", function () {
    if (!s.local) { return; }
    var tracks = s.local.getAudioTracks();
    var on = tracks.length && tracks[0].enabled;
    tracks.forEach(function (track) { track.enabled = !on; });
    el.mute.classList.toggle("is-off", on);
  });
  el.cam.addEventListener("click", function () {
    if (!s.local) { return; }
    var tracks = s.local.getVideoTracks();
    var on = tracks.length && tracks[0].enabled;
    tracks.forEach(function (track) { track.enabled = !on; });
    el.cam.classList.toggle("is-off", on);
  });

  document.addEventListener("click", function (event) {
    var btn = event.target.closest && event.target.closest("[data-call-user]");
    if (!btn) { return; }
    placeCall(btn.getAttribute("data-call-user"), btn.getAttribute("data-call-name"),
      btn.getAttribute("data-call-initials"), btn.getAttribute("data-call-video") === "1");
  });

  /* Leaving the page ends the call - say so first, and if they go anyway,
     tell the server, so the other side is not left talking to nobody. */
  window.addEventListener("beforeunload", function (event) {
    if (s.call && s.call.status === "active") {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  window.addEventListener("pagehide", function () {
    if (!s.call || !navigator.sendBeacon) { return; }
    var data = new FormData();
    data.append("reason", s.call.status === "active" ? "ended" : "missed");
    data.append("csrfmiddlewaretoken", csrf());
    navigator.sendBeacon(url("end", s.call.id), data);
  });

  window.EagleCalls = { incoming: incoming, place: placeCall };
})();
