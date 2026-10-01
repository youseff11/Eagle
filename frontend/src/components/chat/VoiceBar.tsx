import type { Voice } from "../../hooks/useVoiceRecorder";
import { usePreferences } from "../../i18n/Preferences";
import { formatSeconds } from "../../lib/recorder";
import { Icon } from "../Icon";

/**
 * The bar under the box while a voice note is made: the red dot and the clock while it records, then the
 * take to listen to, with the two things that can be done with it - send, or throw it away.
 *
 * What the microphone said no to is said here too: the person asked for something and nothing started.
 */
export function VoiceBar({
  voice,
  busy,
  maxBytes,
  onSend,
}: {
  voice: Voice;
  /** A message is on its way: the take waits for it, so the order of what was said is kept. */
  busy: boolean;
  /** The biggest take the server accepts (`me.limits.voice.bytes`). */
  maxBytes: number;
  onSend: () => void;
}) {
  const { t } = usePreferences();
  const recording = voice.phase === "recording";
  const ready = voice.phase === "ready";
  const tooBig = ready && voice.recorded !== null && voice.recorded.blob.size > maxBytes;

  const failure = {
    unsupported: t("المتصفح ده مش بيسجّل صوت.", "This browser cannot record audio."),
    denied: t(
      "مفيش إذن للمايك. اسمح للموقع يستخدمه من إعدادات المتصفح.",
      "Microphone permission denied. Allow this site to use it in the browser's settings.",
    ),
    failed: t("التسجيل ماشتغلش. اتأكد إن فيه مايك شغّال وجرّب تاني.", "Recording did not start. Check that a microphone is working and try again."),
  };

  return (
    <>
      {voice.failure !== "" && (
        <div className="cchat__count is-over" role="alert">
          {failure[voice.failure]}
        </div>
      )}
      {(recording || ready) && (
        <div className="cchat__rec" role="group" aria-label={t("رسالة صوتية", "Voice note")}>
          {recording && <span className="rec-dot" aria-hidden="true" />}
          <span className="rec-state">
            {recording ? t("بسجّل...", "Recording...") : t("اسمعها قبل ما تبعتها", "Listen before sending")}
          </span>
          <span className="mono" aria-label={t("المدة", "Length")}>
            {formatSeconds(voice.seconds)}
          </span>
          {ready && voice.url !== "" && <audio className="rec-preview" controls preload="metadata" src={voice.url} />}
          <span className="grow" />
          {recording && (
            <button type="button" className="btn btn--sm" onClick={voice.stop}>
              <Icon name="stop" size="sm" />
              <span>{t("وقّف", "Stop")}</span>
            </button>
          )}
          {ready && (
            <button type="button" className="btn btn--sm btn--primary" onClick={onSend} disabled={busy || tooBig}>
              <Icon name="send" size="sm" />
              <span>{t("ابعت", "Send")}</span>
            </button>
          )}
          <button
            type="button"
            className="icon-btn"
            onClick={voice.discard}
            title={t("إلغاء التسجيل", "Cancel the recording")}
            aria-label={t("إلغاء التسجيل", "Cancel the recording")}
          >
            <Icon name="trash" size="sm" />
          </button>
        </div>
      )}
      {tooBig && (
        <div className="cchat__count is-over" role="alert">
          {t("التسجيل أكبر من المسموح. سجّل أقصر.", "The recording is bigger than allowed. Record a shorter one.")}
        </div>
      )}
    </>
  );
}
