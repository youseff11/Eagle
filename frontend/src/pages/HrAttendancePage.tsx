import { Link, Navigate, useSearchParams } from "react-router";
import { useHrBoard } from "../api/queries";
import { DayBadges, useHrAllowed, useStamp } from "../components/hr/shared";
import { Waiting } from "../components/accounts/shared";
import { Icon } from "../components/Icon";
import { usePreferences } from "../i18n/Preferences";
import { minutesHm } from "../lib/payroll";

/** The filters the board understands: anything else in the address is not forwarded to the door. */
const FILTERS = ["view", "date", "user", "role", "day_mode", "shift", "status", "flagged"] as const;

/**
 * Everybody's attendance for a day, a week or a month. The filters live in the address, so a view is a link that can be sent. The
 * day view also names who was rostered and has no row at all: the people a table of rows would otherwise draw invisible.
 */
export function HrAttendancePage() {
  const { t, lang } = usePreferences();
  const stamp = useStamp();
  const { me, allowed } = useHrAllowed();
  const [params, setParams] = useSearchParams();
  const kept = new URLSearchParams();
  for (const name of FILTERS) {
    const value = params.get(name);
    if (value) kept.set(name, value);
  }
  const search = kept.toString();
  const query = useHrBoard(search, allowed);
  const data = query.data;

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!data) return <Waiting failed={query.isError} />;

  const set = (name: (typeof FILTERS)[number], value: string) => {
    const next = new URLSearchParams(kept);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next);
  };
  const words = (value: { ar: string; en: string }) => (lang === "ar" ? value.ar : value.en);
  const view = data.view;
  const flagged = kept.get("flagged") === "1";

  return (
    <>
      <div className="page-head">
        <h1>{t("لوحة الحضور", "Attendance board")}</h1>
        <div className="page-head__sub mono">
          {data.first_day} → {data.last_day}
        </div>
        <div className="grow" />
        {(data.flagged_count > 0 || flagged) && (
          <button className={`btn btn--sm${flagged ? " btn--primary" : ""}`} type="button" onClick={() => set("flagged", flagged ? "" : "1")}>
            <Icon name="alert" size="sm" />
            <span>{t("محتاج مراجعة", "Needs review")}</span>
            <span className="mono">{data.flagged_count}</span>
          </button>
        )}
      </div>

      <div className="grid grid--4">
        <div className="kpi">
          <div className="kpi__label">{t("حاضر", "Present")}</div>
          <div className="kpi__value mono">{data.totals.present}</div>
        </div>
        <div className={`kpi${data.totals.late ? " kpi--warn" : ""}`}>
          <div className="kpi__label">{t("تأخير", "Late")}</div>
          <div className="kpi__value mono">{data.totals.late}</div>
        </div>
        <div className={`kpi${data.totals.off_site ? " kpi--danger" : ""}`}>
          <div className="kpi__label">{t("بره النطاق", "Off site")}</div>
          <div className="kpi__value mono">{data.totals.off_site}</div>
        </div>
        <div className="kpi">
          <div className="kpi__label">{t("ساعات", "Hours")}</div>
          <div className="kpi__value mono">{minutesHm(data.totals.minutes)}</div>
        </div>
      </div>

      <div className="card card--flat">
        <div className="picker">
          <div className="picker__row">
            <div className="tabs" role="tablist">
              {(
                [
                  ["day", "يومي", "Day"],
                  ["week", "أسبوعي", "Week"],
                  ["month", "شهري", "Month"],
                ] as const
              ).map(([value, ar, en]) => (
                <button
                  key={value}
                  type="button"
                  role="tab"
                  aria-selected={view === value}
                  className={`tab${view === value ? " is-active" : ""}`}
                  onClick={() => set("view", value === "day" ? "" : value)}
                >
                  {t(ar, en)}
                </button>
              ))}
            </div>
            <input className="input" type="date" aria-label={t("اليوم", "Date")} value={kept.get("date") ?? data.date} onChange={(event) => set("date", event.target.value)} />
            <select className="input" aria-label={t("الموظف", "Employee")} value={kept.get("user") ?? ""} onChange={(event) => set("user", event.target.value)}>
              <option value="">{t("كل الموظفين", "Everyone")}</option>
              {data.options.people.map((one) => (
                <option key={one.id} value={one.id}>
                  {one.name}
                </option>
              ))}
            </select>
            <select className="input" aria-label={t("الدور", "Role")} value={kept.get("role") ?? ""} onChange={(event) => set("role", event.target.value)}>
              <option value="">{t("كل الأدوار", "All roles")}</option>
              {data.options.roles.map((one) => (
                <option key={one.value} value={one.value}>
                  {words(one)}
                </option>
              ))}
            </select>
            <select className="input" aria-label={t("النظام", "Mode")} value={kept.get("day_mode") ?? ""} onChange={(event) => set("day_mode", event.target.value)}>
              <option value="">{t("كل الأنظمة", "All modes")}</option>
              {data.options.day_modes.map((one) => (
                <option key={one.value} value={one.value}>
                  {words(one)}
                </option>
              ))}
            </select>
            <select className="input" aria-label={t("الشيفت", "Shift")} value={kept.get("shift") ?? ""} onChange={(event) => set("shift", event.target.value)}>
              <option value="">{t("كل الشيفتات", "All shifts")}</option>
              {data.options.shifts.map((one) => (
                <option key={one} value={one}>
                  {one}
                </option>
              ))}
            </select>
            <select className="input" aria-label={t("الحالة", "Status")} value={kept.get("status") ?? ""} onChange={(event) => set("status", event.target.value)}>
              <option value="">{t("كل الحالات", "All statuses")}</option>
              {data.options.statuses.map((one) => (
                <option key={one.value} value={one.value}>
                  {words(one)}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {data.missing.length > 0 && (
        <div className="note note--warn" data-note="missing">
          <Icon name="alert" />
          <div>
            <strong>{t("مسجلوش حضور النهارده", "No check-in today")}</strong>
            <div className="row row--tight mt">
              {data.missing.map((one) => (
                <span key={one.user.id} className="chip">
                  {one.user.name} <span className="mono muted">{one.schedule}</span>
                </span>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="card">
        <div className="card__head">
          <Icon name="users" />
          <h3>{t("السجل", "The record")}</h3>
        </div>
        <div className="table-wrap">
          <table className="table" data-table="board">
            <thead>
              <tr>
                <th>{t("الموظف", "Employee")}</th>
                <th>{t("اليوم", "Date")}</th>
                <th>{t("النظام", "Mode")}</th>
                <th>{t("الشيفت", "Shift")}</th>
                <th>{t("حضور", "In")}</th>
                <th>{t("انصراف", "Out")}</th>
                <th>{t("ساعات", "Hours")}</th>
                <th>{t("الحالة", "Status")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <tr key={row.id} data-day={row.id}>
                  <td>
                    {row.user.name}
                    {row.needs_review && <span className="badge badge--wait">{t("مراجعة", "Review")}</span>}
                  </td>
                  <td className="mono">{row.date}</td>
                  <td>{row.work_mode ? <span className="chip">{words(row.work_mode)}</span> : "—"}</td>
                  <td className="mono muted">{row.schedule || "—"}</td>
                  <td className={`mono${row.late_minutes ? " deadline--late" : ""}`}>{stamp(row.check_in)}</td>
                  <td className="mono">
                    {row.is_open ? <span className="badge badge--work">{t("لسه شغال", "Still open")}</span> : stamp(row.check_out)}
                  </td>
                  <td className="mono">{minutesHm(row.work_minutes)}</td>
                  <td>
                    <DayBadges row={row} />
                  </td>
                  <td>
                    <Link className="btn btn--sm btn--ghost" to={`/hr/attendance/${row.id}`}>
                      <Icon name="pen" size="sm" />
                      <span>{t("عدّل", "Edit")}</span>
                    </Link>
                  </td>
                </tr>
              ))}
              {data.rows.length === 0 && (
                <tr>
                  <td colSpan={9} className="empty">
                    {t("مفيش سجلات في المدى ده.", "Nothing recorded in this range.")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {data.truncated && (
          <div className="note note--info" data-note="truncated">
            <Icon name="info" />
            <div>{t("فيه سجلات أكتر من اللي ظاهر. ضيّق المدى أو الفلاتر.", "There are more records than shown. Narrow the range or the filters.")}</div>
          </div>
        )}
      </div>
    </>
  );
}
