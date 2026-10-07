import { useEffect, useRef, useState } from "react";
import { usePreferences } from "../../i18n/Preferences";
import { formatSeconds } from "../../lib/recorder";
import { Icon } from "../Icon";

/**
 * A voice note, played by our own control: a play button, a bar and the length.
 *
 * Every browser draws `<audio controls>` differently (Android Chrome draws a squashed white pill), so the
 * element behind it is only the engine, as in `Eagle.voiceHtml`. Only the file's own address reaches it, and
 * only an address on this site (`/files/...`).
 *
 * The length is the server's when it knows it (`length`: a recording made in the client chat, a pending one).
 * Where it does not - a note in a group, one the client sent, an audio file - it is the file's own, read once the
 * browser has the beginning of it, so a note never says `0:00` for what is minutes long. Until then the box says
 * nothing about its length instead of a wrong one.
 */
export function VoiceNote({ url, length }: { url: string; length: string }) {
  const { t } = usePreferences();
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [measured, setMeasured] = useState("");
  const probing = useRef(false);

  // Leaving the page stops the sound: a detached <audio> keeps playing otherwise.
  useEffect(() => () => audio.current?.pause(), []);

  // A new file is a new length.
  useEffect(() => {
    setMeasured("");
    probing.current = false;
  }, [url]);

  const toggle = () => {
    const element = audio.current;
    if (!element) return;
    if (element.paused) void element.play();
    else element.pause();
  };

  /** What the browser knows of the file's length: a number of seconds, or nothing yet (a recording made by the browser has none until its end is found). */
  const learn = (element: HTMLAudioElement) => {
    if (length !== "") return;
    if (Number.isFinite(element.duration) && element.duration > 0) {
      setMeasured(formatSeconds(Math.round(element.duration)));
    } else if (element.duration === Infinity && !probing.current) {
      // A file with no length in its header: asking for a place far past its end makes the browser read to the end and say.
      probing.current = true;
      const found = () => {
        element.removeEventListener("timeupdate", found);
        if (Number.isFinite(element.duration) && element.duration > 0) setMeasured(formatSeconds(Math.round(element.duration)));
        element.currentTime = 0;
      };
      element.addEventListener("timeupdate", found);
      element.currentTime = 1e101;
    }
  };

  return (
    <div className="voice" data-voice>
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
        className="voice__bar"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(progress * 100)}
      >
        <span className="voice__fill" style={{ width: `${progress * 100}%` }} />
      </div>
      <span className="voice__time mono">{length || measured || "--:--"}</span>
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
          setProgress(0);
        }}
        onTimeUpdate={(event) => {
          const element = event.currentTarget;
          setProgress(element.duration > 0 && Number.isFinite(element.duration) ? element.currentTime / element.duration : 0);
        }}
      />
    </div>
  );
}
