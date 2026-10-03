import { useState, type ReactNode } from "react";
import { Link, useParams } from "react-router";
import { useReleaseBonuses } from "../api/accountsActions";
import { ApiError } from "../api/client";
import { useAccountsLine } from "../api/queries";
import { Waiting, refusal } from "../components/accounts/shared";
import { Confirm } from "../components/Confirm";
import { Icon } from "../components/Icon";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";
import { hasMoney, minutesHm } from "../lib/payroll";

const DAY_TONES = new Set(["ok", "info", "wait", "dead"]);

function Kv({ label, children, strong }: { label: string; children: ReactNode; strong?: boolean }) {
  return (
    <div className="kv">
      {strong ? <strong>{label}</strong> : <span>{label}</span>}
      {strong ? <strong className="mono">{children}</strong> : <span className="mono">{children}</span>}
    </div>
  );
}

/**
 * One month's payslip, in full, the way it was frozen when the month was run: the admin's to read, and a translator's own.
 * Anybody else is told it is not there. The admin can release the two monthly bonuses from here - the system proposes, the
 * manager releases.
 */
export function AccountsLinePage() {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const params = useParams();
  const id = Number(params.id);
  const query = useAccountsLine(id);
  const release = useReleaseBonuses(id);
  const [asking, setAsking] = useState(false);
  const [problem, setProblem] = useState("");

  if (!Number.isInteger(id) || id <= 0 || (query.error instanceof ApiError && query.error.status === 404)) {
    return (
      <div className="card empty" role="alert">
        <span>{t("الصفحة دي مش موجودة.", "That page does not exist.")}</span>
      </div>
    );
  }
  const data = query.data;
  if (!data) return <Waiting failed={query.isError} />;
  const { line, conf } = data;
  const name = (value: { ar: string; en: string }) => (lang === "ar" ? value.ar : value.en);
  const earned = (money: string, isEarned: boolean, cfg: string) =>
    hasMoney(money) ? (
      `+ ${money}`
    ) : isEarned ? (
      <span className="badge badge--wait">
        {cfg} {t("مستنية", "pending")}
      </span>
    ) : (
      <span className="muted">{t("مستحقتش", "not earned")}</span>
    );

  return (
    <>
      <div className="page-head">
        <h1>{line.user.name}</h1>
        <div className="page-head__sub mono">{line.label}</div>
        <div className="grow" />
        {data.can.salary && (
          <Link className="btn btn--sm" to={`/accounts/salary/${line.user.id}`}>
            {t("سجل الراتب", "Salary history")}
          </Link>
        )}
        {data.can.release && (
          <button className="btn btn--primary" type="button" onClick={() => setAsking(true)}>
            <Icon name="check" size="sm" />
            <span>{t("اصرف المكافآت", "Release the bonuses")}</span>
          </button>
        )}
      </div>

      <div className="grid grid--4">
        <div className="kpi">
          <div className="kpi__label">{t("الراتب الأساسي", "Base salary")}</div>
          <div className="kpi__value mono">{line.base_salary}</div>
        </div>
        <div className="kpi kpi--ok">
          <div className="kpi__label">{t("بونص الإنتاج اليومي", "Daily production bonus")}</div>
          <div className="kpi__value mono">{line.production_bonus}</div>
        </div>
        <div className={`kpi${hasMoney(line.deductions) ? " kpi--danger" : ""}`}>
          <div className="kpi__label">{t("خصومات معتمدة", "Approved deductions")}</div>
          <div className="kpi__value mono">{line.deductions}</div>
        </div>
        <div className="kpi">
          <div className="kpi__label">{t("الصافي", "Net")}</div>
          <div className="kpi__value mono">{line.net}</div>
        </div>
      </div>

      <div className="grid grid--main">
        <div>
          <div className="card">
            <div className="card__head">
              <Icon name="calendar" />
              <h3>{t("اليوم باليوم", "Day by day")}</h3>
              <div className="grow" />
              <span className="muted mono">
                {line.total_words} / {line.target_words}
              </span>
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("اليوم", "Date")}</th>
                    <th>{t("الحالة", "Status")}</th>
                    <th>{t("الكلمات", "Words")}</th>
                    <th>{t("الحد اليومي", "Floor")}</th>
                    <th>{t("بونص اليوم", "Day bonus")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.days.map((day) => (
                    <tr key={day.date} data-day={day.date}>
                      <td className="mono">{day.date}</td>
                      <td>
                        <span className={`badge${DAY_TONES.has(day.status.tone) ? ` badge--${day.status.tone}` : ""}`}>{name(day.status)}</span>
                        {day.secondary && <span className="chip">{t("لغة تانية", "Secondary")}</span>}
                        {day.difficult && <span className="chip">{t("ملف صعب", "Difficult")}</span>}
                      </td>
                      <td className="mono">{day.words}</td>
                      <td className="mono muted">{day.target}</td>
                      <td className="mono">{day.bonus}</td>
                    </tr>
                  ))}
                  {data.days.length === 0 && (
                    <tr>
                      <td colSpan={5} className="empty">
                        {t("مفيش أيام مسجلة.", "No days recorded.")}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card">
            <div className="card__head">
              <Icon name="alert" />
              <h3>{t("الخصومات", "Deductions")}</h3>
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("اليوم", "Date")}</th>
                    <th>{t("النوع", "Kind")}</th>
                    <th>{t("السبب", "Reason")}</th>
                    <th>{t("أيام", "Days")}</th>
                    <th>{t("القيمة", "Amount")}</th>
                    <th>{t("الحالة", "State")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.deductions.map((row, index) => (
                    <tr key={index} data-deduction={row.status}>
                      <td className="mono">{row.date}</td>
                      <td>{name(row.kind)}</td>
                      <td className="muted">{row.reason}</td>
                      <td className="mono">{row.days}</td>
                      <td className={`mono${row.status === "pending" ? " muted" : ""}`}>{row.amount}</td>
                      <td>
                        {row.status === "applied" ? (
                          <span className="badge badge--dead">{t("مطبق", "Applied")}</span>
                        ) : (
                          <span className="badge badge--wait">{t("مستنية اعتماد", "Awaiting approval")}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {data.deductions.length === 0 && (
                    <tr>
                      <td colSpan={6} className="empty">
                        {t("مفيش خصومات.", "No deductions.")}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="sticky-side">
          <div className="card">
            <div className="card__head">
              <Icon name="list-checks" />
              <h3>{t("ملخص الحساب", "How the net was reached")}</h3>
            </div>
            <Kv label={t("الراتب الأساسي", "Base salary")}>{line.base_salary}</Kv>
            <Kv label={t("قيمة اليوم", "Value of a day")}>
              {line.day_value} <span className="muted">= {line.base_salary} / {line.working_days}</span>
            </Kv>
            <Kv label={t("بونص الإنتاج", "Production bonus")}>+ {line.production_bonus}</Kv>
            <Kv label={t("الأوفرتايم", "Overtime")}>
              {hasMoney(line.overtime_bonus) ? (
                <>
                  + {line.overtime_bonus} <span className="muted">({minutesHm(line.overtime_minutes)})</span>
                </>
              ) : line.overtime_minutes > 0 ? (
                <span className="badge badge--wait">
                  {minutesHm(line.overtime_minutes)} {t("مستني اعتماد", "pending")}
                </span>
              ) : (
                <span className="muted">—</span>
              )}
            </Kv>
            <Kv label={t("مكافأة الانضباط", "Discipline bonus")}>{earned(line.discipline_bonus, line.discipline_bonus_earned, conf.discipline_bonus)}</Kv>
            <Kv label={t("مكافأة التارجت", "Target bonus")}>{earned(line.target_bonus, line.target_bonus_earned, conf.target_bonus)}</Kv>
            <Kv label={t("الخصومات", "Deductions")}>- {line.deductions}</Kv>
            <Kv label={t("الصافي", "Net")} strong>
              {line.net}
            </Kv>
          </div>

          <div className="card">
            <div className="card__head">
              <Icon name="target" />
              <h3>{t("الشهر في أرقام", "The month in numbers")}</h3>
            </div>
            <Kv label={t("أيام الشغل", "Worked days")}>
              {line.worked_days} / {line.working_days}
            </Kv>
            <Kv label={t("إجازات", "Leave")}>
              {line.leave_days} <span className="muted">/ {conf.monthly_leave_allowance}</span>
            </Kv>
            <Kv label={t("غياب بدون إذن", "Unexcused")}>{line.unexcused_days}</Kv>
            <Kv label={t("أيام تحت الحد", "Days under the floor")}>{line.under_target_days}</Kv>
            <Kv label={t("إجمالي الكلمات", "Total words")}>
              <span className={line.below_alert ? "deadline--late" : undefined}>
                {line.total_words} / {line.target_words}
              </span>
            </Kv>
          </div>

          <div className="card">
            <div className="card__head">
              <Icon name="timer" />
              <h3>{t("الحضور", "Attendance")}</h3>
            </div>
            <Kv label={t("أيام مجدولة", "Scheduled days")}>{line.scheduled_days}</Kv>
            <Kv label="Office / Remote">
              {line.office_days} / {line.remote_days}
            </Kv>
            <Kv label={t("مرات التأخير", "Times late")}>
              {line.late_days} <span className="muted">({line.late_minutes}{t("د", "m")})</span>
            </Kv>
            <Kv label={t("خروج مبكر", "Early leave")}>
              {line.early_leave_minutes}
              {t("د", "m")}
            </Kv>
            <Kv label={t("نقص الساعات", "Short hours")}>{minutesHm(line.short_minutes)}</Kv>
            <Kv label={t("إجمالي ساعات العمل", "Total hours worked")}>{minutesHm(line.work_minutes)}</Kv>
            <Kv label={t("إجمالي الأوفرتايم", "Total overtime")}>{minutesHm(line.overtime_minutes)}</Kv>
          </div>

          <div className="note note--info">
            <Icon name="shield" />
            <div>
              {t(
                "الأرقام دي متجمدة على قواعد الشهر ده. تعديل الراتب أو الشرائح دلوقتي مش بيغيّر شهر فات.",
                "These figures are frozen on the rules of this month. Changing a salary or a tier today does not rewrite a month already run.",
              )}
            </div>
          </div>
        </div>
      </div>

      {asking && (
        <Confirm
          title={t("اصرف المكافآت", "Release the bonuses")}
          body={t("هتتضاف مكافأة الانضباط ومكافأة التارجت اللي اتحققت على صافي الشهر ده.", "The discipline and target bonuses that were earned are added to this month's net.")}
          yes={t("اصرفهم", "Release them")}
          busy={release.isPending}
          problem={problem}
          onYes={() =>
            release.mutate(undefined, {
              onSuccess: () => {
                setAsking(false);
                setProblem("");
                push({ level: "success", title: t("المكافآت اتصرفت", "The bonuses were released") });
              },
              onError: (error) => setProblem(refusal(error, t("حصلت مشكلة.", "Something went wrong."))),
            })
          }
          onNo={() => {
            setAsking(false);
            setProblem("");
          }}
        />
      )}
    </>
  );
}
