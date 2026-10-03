import { usePreferences } from "../../i18n/Preferences";
import { calls } from "../../lib/calls";
import { useCall } from "../CallOverlay";
import { Icon } from "../Icon";

/**
 * The two buttons on a chat with a colleague that ring them: a voice call and a video call (`data-call-user` on the classic
 * page). Only a colleague has them - a client is never called from here - and while a call is on the screen they are off,
 * because the overlay is the one place a call is placed from and ended.
 */
export function CallButtons({ code, name, initials }: { code: string; name: string; initials: string }) {
  const { t } = usePreferences();
  const call = useCall();
  const person = /^u(\d+)$/.exec(code)?.[1];
  if (!person) return null;
  const busy = call.phase !== "idle" && call.phase !== "ended";
  const place = (video: boolean) => void calls.place({ userId: Number(person), name, initials }, video);
  return (
    <>
      <button
        type="button"
        className="icon-btn cchat__call"
        disabled={busy}
        title={t("مكالمة صوتية", "Voice call")}
        aria-label={t("مكالمة صوتية", "Voice call")}
        onClick={() => place(false)}
      >
        <Icon name="phone" />
      </button>
      <button
        type="button"
        className="icon-btn cchat__call"
        disabled={busy}
        title={t("مكالمة فيديو", "Video call")}
        aria-label={t("مكالمة فيديو", "Video call")}
        onClick={() => place(true)}
      >
        <Icon name="video" />
      </button>
    </>
  );
}
