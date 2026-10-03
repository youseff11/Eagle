import { useEffect, useRef, useSyncExternalStore } from "react";
import { csrfToken } from "../api/client";
import { useNow } from "../hooks/useNow";
import { usePreferences } from "../i18n/Preferences";
import { calls, type CallState, type Notice } from "../lib/calls";
import { Icon } from "./Icon";

/** What the line under the name says, in both languages (the classic overlay's own words). */
const WORDS: Record<Exclude<Notice, "" | "could_not_call">, [string, string]> = {
  opening_mic: ["بفتح المايك…", "Opening the microphone…"],
  ringing: ["بيرن…", "Ringing…"],
  incoming_voice: ["مكالمة صوتية جاية…", "Incoming voice call…"],
  incoming_video: ["مكالمة فيديو جاية…", "Incoming video call…"],
  connecting: ["بوصّل…", "Connecting…"],
  network: ["الاتصال فشل - الشبكة مش سامحة", "Could not connect - the network is blocking it"],
  ended: ["المكالمة خلصت", "Call ended"],
  over: ["المكالمة خلصت", "Call ended"],
  declined_by_me: ["رفضت المكالمة", "Declined"],
  declined: ["رفض المكالمة", "Declined"],
  no_answer: ["مردّش", "No answer"],
  missed: ["مكالمة فايتة", "Missed call"],
  mic_denied: ["لازم تسمح للمتصفح يستخدم المايك.", "Allow the browser to use the microphone."],
};

/** The state of the page's one call, as a React value. */
export function useCall(): CallState {
  return useSyncExternalStore(calls.subscribe, calls.getState, calls.getState);
}

function Clock({ since }: { since: string }) {
  const now = useNow(1000);
  const start = since ? Date.parse(since) : now;
  const seconds = Math.max(0, Math.floor((now - (Number.isNaN(start) ? now : start)) / 1000));
  return <>{`${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`}</>;
}

/**
 * A call between two colleagues - ringing, calling and in progress - over whatever page the person is on, because a call
 * can come in anywhere (`templates/partials/call_overlay.html`). The audio and the video go browser to browser; nothing here
 * ever reaches a client. `lib/calls.ts` does the work; this draws what it says and passes the buttons on.
 */
export function CallOverlay() {
  const { t } = usePreferences();
  const call = useCall();
  const remote = useRef<HTMLVideoElement>(null);
  const self = useRef<HTMLVideoElement>(null);
  const audio = useRef<HTMLAudioElement>(null);

  // The streams are not React's: they are handed to the elements that play them.
  useEffect(() => {
    if (remote.current) remote.current.srcObject = call.video ? call.remote : null;
    if (audio.current) audio.current.srcObject = call.remote;
  }, [call.remote, call.video]);
  useEffect(() => {
    if (self.current) self.current.srcObject = call.video ? call.local : null;
  }, [call.local, call.video]);

  // Leaving the page ends the call: say so first while it is live, and if they go anyway tell the server, so the other end
  // is not left talking to nobody.
  const live = call.phase === "live";
  const open = call.phase !== "idle" && call.phase !== "ended";
  useEffect(() => {
    if (!open) return;
    const warn = (event: BeforeUnloadEvent) => {
      if (!live) return;
      event.preventDefault();
      event.returnValue = "";
    };
    const goodbye = () => calls.leaving(csrfToken());
    window.addEventListener("beforeunload", warn);
    window.addEventListener("pagehide", goodbye);
    return () => {
      window.removeEventListener("beforeunload", warn);
      window.removeEventListener("pagehide", goodbye);
    };
  }, [open, live]);

  if (call.phase === "idle") return null;

  const video = call.video && call.remote !== null;
  const line =
    call.phase === "live" ? (
      <Clock since={call.answeredAt} />
    ) : call.notice === "could_not_call" ? (
      call.detail || t("مقدرتش أتصل.", "Could not call.")
    ) : call.notice ? (
      t(...WORDS[call.notice])
    ) : (
      ""
    );

  return (
    <div className={`call${video ? " is-video" : ""}`} id="callOverlay" role="dialog" aria-live="assertive" aria-label={call.name} data-phase={call.phase}>
      <div className="call__stage">
        <video className={`call__remote${video ? "" : " hidden"}`} ref={remote} autoPlay playsInline />
        <video className={`call__self${call.video && call.local ? "" : " hidden"}`} ref={self} autoPlay playsInline muted />
        <audio ref={audio} autoPlay />
        <div className="call__card">
          <span className="avatar avatar--staff call__face">{call.initials || "?"}</span>
          <div className="call__who">{call.name || "—"}</div>
          <div className="call__state" id="callState">
            {line}
          </div>
        </div>
      </div>
      <div className="call__bar">
        {call.phase === "incoming" && (
          <button className="call__btn call__btn--ok" type="button" title={t("رد", "Answer")} aria-label={t("رد", "Answer")} onClick={() => void calls.answer()}>
            <Icon name="phone" />
          </button>
        )}
        {live && (
          <button
            className={`call__btn${call.muted ? " is-off" : ""}`}
            type="button"
            title={t("كتم المايك", "Mute")}
            aria-label={t("كتم المايك", "Mute")}
            aria-pressed={call.muted}
            onClick={() => calls.toggleMute()}
          >
            <Icon name="mic" />
          </button>
        )}
        {live && call.video && (
          <button
            className={`call__btn${call.cameraOff ? " is-off" : ""}`}
            type="button"
            title={t("قفل الكاميرا", "Camera off")}
            aria-label={t("قفل الكاميرا", "Camera off")}
            aria-pressed={call.cameraOff}
            onClick={() => calls.toggleCamera()}
          >
            <Icon name="video" />
          </button>
        )}
        <button className="call__btn call__btn--end" type="button" title={t("إنهاء", "Hang up")} aria-label={t("إنهاء", "Hang up")} onClick={() => void calls.pressHangUp()}>
          <Icon name="phone-off" />
        </button>
      </div>
    </div>
  );
}
