import { useMe } from "../../api/queries";
import type { DayStatusJson, HrBoardRow, HrFileLink, Stamp } from "../../api/types";
import { Icon } from "../Icon";
import { usePreferences } from "../../i18n/Preferences";

/** The people HR's pages are for: the HR role and the admin (the same ones the doors let in with the switch on). */
export function useHrAllowed() {
  const me = useMe();
  const user = me.data?.user;
  return { me, allowed: user !== undefined && (user.role === "hr" || user.is_admin) };
}

/** The owner alone: hiring is decided by them and nobody else. */
export function useOwnerAllowed() {
  const me = useMe();
  return { me, allowed: me.data?.user.is_admin === true };
}

/** Who may mark a candidate's test: a reviewer, a team leader, the owner. */
export function useReviewerAllowed() {
  const me = useMe();
  const user = me.data?.user;
  return { me, allowed: user !== undefined && (user.role === "reviewer" || user.role === "team_lead" || user.is_admin) };
}

/** A stored file as a chip that opens it in a new tab (the address is the protected one the server gave). */
export function FileChip({ file }: { file: HrFileLink }) {
  return (
    <a className="chip" href={file.url} target="_blank" rel="noopener noreferrer">
      <Icon name="paperclip" size="sm" />
      <span>{file.name}</span>
    </a>
  );
}

/** A time in the reader's language, or a dash. */
export function useStamp() {
  const { lang } = usePreferences();
  return (stamp: Stamp | null | undefined) => (stamp ? (lang === "ar" ? stamp.ar : stamp.en) : "—");
}

const TONES = new Set(["ok", "info", "wait", "dead"]);

/** A day's status as the badge the classic tables draw. */
export function StatusBadge({ status }: { status: DayStatusJson }) {
  const { lang } = usePreferences();
  return <span className={`badge${TONES.has(status.tone) ? ` badge--${status.tone}` : ""}`}>{lang === "ar" ? status.ar : status.en}</span>;
}

/** What else is worth saying about a day: lateness, an early leave, a shortfall, overtime, an office day punched from outside. */
export function DayBadges({ row }: { row: HrBoardRow }) {
  const { t } = usePreferences();
  const stamp = useStamp();
  return (
    <>
      <StatusBadge status={row.status} />
      {row.late_minutes > 0 && (
        <span className="badge badge--wait mono">
          {t("تأخير", "Late")} {row.late_minutes}
          {t("د", "m")}
        </span>
      )}
      {row.early_leave_minutes > 0 && (
        <span className="badge badge--wait mono">
          {t("مبكر", "Early")} {row.early_leave_minutes}
          {t("د", "m")}
        </span>
      )}
      {row.short_minutes > 0 && (
        <span className="badge badge--dead mono">
          {t("ناقص", "Short")} {row.short_minutes}
          {t("د", "m")}
        </span>
      )}
      {row.overtime_minutes > 0 && (
        <span className="badge badge--ok mono">
          OT {row.overtime_minutes}
          {t("د", "m")}
        </span>
      )}
      {row.off_site && <span className="badge badge--dead">{t("بره النطاق", "Off site")}</span>}
      {row.extra_started_at && (
        <span className="badge badge--info mono">
          {t("اكسترا من", "Extra from")} {stamp(row.extra_started_at)}
        </span>
      )}
      {row.checkout_missed && <span className="badge badge--dead">{t("مسجلش انصراف — مش محسوب", "No check-out - not counted")}</span>}
    </>
  );
}
