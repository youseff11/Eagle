import { Navigate, useSearchParams } from "react-router";
import { useHrReport } from "../api/queries";
import { Waiting } from "../components/accounts/shared";
import { MonthPicker } from "../components/accounts/MonthPicker";
import { StatusBadge, useHrAllowed, useStamp } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { usePreferences } from "../i18n/Preferences";
import { minutesHm } from "../lib/payroll";

/** Section 12 for one person and one month: the numbers, then the days. The month and the person live in the address. */
export function HrReportPage() {
  const { t, lang } = usePreferences();
  const stamp = useStamp();
  const { me, allowed } = useHrAllowed();
  const [params, setParams] = useSearchParams();
  const period = params.get("period") ?? "";
  const user = params.get("user") ?? "";
  const query = useHrReport(period, user, allowed);
  const data = query.data;

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!data) return <Waiting failed={query.isError} />;

  const go = (next: { period?: string; user?: string }) => {
    const merged = new URLSearchParams();
    const nextPeriod = next.period ?? period;
    const nextUser = next.user ?? user;
    if (nextPeriod) merged.set("period", nextPeriod);
    if (nextUser) merged.set("user", nextUser);
    setParams(merged);
  };
  const summary = data.summary;
  const mode = (value: { ar: string; en: string } | null) => (value ? (lang === "ar" ? value.ar : value.en) : "—");
  const row = (ar: string, en: string, value: string | number) => (
    <div className="kv" key={en}>
      <span>{t(ar, en)}</span>
      <b className="mono">{value}</b>
    </div>
  );

  return (
    <>
      <div className="page-head">
        <h1>{t("التقرير الشهري", "Monthly attendance report")}</h1>
        <div className="grow" />
        <select
          className="input"
          aria-label={t("الموظف", "Employee")}
          value={data.person?.id ?? ""}
          onChange={(event) => go({ user: event.target.value })}
        >
          {data.people.map((one) => (
            <option key={one.id} value={one.id}>
              {one.name}
            </option>
          ))}
        </select>
        <MonthPicker periods={data.periods} year={data.year} month={data.month} onChange={(next) => go({ period: next })} />
      </div>

      {summary ? (
        <>
          <div className="grid grid--4">
            <div className="kpi">
              <div className="kpi__label">{t("أيام مجدولة", "Scheduled")}</div>
              <div className="kpi__value mono">{summary.scheduled_days}</div>
            </div>
            <div className="kpi kpi--ok">
              <div className="kpi__label">{t("أيام حضور", "Present")}</div>
              <div className="kpi__value mono">{summary.present_days}</div>
            </div>
            <div className="kpi">
              <div className="kpi__label">{t("إجمالي الساعات", "Total hours")}</div>
              <div className="kpi__value mono">{minutesHm(summary.work_minutes)}</div>
            </div>
            <div className={`kpi${summary.overtime_minutes ? " kpi--ok" : ""}`}>
              <div className="kpi__label">{t("أوفرتايم", "Overtime")}</div>
              <div className="kpi__value mono">{minutesHm(summary.overtime_minutes)}</div>
            </div>
          </div>

          <div className="grid grid--main">
            <div className="card">
              <div className="card__head">
                <Icon name="calendar" />
                <h3>{t("يوم بيوم", "Day by day")}</h3>
              </div>
              <div className="table-wrap">
                <table className="table" data-table="days">
                  <thead>
                    <tr>
                      <th>{t("اليوم", "Date")}</th>
                      <th>{t("الحالة", "Status")}</th>
                      <th>{t("النظام", "Mode")}</th>
                      <th>{t("حضور", "In")}</th>
                      <th>{t("انصراف", "Out")}</th>
                      <th>{t("بريك", "Break")}</th>
                      <th>{t("ساعات", "Hours")}</th>
                      <th>{t("تأخير", "Late")}</th>
                      <th>{t("نقص", "Short")}</th>
                      <th>OT</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.days.map((day) => (
                      <tr key={day.date} data-day={day.date}>
                        <td className="mono">{day.date}</td>
                        <td>
                          <StatusBadge status={day.status} />
                        </td>
                        <td>{day.work_mode ? <span className="chip">{mode(day.work_mode)}</span> : "—"}</td>
                        <td className="mono">{stamp(day.check_in)}</td>
                        <td className="mono">{stamp(day.check_out)}</td>
                        <td className="mono">
                          {day.break_minutes}
                          {t("د", "m")}
                        </td>
                        <td className="mono">{minutesHm(day.work_minutes)}</td>
                        <td className={`mono${day.late_minutes ? " deadline--late" : ""}`}>{day.late_minutes}</td>
                        <td className="mono">{day.short_minutes}</td>
                        <td className="mono">{day.overtime_minutes}</td>
                      </tr>
                    ))}
                    {summary.days.length === 0 && (
                      <tr>
                        <td colSpan={10} className="empty">
                          {t("مفيش أيام في الشهر ده.", "Nothing recorded this month.")}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="sticky-side">
              <div className="card">
                <div className="card__head">
                  <Icon name="list-checks" />
                  <h3>{t("الملخص", "Summary")}</h3>
                </div>
                {row("أيام العمل المجدولة", "Scheduled days", summary.scheduled_days)}
                {row("أيام الحضور", "Days present", summary.present_days)}
                {row("أيام Office", "Office days", summary.office_days)}
                {row("أيام Remote", "Remote days", summary.remote_days)}
                {row("الإجازات", "Leave", summary.leave_days)}
                {row("غياب بعذر", "Excused", summary.excused_days)}
                {row("الغياب", "Absent", summary.absent_days)}
                {row("مرات التأخير", "Times late", summary.late_days)}
                {row("إجمالي دقائق التأخير", "Total late minutes", summary.late_minutes)}
                {row("الخروج المبكر", "Early leave", `${summary.early_leave_minutes}${t("د", "m")}`)}
                {row("نقص الساعات", "Short hours", minutesHm(summary.short_minutes))}
                {row("إجمالي ساعات العمل", "Total worked", minutesHm(summary.work_minutes))}
                {row("إجمالي الأوفرتايم", "Total overtime", minutesHm(summary.overtime_minutes))}
              </div>
              {summary.needs_review > 0 && (
                <div className="note note--warn" data-note="review">
                  <Icon name="alert" />
                  <div>
                    {t("فيه أيام لسه محتاجة مراجعة:", "Some days still need review:")} <b className="mono">{summary.needs_review}</b>
                  </div>
                </div>
              )}
            </div>
          </div>
        </>
      ) : (
        <div className="card empty">{t("اختار موظف.", "Pick somebody.")}</div>
      )}
    </>
  );
}
