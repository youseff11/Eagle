import { useEffect, useRef, useState } from "react";
import { usePreferences } from "../../i18n/Preferences";
import { Icon } from "../Icon";

/**
 * A voice note, played by our own control: a play button, a bar and the length.
 *
 * Every browser draws `<audio controls>` differently (Android Chrome draws a squashed white pill), so the
 * element behind it is only the engine, as in `Eagle.voiceHtml`. Only the file's own address reaches it, and
 * only an address on this site (`/files/...`).
 */
export function VoiceNote({ url, length }: { url: string; length: string }) {
  const { t } = usePreferences();
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);

  // Leaving the page stops the sound: a detached <audio> keeps playing otherwise.
  useEffect(() => () => audio.current?.pause(), []);

  const toggle = () => {
    const element = audio.current;
    if (!element) return;
    if (element.paused) void element.play();
    else element.pause();
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
      <span className="voice__time mono">{length || "0:00"}</span>
      <audio
        ref={audio}
        className="voice__audio"
        preload="metadata"
        src={url}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => {
          setPlaying(false);
          setProgress(0);
        }}
        onTimeUpdate={(event) => {
          const element = event.currentTarget;
          setProgress(element.duration > 0 ? element.currentTime / element.duration : 0);
        }}
      />
    </div>
  );
}
