import { Link, useSearchParams } from "react-router";
import { useHrPerformance } from "../api/queries";
import type { HrPart } from "../api/types";
import { MonthPicker } from "../components/accounts/MonthPicker";
import { Waiting } from "../components/accounts/shared";
import { Meter } from "../components/hr/Meter";
import { PerformanceBoard, personHref } from "../components/hr/PerformanceBoard";
import { useHrAllowed } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { LeaveStatusBadge } from "../components/leave/shared";
import { usePreferences } from "../i18n/Preferences";
import { periodLabel, periodText } from "../lib/payroll";

type Part = HrPart;

/**
 * The performance page. Without a person in the address it is the board (who delivered the most this month, the best three on
 * a podium and everybody below), which every employee reads. With `?user=` it is that translator's month and record, which is
 * HR's and the admin's: anybody else who types such an address is shown the board.
 */
export function HrPerformancePage() {
  const { me, allowed } = useHrAllowed();
  const [params, setParams] = useSearchParams();
  const period = params.get("period") ?? "";
  const user = params.get("user") ?? "";

  // Until the server has said who this is nobody is known to be HR: the board and a person's page must not trade places.
  if (!me.data) return <Waiting failed={me.isError} />;
  if (user && allowed) return <PersonPerformance period={period} user={user} allowed={allowed} setParams={setParams} />;
  return <PerformanceBoard period={period} linkPeople={allowed} onPeriod={(next) => setParams(next ? { period: next } : {})} />;
}

