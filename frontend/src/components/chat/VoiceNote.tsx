import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from "react";
import { usePreferences } from "../../i18n/Preferences";
import { formatSeconds } from "../../lib/recorder";
import { Icon } from "../Icon";

/** The speeds a note is heard at, in the order the button goes through them. */
const RATES = [1, 1.5, 2];

/** How far an arrow key moves a note, in seconds. */
const STEP = 5;

/** A note moved to its very end ends at once and starts over; this is how close to the end it may be put. */
const END_GAP = 0.1;

/** `m:ss` as the server writes a length, in seconds (0 when it is not one). */
function lengthSeconds(text: string): number {
  const found = /^(\d+):(\d{2})$/.exec(text);
  return found ? Number(found[1]) * 60 + Number(found[2]) : 0;
}

/**
 * A voice note, played by our own control: a play button, a bar, the length and the speed.
 *
 * Every browser draws `<audio controls>` differently (Android Chrome draws a squashed white pill), so the
 * element behind it is only the engine, as in `Eagle.voiceHtml`. Only the file's own address reaches it, and
 * only an address on this site (`/files/...`).
 *
 * The length is the server's when it knows it (`length`: a recording made in the client chat, a pending one).
 * Where it does not - a note in a group, one the client sent, an audio file - it is the file's own, read once the
 * browser has the beginning of it, so a note never says `0:00` for what is minutes long. Until then the box says
 * nothing about its length instead of a wrong one.
 *
 * The bar is a slider: a tap or a drag puts the note at that place, the arrow keys move it by five seconds. It
 * needs the file to be served in parts (`Range`, see `views.serve_file`); a browser that is given the whole file in
 * one piece can neither measure it nor move inside it.
 */
