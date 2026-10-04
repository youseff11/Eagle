import { Navigate } from "react-router";
import { useDecideClaim } from "../api/hrActions";
import { useHrOvertime } from "../api/queries";
import { Waiting, refusal } from "../components/accounts/shared";
import { useHrAllowed } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

/**
 * Extra hours waiting for a decision - the mirror of a deduction. The engine works out that the time was worked; a person's
 * approval is what pays for it. A claim that has been decided is not decided again from here.
 */
export function HrOvertimePage() {
  const { t } = usePreferences();
  const { push } = useToasts();
  const { me, allowed } = useHrAllowed();
  const query = useHrOvertime(allowed);
  const decide = useDecideClaim();
  const data = query.data;

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!data) return <Waiting failed={query.isError} />;

  const act = (id: number, action: "approve" | "reject") =>
    decide.mutate({ id, action }, { onError: (error) => push({ level: "danger", title: refusal(error, t("حصلت مشكلة.", "Something went wrong.")) }) });

  return (
    <>
      <div className="page-head">
        <h1>{t("الأوفرتايم", "Overtime claims")}</h1>
      </div>

      <div className="note note--info">
        <Icon name="info" />
        <div>
          {t(
            "النظام بيحسب إن الوقت اتشُغل فعلًا، والاعتماد هو اللي بيصرفه — بالظبط زي الخصومات بالعكس. سعر الساعة بيتاخد من قواعد الحساب، وصفر معناه قيمة اليوم ÷ ساعات اليوم.",
            "The engine works out that the time was worked; approval is what pays for it - the exact mirror of a deduction. The hourly rate comes from the payroll rules, and zero means the day's value divided by the daily hours.",
          )}
        </div>
      </div>

      <div className="card">
        <div className="card__head">
          <Icon name="clock" />
          <h3>{t("مستنية اعتماد", "Waiting for approval")}</h3>
        </div>
        <div className="table-wrap">
          <table className="table" data-table="pending">
            <thead>
              <tr>
                <th>{t("الموظف", "Employee")}</th>
                <th>{t("اليوم", "Date")}</th>
                <th>{t("الوقت الإضافي", "Extra time")}</th>
                <th>{t("سعر الساعة", "Rate")}</th>
                <th>{t("المبلغ", "Amount")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.pending.map((claim) => (
                <tr key={claim.id} data-claim={claim.id}>
                  <td>{claim.user}</td>
                  <td className="mono">{claim.date}</td>
                  <td className="mono">{claim.hours}</td>
                  <td className="mono">{claim.hourly_rate}</td>
                  <td className="mono">{claim.amount}</td>
                  <td>
                    <div className="row row--tight">
                      <button className="btn btn--ok btn--sm" type="button" disabled={decide.isPending} onClick={() => act(claim.id, "approve")}>
                        <Icon name="check" size="sm" />
                        <span>{t("اعتمد", "Approve")}</span>
                      </button>
                      <button className="btn btn--danger btn--sm" type="button" disabled={decide.isPending} onClick={() => act(claim.id, "reject")}>
                        <Icon name="x" size="sm" />
                        <span>{t("ارفض", "Reject")}</span>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {data.pending.length === 0 && (
                <tr>
                  <td colSpan={6} className="empty">
                    {t("مفيش أوفرتايم مستني.", "Nothing waiting.")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="card__head">
          <Icon name="history" />
          <h3>{t("اتقرر فيها", "Decided")}</h3>
        </div>
        <div className="table-wrap">
          <table className="table" data-table="decided">
            <thead>
              <tr>
                <th>{t("الموظف", "Employee")}</th>
                <th>{t("اليوم", "Date")}</th>
                <th>{t("الوقت", "Time")}</th>
                <th>{t("المبلغ", "Amount")}</th>
                <th>{t("الحالة", "Status")}</th>
                <th>{t("مين", "By")}</th>
              </tr>
            </thead>
            <tbody>
              {data.decided.map((claim) => (
                <tr key={claim.id} data-claim={claim.id}>
                  <td>{claim.user}</td>
                  <td className="mono">{claim.date}</td>
                  <td className="mono">{claim.hours}</td>
                  <td className="mono">{claim.amount}</td>
                  <td>
                    {claim.status === "approved" ? (
                      <span className="badge badge--ok">{t("معتمد", "Approved")}</span>
                    ) : (
                      <span className="badge badge--dead">{t("مرفوض", "Rejected")}</span>
                    )}
                  </td>
                  <td>{claim.decided_by ?? "—"}</td>
                </tr>
              ))}
              {data.decided.length === 0 && (
                <tr>
                  <td colSpan={6} className="empty">
                    {t("لسه مفيش.", "Nothing yet.")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
