import { Loading } from "../components/Loading";
import { useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router";
import { useApprovePeriod, useDecideViolation, useRunMonth } from "../api/accountsActions";
import { useAccountsOverview } from "../api/queries";
import { MonthPicker } from "../components/accounts/MonthPicker";
import { Penalty, refusal, useMayRunTheMonth } from "../components/accounts/shared";
import { Confirm } from "../components/Confirm";
import { Icon } from "../components/Icon";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";
import { hasMoney, periodLabel, periodText } from "../lib/payroll";

/**
 * The month's sheet: every translator's line, the totals, and what is waiting - deductions to approve, translators with no
 * salary, jobs whose words nobody settled. Nothing here moves money on its own: the system proposes, a person approves, and
 * a locked month is never computed again.
 */
export function AccountsOverviewPage() {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const { me, allowed } = useMayRunTheMonth();
  const [params, setParams] = useSearchParams();
  const period = params.get("period") ?? "";
  const query = useAccountsOverview(period, allowed);
  const run = useRunMonth();
  const approve = useApprovePeriod();
  const decide = useDecideViolation();
  const [locking, setLocking] = useState(false);
  const [problem, setProblem] = useState("");

  if (me.data && !allowed) return <Navigate to="/" replace />;
  const data = query.data;
  const name = (value: { ar: string; en: string }) => (lang === "ar" ? value.ar : value.en);

  const runMonth = () =>
    data &&
    run.mutate(periodText(data.year, data.month), {
      onSuccess: () => push({ level: "success", title: t("اتحسب", "Computed") }),
      onError: (error) => push({ level: "danger", title: refusal(error, t("حصلت مشكلة، الشهر ماتحسبش.", "Something went wrong, the month was not computed.")) }),
    });
  const approveMonth = (lock: boolean) =>
    data?.period &&
    approve.mutate(
      { id: data.period.id, lock },
      {
        onSuccess: () => {
          setLocking(false);
          push({ level: "success", title: lock ? t("الشهر اتقفل", "The month is locked") : t("اتعمد", "Approved") });
        },
        onError: (error) => setProblem(refusal(error, t("حصلت مشكلة.", "Something went wrong."))),
      },
    );
  const decideRow = (id: number, action: "approve" | "reject") =>
    decide.mutate(
      { id, action },
      { onError: (error) => push({ level: "danger", title: refusal(error, t("حصلت مشكلة.", "Something went wrong.")) }) },
    );

  return (
    <>
      <div className="page-head">
        <h1>{t("حسابات المترجمين", "Translator payroll")}</h1>
        {data && <div className="page-head__sub mono">{periodLabel(data.year, data.month)}</div>}
        <div className="grow" />
        {data && (
          <MonthPicker
            periods={data.periods}
            year={data.year}
            month={data.month}
            onChange={(next) => setParams(next ? { period: next } : {})}
          />
        )}
        <button className="btn btn--primary" type="button" disabled={!data || run.isPending} onClick={runMonth}>
          <Icon name="refresh" size="sm" />
          <span>{t("احسب الشهر", "Run the month")}</span>
        </button>
      </div>

      {data ? (
        <>
          {data.missing_salary.length > 0 && (
            <div className="note note--warn" data-note="salary">
              <Icon name="alert" />
              <div>
                <div>{t("فيه مترجمين من غير راتب مسجل — سطرهم هيطلع بصفر:", "Some translators have no salary on record - their line computes to zero:")}</div>
                <div className="row row--tight">
                  {data.missing_salary.map((person) => (
                    <Link key={person.id} className="chip" to={`/accounts/salary/${person.id}`}>
                      {person.name}
                    </Link>
                  ))}
                </div>
              </div>
            </div>
          )}

          {data.unsettled_tasks.length > 0 && (
            <div className="note note--warn" data-note="words">
              <Icon name="alert" />
              <div>
                <div>
                  {t(
                    "تاسكات اتسلمت الشهر ده وعدد كلماتها لسه مش متأكد — أكدها قبل ما تقفل الشهر:",
                    "Jobs delivered this month whose word count nobody has settled - settle them before locking:",
                  )}
                </div>
                <div className="row row--tight">
                  {data.unsettled_tasks.map((task) =>
                    data.can.task ? (
                      <Link key={task.code} className="chip mono" to={`/tasks/${encodeURIComponent(task.code)}`}>
                        {task.code} <span className="muted">{task.translator ?? "—"}</span>
                      </Link>
                    ) : (
                      <span key={task.code} className="chip mono">
                        {task.code} <span className="muted">{task.translator ?? "—"}</span>
                      </span>
                    ),
                  )}
                </div>
              </div>
            </div>
          )}

          {data.totals && (
            <div className="grid grid--4">
              <div className="kpi">
                <div className="kpi__label">{t("الصافي", "Net")}</div>
                <div className="kpi__value mono">{data.totals.net}</div>
              </div>
              <div className="kpi">
                <div className="kpi__label">{t("إجمالي الكلمات", "Words")}</div>
                <div className="kpi__value mono">{data.totals.words}</div>
              </div>
              <div className={`kpi${hasMoney(data.totals.deductions) ? " kpi--warn" : ""}`}>
                <div className="kpi__label">{t("خصومات معتمدة", "Approved deductions")}</div>
                <div className="kpi__value mono">{data.totals.deductions}</div>
              </div>
              <div className={`kpi${data.totals.alerts > 0 ? " kpi--danger" : ""}`}>
                <div className="kpi__label">{t("تحت حد التنبيه", "Below the alert line")}</div>
                <div className="kpi__value mono">{data.totals.alerts}</div>
              </div>
            </div>
          )}

          <div className="card">
            <div className="card__head">
              <Icon name="calendar" />
              <h3>{t("كشف الشهر", "The month")}</h3>
              <div className="grow" />
              {data.period && (
                <>
                  <span className={`badge ${data.period.status.value === "locked" ? "badge--dead" : data.period.status.value === "approved" ? "badge--ok" : "badge--wait"}`}>
                    {name(data.period.status)}
                  </span>
                  {data.period.status.value === "draft" && (
                    <button className="btn btn--sm btn--ok" type="button" disabled={approve.isPending} onClick={() => approveMonth(false)}>
                      {t("اعتماد", "Approve")}
                    </button>
                  )}
                  {data.period.status.value === "approved" && (
                    <button className="btn btn--sm" type="button" disabled={approve.isPending} onClick={() => setLocking(true)}>
                      {t("قفل الشهر", "Lock the month")}
                    </button>
                  )}
                </>
              )}
            </div>
            {data.lines.length > 0 ? (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>{t("المترجم", "Translator")}</th>
                      <th>{t("الأساسي", "Base")}</th>
                      <th>{t("أيام شغل", "Worked")}</th>
                      <th>{t("إجازة", "Leave")}</th>
                      <th>{t("كلمات", "Words")}</th>
                      <th>{t("بونص الإنتاج", "Production bonus")}</th>
                      <th>{t("مكافآت", "Bonuses")}</th>
                      <th>{t("خصومات", "Deductions")}</th>
                      <th>{t("الصافي", "Net")}</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {data.lines.map((line) => (
                      <tr key={line.id} data-line={line.id}>
                        <td>
                          <div className="row row--tight">
                            <div className="avatar avatar--sm">{line.user.initials}</div>
                            <div>
                              <div>{line.user.name}</div>
                              <small className="muted mono">{line.user.username}</small>
                            </div>
                          </div>
                        </td>
                        <td className="mono">{line.base_salary}</td>
                        <td className="mono">
                          {line.worked_days}
                          <span className="muted">/{line.working_days}</span>
                        </td>
                        <td className="mono">
                          {line.leave_days}
                          {line.extra_leave_days > 0 && <span className="badge badge--dead">+{line.extra_leave_days}</span>}
                          {line.unexcused_days > 0 && (
                            <span className="badge badge--dead">
                              {t("غياب", "Absent")} {line.unexcused_days}
                            </span>
                          )}
                        </td>
                        <td className={`mono${line.below_alert ? " deadline--late" : ""}`}>{line.total_words}</td>
                        <td className="mono">{line.production_bonus}</td>
                        <td className="mono">
                          {line.bonus_total}
                          {hasMoney(line.pending_bonus) && (
                            <span className="badge badge--wait">
                              {t("مستنية", "Awaiting")} {line.pending_bonus}
                            </span>
                          )}
                        </td>
                        <td className="mono">{line.deductions}</td>
                        <td className="mono">
                          <strong>{line.net}</strong>
                        </td>
                        <td>
                          {data.can.line && (
                            <Link className="btn btn--sm" to={`/accounts/lines/${line.id}`}>
                              {t("التفاصيل", "Detail")}
                            </Link>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="empty">{t("الشهر ده لسه ماتحسبش. اضغط «احسب الشهر».", "This month has not been computed yet. Use Run the month.")}</div>
            )}
          </div>

          <div className="card">
            <div className="card__head">
              <Icon name="alert" />
              <h3>{t("خصومات مستنية الاعتماد", "Deductions awaiting approval")}</h3>
              <div className="grow" />
              <Link className="btn btn--sm" to="/accounts/violations">
                {t("كل المخالفات", "All violations")}
              </Link>
            </div>
            {data.pending_violations.length > 0 ? (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>{t("المترجم", "Translator")}</th>
                      <th>{t("التاريخ", "Date")}</th>
                      <th>{t("النوع", "Kind")}</th>
                      <th>{t("السبب", "Reason")}</th>
                      <th>{t("الخصم", "Penalty")}</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {data.pending_violations.map((row) => (
                      <tr key={row.id} data-violation={row.id}>
                        <td>{row.user}</td>
                        <td className="mono">{row.date}</td>
                        <td>
                          {name(row.kind)} {row.escalated && <span className="badge badge--dead">{t("تصعيد للمدير", "Escalated")}</span>}
                        </td>
                        <td className="muted">{row.reason}</td>
                        <td className="mono">
                          <Penalty row={row} />
                        </td>
                        <td>
                          <div className="row row--tight">
                            <button className="btn btn--sm btn--ok" type="button" disabled={decide.isPending} onClick={() => decideRow(row.id, "approve")}>
                              {t("اعتماد", "Approve")}
                            </button>
                            <button className="btn btn--sm btn--ghost" type="button" disabled={decide.isPending} onClick={() => decideRow(row.id, "reject")}>
                              {t("رفض", "Reject")}
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="empty">{t("مفيش حاجة مستنية.", "Nothing waiting.")}</div>
            )}
          </div>

          <div className="note note--info">
            <Icon name="info" />
            <div>
              {t(
                "مفيش خصم بيتطبق لوحده. النظام بيقترح، والمدير بيعتمد — والمكافأتين الشهريتين بيتحسبوا وبيتصرفوا بعد الاعتماد.",
                "No deduction applies by itself. The system proposes, the manager approves - and the two monthly bonuses are computed but paid only once released.",
              )}
            </div>
          </div>
        </>
      ) : query.isError ? (
        <div className="card empty" role="alert">
          <Icon name="alert" size="xl" />
          <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
        </div>
      ) : (
        <Loading className="card empty" />
      )}

      {locking && (
        <Confirm
          title={t("قفل الشهر", "Lock the month")}
          body={t("الشهر المقفول مش بيتحسب تاني ومفيش رجوع. متأكد؟", "A locked month is never computed again and there is no way back. Sure?")}
          yes={t("اقفل الشهر", "Lock it")}
          danger
          busy={approve.isPending}
          problem={problem}
          onYes={() => approveMonth(true)}
          onNo={() => {
            setLocking(false);
            setProblem("");
          }}
        />
      )}
    </>
  );
}
