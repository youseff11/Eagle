import type { DayStatusJson } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";

const TONES = new Set(["ok", "info", "wait", "dead"]);

/** A leave request's state as the badge the classic tables draw. */
export function LeaveStatusBadge({ status }: { status: DayStatusJson }) {
  const { lang } = usePreferences();
  return <span className={`badge${TONES.has(status.tone) ? ` badge--${status.tone}` : ""}`}>{lang === "ar" ? status.ar : status.en}</span>;
}

/** A word that comes in both languages, in the reader's. */
export function useLeaveWords() {
  const { lang } = usePreferences();
  return (value: { ar: string; en: string }) => (lang === "ar" ? value.ar : value.en);
}