/** One translator's month: four indicators, each with its band, the weights from the payroll rules, the overall - and their last months. */
function PersonPerformance({
  period,
  user,
  allowed,
  setParams,
}: {
  period: string;
  user: string;
  allowed: boolean;
  setParams: (params: URLSearchParams) => void;
}) {
  const { t, lang } = usePreferences();
  const query = useHrPerformance(period, user, allowed);
  const data = query.data;

  if (!data) return <Waiting failed={query.isError} />;

  const go = (next: { period?: string; user?: string }) => {
    const merged = new URLSearchParams();
    const nextPeriod = next.period ?? period;
    const nextUser = next.user ?? user;
    if (nextPeriod) merged.set("period", nextPeriod);
    if (nextUser) merged.set("user", nextUser);
    setParams(merged);
  };
  const report = data.report;
  const why = (part: Part) => (part.reason ? (lang === "ar" ? part.reason.ar : part.reason.en) : "");
  const percent = (value: number | null | undefined) => (value === null || value === undefined ? "—" : `${value}%`);
  const indicator = (key: "productivity" | "quality" | "deadline" | "attendance", ar: string, en: string, detail: (part: Part) => string) => {
    const part = report!.parts[key];
    return (
      <div className="field" key={key} data-part={key}>
        <div className="row row--between">
          <label>
            {t(ar, en)} <span className="muted mono">{report!.weights[key]}%</span>
          </label>
          <LeaveStatusBadge status={part.band} />
        </div>
        <div className="score-row">
          <Meter score={part.score} band={part.band.value} />
          <span className="score-row__value mono">{percent(part.score)}</span>
        </div>
        <small className="muted">{part.score !== null ? detail(part) : why(part)}</small>
      </div>
    );
  };

  return (
    <>
      <div className="page-head">
        <h1>{t("الأداء", "Performance")}</h1>
        <Link className="btn btn--sm" to={period ? `/hr/performance?period=${encodeURIComponent(period)}` : "/hr/performance"}>
          <Icon name="chart" size="sm" />
          <span>{t("الترتيب", "Ranking")}</span>
        </Link>
        <div className="grow" />
        <select className="input input--inline" aria-label={t("الموظف", "Employee")} value={data.person?.id ?? ""} onChange={(event) => go({ user: event.target.value })}>
          {data.people.map((one) => (
            <option key={one.id} value={one.id}>
              {one.name}
            </option>
          ))}
        </select>
        <MonthPicker periods={data.periods} year={data.year} month={data.month} onChange={(next) => go({ period: next })} className="input input--inline" />
      </div>

      {report && data.person ? (
        <div className="grid grid--main">
          <div className="stack">
            <div className="card">
              <div className="card__head">
                <Icon name="target" />
                <h3>{t("المؤشرات", "Indicators")}</h3>
                <div className="grow" />
                <span className="muted">{t("الأوزان من قواعد الحساب", "Weights come from the payroll rules")}</span>
              </div>
              {indicator("productivity", "الإنتاجية", "Productivity", (part) => `${part.words} / ${part.target} ${t("كلمة", "words")}`)}
              {indicator(
                "quality",
                "الجودة",
                "Quality",
                (part) =>
                  `${t("متوسط المراجع", "Reviewer average")} ${part.reviewer_avg ?? "—"} · ${part.reviewed} ${t("متقيّم", "marked")} · ${part.complaints} ${t("شكوى", "complaints")}`,
              )}
              {indicator("deadline", "المواعيد", "Deadlines", (part) => `${part.late} ${t("متأخر من", "late of")} ${part.total}`)}
              {indicator("attendance", "الحضور", "Attendance", (part) => `${part.present} / ${part.scheduled} ${t("يوم", "days")} · ${part.late_days} ${t("تأخير", "late")}`)}
            </div>
            <div className="note note--info">
              <Icon name="info" />
              <div>
                {t(
                  "المؤشر اللي مالوش بيانات بيقول «مابتتقاسش» ومابيدخلش في الإجمالي — بدل ما يتحسب صفر.",
                  "An indicator with no data reads 'not measured' and stays out of the overall, instead of counting as zero and dragging it down.",
                )}
              </div>
            </div>

            {data.history.length > 0 && (
              <div className="card" data-card="history">
                <div className="card__head">
                  <Icon name="history" />
                  <h3>{t("سجل الإنتاجية", "Productivity record")}</h3>
                  <div className="grow" />
                  <span className="muted">{t("آخر 6 شهور", "Last 6 months")}</span>
                </div>
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>{t("الشهر", "Month")}</th>
                        <th>{t("الإنتاجية", "Productivity")}</th>
                        <th>{t("الكلمات", "Words")}</th>
                        <th>{t("المشاريع", "Projects")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.history.map((row) => {
                        const text = periodText(row.year, row.month);
                        const current = row.year === data.year && row.month === data.month;
                        return (
                          <tr key={text} data-month={text} className={current ? "is-current" : undefined}>
                            <td className="mono">
                              {current ? periodLabel(row.year, row.month) : <Link to={personHref(data.person!.id, text)}>{periodLabel(row.year, row.month)}</Link>}
                            </td>
                            <td>
                              <div className="score-row">
                                <Meter score={row.score} band={row.band.value} />
                                <span className="score-row__value mono">{percent(row.score)}</span>
                              </div>
                            </td>
                            <td className="mono">
                              {row.words.toLocaleString("en-US")}
                              {row.target > 0 && <span className="muted"> / {row.target.toLocaleString("en-US")}</span>}
                            </td>
                            <td className="mono">{row.projects}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>

          <div className="sticky-side">
            <div className="card" data-card="overall">
              <div className="card__head">
                <Icon name="chart" />
                <h3>{t("الإجمالي", "Overall")}</h3>
              </div>
              <div className="kpi">
                <div className="kpi__label">{t("الأداء العام", "Overall performance")}</div>
                <div className="kpi__value mono">{percent(report.overall)}</div>
              </div>
              <div className="row row--tight mt">
                <LeaveStatusBadge status={report.band} />
              </div>
            </div>

            <div className="card card--flat">
              <div className="card__head">
                <Icon name="layers" />
                <h3>{t("الشهر في أرقام", "The month")}</h3>
              </div>
              <div className="kv">
                <span>{t("عدد المشاريع", "Projects")}</span>
                <b className="mono">{report.projects}</b>
              </div>
              <div className="kv">
                <span>{t("رجعت للتعديل", "Sent back")}</span>
                <b className="mono">{report.returned_projects}</b>
              </div>
              <div className="kv">
                <span>{t("نسبة المراجعة المعادة", "Revision rate")}</span>
                <b className="mono">{percent(report.revision_rate)}</b>
              </div>
              <div className="kv">
                <span>{t("شكاوى العملاء", "Client complaints")}</span>
                <b className="mono">{report.parts.quality.complaints ?? 0}</b>
              </div>
              <div className="kv">
                <span>{t("مخالفات جودة معتمدة", "Quality violations")}</span>
                <b className="mono">{report.parts.quality.violations ?? 0}</b>
              </div>
            </div>

            <Link className="btn btn--sm btn--ghost btn--block" to={`/hr/employees/${data.person.id}`}>
              <Icon name="user" size="sm" />
              <span>{t("ملف الموظف", "Employee file")}</span>
            </Link>
          </div>
        </div>
      ) : (
        <div className="card empty">{t("اختار موظف.", "Pick somebody.")}</div>
      )}
    </>
  );
}
