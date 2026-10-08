import { useNow } from "../hooks/useNow";
import { usePreferences } from "../i18n/Preferences";
import { Icon } from "./Icon";

const two = (value: number) => String(value).padStart(2, "0");

/**
 * What is left until a deadline, counted down every second from the moment the server wrote (an ISO time): `2 days 03:20:15`, and once it
 * has passed, how long ago, in the colour of a late date. The operation's page counts to the client's date, the translator's page to the
 * one their team leader chose for them (the same date, or a shorter one), and the leader's page to both. Nothing for a deadline that is not
 * there or a task that is done. `label` says whose it is when a page shows two.
 */
export function Countdown({ iso, state, label }: { iso: string | undefined; state: string; label?: string }) {
  const { t } = usePreferences();
  const now = useNow(1000);
  if (!iso || state === "done" || state === "none") return null;
  const target = Date.parse(iso);
  if (Number.isNaN(target)) return null;

  const late = target < now;
  const seconds = Math.floor(Math.abs(target - now) / 1000);
  const days = Math.floor(seconds / 86400);
  const clock = `${two(Math.floor((seconds % 86400) / 3600))}:${two(Math.floor((seconds % 3600) / 60))}:${two(seconds % 60)}`;
  const span = days > 0 ? `${days} ${t("يوم", days === 1 ? "day" : "days")} ${clock}` : clock;
  // Close to the end it turns the colour of "soon" with the server's own state, and past it the colour of "late".
  const tone = late ? "late" : state === "soon" || state === "late" ? state : "ok";

  return (
    // Not ``countdown``: that class is the round ring of the hand-off popup (118px, a conic gradient), and a line of text wearing it
    // is drawn as a big empty circle with the numbers hanging out of its edge.
    <span className={`row row--tight mono deadline-clock deadline--${tone}`} role="timer" aria-label={t("العد التنازلي للديدلاين", "Deadline countdown")}>
      <Icon name="timer" size="sm" />
      <span>
        {label ? `${label}: ` : ""}
        {late ? t(`فات من ${span}`, `Late by ${span}`) : t(`باقي ${span}`, `${span} left`)}
      </span>
    </span>
  );
}
