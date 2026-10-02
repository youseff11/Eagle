import { Navigate, useSearchParams } from "react-router";
import { useMe, usePayroll } from "../api/queries";
import type { PayrollResponse } from "../api/types";
import { Icon } from "../components/Icon";
import { usePreferences } from "../i18n/Preferences";
import { safeInternalPath } from "../lib/safeUrl";

/** The badge looks `static/css/app.css` has for a day; the server names the tone, anything else is drawn plain. */
const DAY_TONES = new Set(["ok", "info", "wait", "dead"]);

const pad = (month: number) => String(month).padStart(2, "0");

function Kpi({ label, value, tone }: { label: string; value: string; tone?: "ok" | "danger" }) {
  return (
    <div className={`kpi${tone ? ` kpi--${tone}` : ""}`}>
      <div className="kpi__label">{label}</div>
      <div className="kpi__value mono">{value}</div>
    </div>
  );
}

function Month({ data }: { data: PayrollResponse }) {
  const { t, lang } = usePreferences();
  const { line } = data;
  // The classic page's own test is the number's truth: "0.00" is no bonus waiting.
  const waiting = line !== null && Number(line.pending_bonus) > 0;
  const full = line ? safeInternalPath(line.url) : null;

  return (
    <>
      {line ? (
        <>
          <div className="grid grid--4">
            <Kpi label={t("الراتب الأساسي", "Base salary")} value={line.base_salary} />
            <Kpi label={t("بونص الإنتاج", "Production bonus")} value={line.production_bonus} tone="ok" />
            <Kpi label={t("خصومات", "Deductions")} value={line.deductions} tone={Number(line.deductions) > 0 ? "danger" : undefined} />
            <Kpi label={t("الصافي", "Net")} value={line.net} />
          </div>
          <div className="row row--tight">
            {full && (
              <a className="btn btn--primary" href={full}>
                <Icon name="file" size="sm" />
                <span>{t("التفاصيل كاملة", "Full breakdown")}</span>
              </a>
            )}
            {waiting && (
              <span className="badge badge--wait">
                <span>{t("مكافآت مستنية اعتماد", "Bonuses awaiting approval")}</span>
                <span className="mono">{line.pending_bonus}</span>
              </span>
            )}
          </div>
        </>
      ) : (
        <div className="note note--info">
          <Icon name="info" />
          <div>{t("الشهر ده لسه ماتحسبش. هيظهر هنا أول ما الحسابات تشغّله.", "This month has not been run yet. It appears here once accounts computes it.")}</div>
        </div>
      )}

      <div className="grid grid--main">
        <div className="card">
          <div className="card__head">
            <Icon name="calendar" />
            <h3>{t("أيامي في الشهر", "My days")}</h3>
            <div className="grow" />
            <span className="muted mono">
              {data.daily_target_words} {t("كلمة في اليوم", "words a day")}
            </span>
          </div>
          <div className="table-wrap table-wrap--cards">
            <table className="table table--cards">
              <thead>
                <tr>
                  <th>{t("اليوم", "Date")}</th>
                  <th>{t("الحالة", "Status")}</th>
                  <th>{t("الكلمات", "Words")}</th>
                </tr>
              </thead>
              <tbody>
                {data.days.map((day) => (
                  <tr key={day.date}>
                    <td data-ar-label="اليوم" data-en-label="Date" className="mono">
                      {day.date}
                    </td>
                    <td data-ar-label="الحالة" data-en-label="Status">
                      <span className={`badge${DAY_TONES.has(day.status.tone) ? ` badge--${day.status.tone}` : ""}`}>
                        {lang === "ar" ? day.status.ar : day.status.en}
                      </span>
                    </td>
                    <td data-ar-label="الكلمات" data-en-label="Words" className="mono">
                      {day.words}
                    </td>
                  </tr>
                ))}
                {data.days.length === 0 && (
                  <tr>
                    <td colSpan={3} className="empty">
                      {t("مفيش أيام مسجلة.", "No days recorded.")}
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
              <Icon name="alert" />
              <h3>{t("المخالفات", "Violations")}</h3>
            </div>
            {data.violations.map((row, index) => (
              <div className="note" key={`${row.date}-${row.kind.value}-${index}`}>
                <Icon name="info" />
                <div>
                  <div className="note__where mono">
                    {row.date} · {lang === "ar" ? row.kind.ar : row.kind.en}
                  </div>
                  <div>{row.reason}</div>
                  {row.status === "approved" ? (
                    <span className="badge badge--dead">{t("مطبق", "Applied")}</span>
                  ) : row.status === "pending" ? (
                    <span className="badge badge--wait">{t("مستنية اعتماد", "Awaiting approval")}</span>
                  ) : (
                    <span className="badge badge--info">{t("مرفوضة", "Rejected")}</span>
                  )}
                </div>
              </div>
            ))}
            {data.violations.length === 0 && <div className="empty">{t("مفيش مخالفات.", "No violations.")}</div>}
          </div>
        </div>
      </div>
    </>
  );
}

/** The translator's own payslip: one month, read only. The month is in the address (`?period=2026-09`), so it can be linked to. */
export function PayrollPage() {
  const { t } = usePreferences();
  const me = useMe();
  const [params, setParams] = useSearchParams();
  // Anything that is not a month is this month; the server refuses what is not a real one, and says so.
  const asked = params.get("period") ?? "";
  const period = /^\d{4}-\d{1,2}$/.test(asked) ? asked : "";
  // The same people the server lets in (`api_role_required`: translators, and the admin).
  const allowed = me.data !== undefined && (me.data.user.role === "translator" || me.data.user.is_admin);
  const query = usePayroll(period, allowed);

  if (me.data && !allowed) return <Navigate to="/" replace />;

  const data = query.data;
  const here = data ? `${data.year}-${data.month}` : "";
  const options = data ? data.periods.map((p) => `${p.year}-${p.month}`) : [];
  // A month asked for by hand may be older than the picker goes: it stays selectable.
  if (data && !options.includes(here)) options.push(here);

  return (
    <>
      <div className="page-head">
        <h1>{t("مستحقاتي", "My payroll")}</h1>
        {data && (
          <div className="page-head__sub mono">
            {data.year}-{pad(data.month)}
          </div>
        )}
        <div className="grow" />
        {data && (
          <select
            className="input"
            aria-label={t("الشهر", "Month")}
            value={here}
            onChange={(event) => setParams(event.target.value ? { period: event.target.value } : {})}
          >
            {options.map((value) => {
              const [year, month] = value.split("-");
              return (
                <option key={value} value={value}>
                  {year}-{pad(Number(month))}
                </option>
              );
            })}
          </select>
        )}
      </div>

      {data ? (
        <Month data={data} />
      ) : (
        <div className="card">
          {query.isError ? (
            <div className="empty" role="alert">
              <Icon name="alert" size="xl" />
              <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
            </div>
          ) : (
            <div className="empty">
              <Icon name="refresh" size="xl" />
              <span>{t("بيحمّل...", "Loading...")}</span>
            </div>
          )}
        </div>
      )}
    </>
  );
}
