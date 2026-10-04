import { useState, type FormEvent } from "react";
import { formErrors } from "../api/adminActions";
import { useAskLeave, useCancelLeave } from "../api/leaveActions";
import { useMyLeave } from "../api/queries";
import type { FormErrors } from "../api/types";
import { Waiting, refusal } from "../components/accounts/shared";
import { DjangoForm, useFormEdits } from "../components/admin/DjangoForm";
import { Icon } from "../components/Icon";
import { LeaveStatusBadge, useLeaveWords } from "../components/leave/shared";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";
import { minutesHm } from "../lib/payroll";

/**
 * A person's own leave: what is left of this month's allowance, the requests so far, and the form that asks for more. It is
 * only ever the person's own - nothing in a request names anybody else. Once approved, the days are written onto the
 * attendance sheet by the system, so they never read as absence.
 */
export function MyLeavePage() {
  const { t } = usePreferences();
  const { push } = useToasts();
  const words = useLeaveWords();
  const query = useMyLeave();
  const ask = useAskLeave();
  const cancel = useCancelLeave();
  const data = query.data;
  const edits = useFormEdits(data?.form);
  const [errors, setErrors] = useState<FormErrors>({});
  const [problem, setProblem] = useState("");

  if (!data) return <Waiting failed={query.isError} />;
  const { balance } = data;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    setProblem("");
    ask.mutate(edits.edited, {
      onSuccess: () => {
        edits.reset();
        push({ level: "success", title: t("الطلب اتبعت", "Request sent") });
      },
      onError: (error) => {
        const found = formErrors(error);
        if (found) setErrors(found);
        else setProblem(refusal(error, t("حصلت مشكلة، الطلب ماتبعتش.", "Something went wrong, the request was not sent.")));
      },
    });
  };
  const withdraw = (id: number) =>
    cancel.mutate(id, {
      onSuccess: () => push({ level: "success", title: t("اتسحب", "Withdrawn") }),
      onError: (error) => push({ level: "danger", title: refusal(error, t("حصلت مشكلة.", "Something went wrong.")) }),
    });

  return (
    <>
      <div className="page-head">
        <h1>{t("إجازاتي", "My leave")}</h1>
      </div>

      <div className="grid grid--4">
        <div className="kpi">
          <div className="kpi__label">{t("رصيد الشهر", "This month's allowance")}</div>
          <div className="kpi__value mono">{balance.allowance}</div>
        </div>
        <div className="kpi">
          <div className="kpi__label">{t("مستخدم", "Taken")}</div>
          <div className="kpi__value mono">{balance.taken}</div>
        </div>
        <div className="kpi">
          <div className="kpi__label">{t("مستني موافقة", "Pending")}</div>
          <div className="kpi__value mono">{balance.pending}</div>
        </div>
        <div className={`kpi${balance.left ? " kpi--ok" : " kpi--warn"}`}>
          <div className="kpi__label">{t("الباقي", "Left")}</div>
          <div className="kpi__value mono">{balance.left}</div>
        </div>
      </div>

      {balance.over > 0 && (
        <div className="note note--warn" data-note="over">
          <Icon name="alert" />
          <div>
            {t(
              `فيه ${balance.over} يوم فوق الرصيد — بيترجم لخصم لما الشهر يتحسب.`,
              `${balance.over} days are beyond the allowance and price as a deduction when the month runs.`,
            )}
          </div>
        </div>
      )}

      <div className="grid grid--main">
        <div className="card">
          <div className="card__head">
            <Icon name="history" />
            <h3>{t("طلباتي", "My requests")}</h3>
          </div>
          <div className="table-wrap">
            <table className="table" data-table="mine">
              <thead>
                <tr>
                  <th>{t("النوع", "Kind")}</th>
                  <th>{t("من", "From")}</th>
                  <th>{t("إلى", "To")}</th>
                  <th>{t("المدة", "Length")}</th>
                  <th>{t("الحالة", "Status")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.id} data-request={row.id}>
                    <td>{words(row.kind)}</td>
                    <td className="mono">{row.start_date}</td>
                    <td className="mono">{row.end_date ?? "—"}</td>
                    <td className="mono">
                      {row.is_permission ? (
                        minutesHm(row.minutes)
                      ) : (
                        <>
                          {row.days} <span className="muted">{t("يوم", "days")}</span>
                        </>
                      )}
                    </td>
                    <td>
                      <LeaveStatusBadge status={row.status} />
                    </td>
                    <td>
                      {row.is_open ? (
                        <button className="btn btn--sm btn--ghost" type="button" disabled={cancel.isPending} onClick={() => withdraw(row.id)}>
                          <Icon name="x" size="sm" />
                          <span>{t("اسحب", "Withdraw")}</span>
                        </button>
                      ) : (
                        row.decision_note && <span className="muted">{row.decision_note}</span>
                      )}
                    </td>
                  </tr>
                ))}
                {data.rows.length === 0 && (
                  <tr>
                    <td colSpan={6} className="empty">
                      {t("مفيش طلبات لسه.", "Nothing yet.")}
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
              <Icon name="plus" />
              <h3>{t("اطلب إجازة", "Ask for leave")}</h3>
            </div>
            <form onSubmit={submit}>
              <DjangoForm fields={data.form} edits={edits} errors={errors} prefix="leave" />
              {problem && (
                <div className="note note--high" role="alert">
                  <Icon name="alert" />
                  <div>{problem}</div>
                </div>
              )}
              <button className="btn btn--primary btn--block" type="submit" disabled={ask.isPending || !edits.dirty}>
                <Icon name="send" size="sm" />
                <span>{t("ابعت الطلب", "Send")}</span>
              </button>
            </form>
          </div>

          <div className="note note--info" data-note="chain">
            <Icon name="info" />
            <div>
              {data.needs_manager
                ? t("الطلب بيروح لمديرك الأول وبعدين للموارد البشرية.", "Your manager signs first, then HR.")
                : t("الطلب بيروح للموارد البشرية مباشرة.", "The request goes straight to HR.")}
              <div className="muted mt">
                {t(
                  "أول ما يتوافق عليه، الأيام بتتسجل في كشف حضورك تلقائيًا — فمش هتظهر غياب.",
                  "Once approved the days are written onto your attendance sheet, so they never read as absence.",
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
