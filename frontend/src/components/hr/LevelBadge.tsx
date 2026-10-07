import type { Labelled } from "../../api/types";
import { useLeaveWords } from "../leave/shared";
import { usePreferences } from "../../i18n/Preferences";

/**
 * A translator's rung beside their name. The trainee is drawn as waiting (nothing is worked out on them yet); the rest are plain
 * names, because the grades are names and nothing reads them.
 */
export function LevelBadge({ level }: { level: Labelled }) {
  const words = useLeaveWords();
  const { t } = usePreferences();
  if (level.value === "trainee") {
    return (
      <span className="badge badge--wait" data-level="trainee" title={t("مفيش حسابات ولا خصومات لحد ما يترقّى", "No pay or deductions until promoted")}>
        {words(level)}
      </span>
    );
  }
  return (
    <span className="chip" data-level={level.value}>
      {words(level)}
    </span>
  );
}
