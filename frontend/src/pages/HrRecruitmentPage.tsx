import { Link, Navigate } from "react-router";
import { useHrRecruitment } from "../api/queries";
import type { HrCandidateRow } from "../api/types";
import { Waiting } from "../components/accounts/shared";
import { useHrAllowed, useStamp } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { LeaveStatusBadge, useLeaveWords } from "../components/leave/shared";
import { usePreferences } from "../i18n/Preferences";

/** One line of an applicant list: the code opens the file, the name is what the bot or HR wrote down. */
export function CandidateRows({ rows, empty, phones = false }: { rows: HrCandidateRow[]; empty: string; phones?: boolean }) {
  const { t } = usePreferences();
  const words = useLeaveWords();
  return (
    <div className="table-wrap">
      <table className="table" data-table="candidates">
        <thead>
          <tr>
            <th>{t("الكود", "Code")}</th>
            <th>{t("المرشح", "Candidate")}</th>
            {phones && <th>{t("الموبايل", "Phone")}</th>}
            <th>{t("الوظيفة", "Vacancy")}</th>
            <th>{t("المصدر", "Source")}</th>
            <th>{t("الحالة", "Status")}</th>
            <th>{t("التاريخ", "Applied")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.code} data-candidate={row.code}>
              <td className="mono">
                <Link to={`/hr/candidates/${row.code}`}>{row.code}</Link>
              </td>
              <td>{row.name}</td>
              {phones && (
                <td className="mono muted" dir="ltr">
                  {row.phone || "—"}
                </td>
              )}
              <td className="muted">{row.vacancy ?? "—"}</td>
              <td className="muted">{words(row.source)}</td>
              <td>
                <LeaveStatusBadge status={row.status} />
              </td>
              <td className="mono muted">{row.applied_on}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={phones ? 7 : 6} className="empty">
                {empty}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/** The pipeline at a glance. If nothing is set to be scrubbed from what a candidate reads, the page says so: silence would read as safety. */
export function HrRecruitmentPage() {
  const { t } = usePreferences();
  const words = useLeaveWords();
  const stamp = useStamp();
  const { me, allowed } = useHrAllowed();
  const query = useHrRecruitment(allowed);
  const data = query.data;

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!data) return <Waiting failed={query.isError} />;
  const { counts } = data;
  const kpi = (ar: string, en: string, value: number, tone = "") => (
    <div className={`kpi${tone ? ` kpi--${tone}` : ""}`} key={en}>
      <div className="kpi__label">{t(ar, en)}</div>
      <div className="kpi__value mono">{value}</div>
    </div>
  );

  return (
    <>
      <div className="page-head">
        <h1>{t("لوحة التوظيف", "Recruitment board")}</h1>
        <div className="grow" />
        <Link className="btn btn--primary btn--sm" to="/hr/vacancies">
          <Icon name="plus" size="sm" />
          <span>{t("وظيفة جديدة", "New vacancy")}</span>
        </Link>
      </div>

      {!data.privacy_armed && (
        <div className="note note--high" data-note="privacy">
          <Icon name="alert" />
          <div>
            <b>{t("قاعدة إخفاء الهوية مش مفعّلة", "The identity rule is not armed")}</b>
            <div>
              {t("مفيش كلمات متسجلة للإخفاء — اكتبهم في ", "Nothing is configured to redact, so the company name can reach a candidate. Add the terms in the ")}
              <Link to="/hr/recruitment/settings">{t("إعدادات التوظيف", "recruitment settings")}</Link>.
            </div>
          </div>
        </div>
      )}

      {(!data.bot_enabled || !data.recruit_number) && (
        <div className="note note--warn" data-note="bot">
          <Icon name="info" />
          <div>
            {!data.recruit_number
              ? t("رقم التوظيف لسه مش متسجل — البوت مش هيستقبل حاجة.", "No recruitment number is configured yet, so the bot receives nothing.")
              : t("البوت مقفول من الإعدادات.", "The bot is switched off.")}
          </div>
        </div>
      )}

      <div className="grid grid--4">
        {kpi("وظايف مفتوحة", "Open vacancies", counts.open_vacancies)}
        {kpi("إجمالي المتقدمين", "Total applicants", counts.total_applicants)}
        {kpi("في الفرز", "Screening", counts.screening, counts.screening ? "warn" : "")}
        {kpi("مستني المالك", "Owner approval", counts.pending_owner, counts.pending_owner ? "danger" : "")}
      </div>
      <div className="grid grid--4">
        {kpi("مقابلات النهارده", "Interviews today", counts.interviews_today)}
        {kpi("اختبارات معلقة", "Pending tests", counts.pending_tests)}
        {kpi("اتعيّنوا", "Hired", counts.hired, "ok")}
        {kpi("تحت الاختبار", "On probation", counts.on_probation)}
      </div>

      <div className="grid grid--main">
        <div className="card">
          <div className="card__head">
            <Icon name="contact" />
            <h3>{t("آخر المتقدمين", "Latest applicants")}</h3>
            <div className="grow" />
            <Link className="btn btn--sm btn--ghost" to="/hr/candidates">
              {t("الكل", "All")}
            </Link>
          </div>
          <CandidateRows rows={data.recent} empty={t("مفيش متقدمين لسه.", "No applicants yet.")} />
        </div>

        <div className="sticky-side">
          <div className="card" data-card="today">
            <div className="card__head">
              <Icon name="calendar" />
              <h3>{t("مقابلات النهارده", "Today")}</h3>
            </div>
            {data.today_interviews.map((one, index) => (
              <div className="kv" key={index}>
                <span>
                  <Link to={`/hr/candidates/${one.candidate.code}`}>{one.candidate.name}</Link> <span className="muted">{words(one.kind)}</span>
                </span>
                <b className="mono">{stamp(one.at)}</b>
              </div>
            ))}
            {data.today_interviews.length === 0 && <div className="muted">{t("مفيش مقابلات النهارده.", "Nothing today.")}</div>}
          </div>

          <div className="card" data-card="owner">
            <div className="card__head">
              <Icon name="user-check" />
              <h3>{t("مستني موافقة المالك", "Waiting for the owner")}</h3>
            </div>
            {data.waiting_owner.map((one) => (
              <div className="kv" key={one.code}>
                <Link to={`/hr/candidates/${one.code}`}>{one.name}</Link>
                <span className="muted">{one.vacancy ?? "—"}</span>
              </div>
            ))}
            {data.waiting_owner.length === 0 && <div className="muted">{t("مفيش حاجة مستنية.", "Nothing waiting.")}</div>}
            {data.can.approve && data.waiting_owner.length > 0 && (
              <Link className="btn btn--primary btn--block mt" to="/hr/approvals">
                <Icon name="check" size="sm" />
                <span>{t("افتح الطابور", "Open the queue")}</span>
              </Link>
            )}
          </div>

          <div className="note note--info">
            <Icon name="shield" />
            <div>
              {t(
                "البوت بيجمع ويستلم الورق ويحوّل للـHR — مابياخدش قرار توظيف.",
                "The bot collects and hands over. It does not screen, score or hire: that is HR's evaluation and then the owner's decision.",
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