export function VoiceNote({ url, length }: { url: string; length: string }) {
  const { t, dir } = usePreferences();
  const audio = useRef<HTMLAudioElement>(null);
  const bar = useRef<HTMLDivElement>(null);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [known, setKnown] = useState(0);
  const [measured, setMeasured] = useState("");
  const [rate, setRate] = useState(1);
  const [dragging, setDragging] = useState(false);
  const probing = useRef(false);
  /** The browser is being asked for the end of the file: where it says the note is, meanwhile, is not where it is. */
  const measuring = useRef(false);
  const dragRef = useRef(false);

  // The file's own length when the browser has said, else the server's.
  const span = known > 0 ? known : lengthSeconds(length);
  const progress = span > 0 ? Math.min(1, position / span) : 0;
  const rtl = dir === "rtl";

  // Leaving the page stops the sound: a detached <audio> keeps playing otherwise.
  useEffect(() => () => audio.current?.pause(), []);

  // A new file is a new length, from its start.
  useEffect(() => {
    setMeasured("");
    setKnown(0);
    setPosition(0);
    probing.current = false;
    measuring.current = false;
  }, [url]);

  // The speed outlives the file loading: a new source goes back to the default speed unless that is set too.
  useEffect(() => {
    const element = audio.current;
    if (!element) return;
    element.defaultPlaybackRate = rate;
    element.playbackRate = rate;
  }, [rate, url]);

  const toggle = () => {
    const element = audio.current;
    if (!element) return;
    if (element.paused) void element.play();
    else element.pause();
  };

  const faster = () => setRate((now) => RATES[(RATES.indexOf(now) + 1) % RATES.length]);

  /** What the browser knows of the file's length: a number of seconds, or nothing yet (a recording made by the browser has none until its end is found). */
  const learn = (element: HTMLAudioElement) => {
    const said = (heard: HTMLAudioElement) => {
      setKnown(heard.duration);
      if (length === "") setMeasured(formatSeconds(Math.round(heard.duration)));
    };
    if (Number.isFinite(element.duration) && element.duration > 0) {
      said(element);
    } else if (element.duration === Infinity && !probing.current) {
      // A file with no length in its header: asking for a place far past its end makes the browser read to the end and say.
      probing.current = true;
      measuring.current = true;
      const found = () => {
        element.removeEventListener("timeupdate", found);
        if (Number.isFinite(element.duration) && element.duration > 0) said(element);
        element.currentTime = 0;
        measuring.current = false;
      };
      element.addEventListener("timeupdate", found);
      element.currentTime = 1e101;
    }
  };

  /** Put the note at a place, in seconds. Nothing is moved while its length is not known: there is no place to put it. */
  const seek = (seconds: number) => {
    const element = audio.current;
    if (!element || span <= 0) return;
    const to = Math.min(Math.max(0, seconds), Math.max(0, span - END_GAP));
    element.currentTime = to;
    setPosition(to);
  };

  /** How far along the bar a pointer is, 0 to 1, from the side the bar fills from (the right one in Arabic). */
  const fractionAt = (event: ReactPointerEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    if (box.width <= 0) return 0;
    const along = (event.clientX - box.left) / box.width;
    return Math.min(1, Math.max(0, rtl ? 1 - along : along));
  };

  const grab = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (span <= 0 || (event.pointerType === "mouse" && event.button !== 0)) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dragRef.current = true;
    setDragging(true);
    setPosition(fractionAt(event) * span);
  };
  const drag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (dragRef.current) setPosition(fractionAt(event) * span);
  };
  const drop = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragRef.current) return;
    dragRef.current = false;
    setDragging(false);
    seek(fractionAt(event) * span);
  };
  /** The pointer was taken away (a scroll took over, a call came in): the note stays where it was. */
  const letGo = () => {
    if (!dragRef.current) return;
    dragRef.current = false;
    setDragging(false);
    setPosition(audio.current?.currentTime ?? 0);
  };

  const key = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const element = audio.current;
    if (!element || span <= 0) return;
    // The arrow points the way the bar fills: right in English, left in Arabic.
    const ahead = rtl ? "ArrowLeft" : "ArrowRight";
    const back = rtl ? "ArrowRight" : "ArrowLeft";
    let to: number | null = null;
    if (event.key === ahead || event.key === "ArrowUp") to = element.currentTime + STEP;
    else if (event.key === back || event.key === "ArrowDown") to = element.currentTime - STEP;
    else if (event.key === "Home") to = 0;
    else if (event.key === "End") to = span;
    if (to === null) return;
    event.preventDefault();
    seek(to);
  };

  const speed = `${rate}×`;
  const total = length || measured || "--:--";
  // Where it is while it is being heard or moved; what it is when it is not.
  const shown = playing || position >= 1 ? formatSeconds(position) : total;
  const classes = ["voice"];
  if (dragging) classes.push("is-dragging");

  return (
    <div className={classes.join(" ")} data-voice>
      <button
        className="voice__play"
        type="button"
        title={playing ? t("إيقاف", "Pause") : t("تشغيل", "Play")}
        aria-label={playing ? t("إيقاف", "Pause") : t("تشغيل", "Play")}
        onClick={toggle}
      >
        <Icon name={playing ? "pause" : "play"} size="sm" />
      </button>
      <div
        ref={bar}
        className="voice__bar"
        role="slider"
        tabIndex={span > 0 ? 0 : -1}
        aria-label={t("مكان التشغيل", "Playback position")}
        aria-disabled={span <= 0}
        aria-valuemin={0}
        aria-valuemax={Math.round(span)}
        aria-valuenow={Math.round(position)}
        aria-valuetext={span > 0 ? `${formatSeconds(position)} / ${formatSeconds(span)}` : undefined}
        onPointerDown={grab}
        onPointerMove={drag}
        onPointerUp={drop}
        onPointerCancel={letGo}
        onKeyDown={key}
      >
        <span className="voice__fill" style={{ width: `${progress * 100}%` }} />
      </div>
      <span className="voice__time mono" title={total}>
        {shown}
      </span>
      <button
        className={rate === 1 ? "voice__rate" : "voice__rate is-fast"}
        type="button"
        title={t("السرعة", "Speed")}
        aria-label={t(`السرعة ${speed}`, `Speed ${speed}`)}
        onClick={faster}
      >
        {speed}
      </button>
      <audio
        ref={audio}
        className="voice__audio"
        preload="metadata"
        src={url}
        onLoadedMetadata={(event) => learn(event.currentTarget)}
        onDurationChange={(event) => learn(event.currentTarget)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => {
          setPlaying(false);
          setPosition(0);
        }}
        onTimeUpdate={(event) => {
          if (dragRef.current || measuring.current) return;
          setPosition(event.currentTarget.currentTime);
        }}
      />
    </div>
  );
}
