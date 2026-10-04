import { Link, Navigate, useSearchParams } from "react-router";
import { useHrPerformance } from "../api/queries";
import type { HrPart } from "../api/types";
import { MonthPicker } from "../components/accounts/MonthPicker";
import { Waiting } from "../components/accounts/shared";
import { useHrAllowed } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { LeaveStatusBadge } from "../components/leave/shared";
import { usePreferences } from "../i18n/Preferences";

type Part = HrPart;

/** A score as a bar. No score draws an empty track: a missing indicator must look missing, not like zero. */
function Meter({ score, band }: { score: number | null; band: string }) {
  if (score === null) {
    return (
      <div className="meter meter--empty" role="img" aria-label="not measured">
        <i style={{ width: 0 }} />
      </div>
    );
  }
  const width = Math.max(0, Math.min(100, Math.trunc(score)));
  return (
    <div className={`meter meter--${band}`} role="img" aria-label={`${width}%`}>
      <i style={{ width: `${width}%` }} />
    </div>
  );
}

/** One translator's month: four indicators, each with its band, the weights from the payroll rules, and the overall. */
export function HrPerformancePage() {
  const { t, lang } = usePreferences();
  const { me, allowed } = useHrAllowed();
  const [params, setParams] = useSearchParams();
  const period = params.get("period") ?? "";
  const user = params.get("user") ?? "";
  const query = useHrPerformance(period, user, allowed);
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
        <div className="grow" />
        <select className="input" aria-label={t("الموظف", "Employee")} value={data.person?.id ?? ""} onChange={(event) => go({ user: event.target.value })}>
          {data.people.map((one) => (
            <option key={one.id} value={one.id}>
              {one.name}
            </option>
          ))}
        </select>
        <MonthPicker periods={data.periods} year={data.year} month={data.month} onChange={(next) => go({ period: next })} />
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
