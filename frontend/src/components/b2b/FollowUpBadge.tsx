import type { FollowUpState } from "../../api/b2b";
import { usePreferences } from "../../i18n/Preferences";
import { Icon } from "../Icon";

/**
 * A row's next follow-up: the date, and where it stands - due today, late, or done (the Sales person reached out on or after
 * the day). The state is the server's (`b2b.follow_up_state`); this only draws it.
 */
export function FollowUpBadge({ date, state }: { date: string; state: FollowUpState }) {
  const { t } = usePreferences();
  if (!date) return <span className="mono">—</span>;
  return (
    <div data-follow-up={state || "none"}>
      <span className={state === "overdue" ? "mono deadline--late" : "mono"}>{date}</span>
      {state === "today" && <div className="chip chip--sm chip--open">{t("النهارده", "Today")}</div>}
      {state === "overdue" && <div className="chip chip--sm deadline--late">{t("متأخرة", "Overdue")}</div>}
      {state === "done" && (
        <div className="chip chip--sm chip--replied">
          <Icon name="check" size="sm" />
          {t("اتعملت", "Done")}
        </div>
      )}
    </div>
  );
}
