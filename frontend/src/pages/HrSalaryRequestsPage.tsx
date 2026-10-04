import { useEffect, useState, type FormEvent } from "react";
import { Navigate, useSearchParams } from "react-router";
import { formErrors } from "../api/adminActions";
import { useAskSalaryChange, useDecideSalaryChange } from "../api/hrActions";
import { useHrSalaryRequests } from "../api/queries";
import type { FormErrors } from "../api/types";
import { Waiting, refusal } from "../components/accounts/shared";
import { DjangoForm, useFormEdits } from "../components/admin/DjangoForm";
import { useHrAllowed } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

/**
 * HR cannot edit a salary. The request starts here, the owner approves, and approval is what writes the salary record that
 * accounting then sees. Money is text all the way: nothing here adds or compares it.
 */
export function HrSalaryRequestsPage() {
  const { t } = usePreferences();
  const { push } = useToasts();
  const { me, allowed } = useHrAllowed();
  const [params, setParams] = useSearchParams();
  const user = params.get("user") ?? "";
  const query = useHrSalaryRequests(user, allowed);
  const ask = useAskSalaryChange();
  const decide = useDecideSalaryChange();
  const data = query.data;
  const edits = useFormEdits(data?.form);
  const [errors, setErrors] = useState<FormErrors>({});
  const [problem, setProblem] = useState("");
  const [notes, setNotes] = useState<Record<number, string>>({});
  // What was typed for one person must not be waiting in the boxes when the next one is picked: it is a money form.
  const { reset } = edits;
  const personId = data?.person?.id ?? null;
  useEffect(() => {
    reset();
    setErrors({});
    setProblem("");
  }, [personId, reset]);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!data) return <Waiting failed={query.isError} />;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!data.person) return;
    setErrors({});
    setProblem("");
    ask.mutate(
      { user: data.person.id, values: edits.edited },
      {
        onSuccess: () => {
          edits.reset();
          push({ level: "success", title: t("الطلب اتبعت للمالك", "The request went to the owner") });
        },
        onError: (error) => {
          const found = formErrors(error);
          if (found) setErrors(found);
          else setProblem(refusal(error, t("حصلت مشكلة، الطلب ماتبعتش.", "Something went wrong, the request was not sent.")));
        },
      },
    );
  };
  const act = (id: number, action: "approve" | "reject") =>
    decide.mutate(
      { id, action, note: action === "reject" ? (notes[id] ?? "") : "" },
      { onError: (error) => push({ level: "danger", title: refusal(error, t("حصلت مشكلة.", "Something went wrong.")) }) },
    );

  return (
    <>
      <div className="page-head">
        <h1>{t("طلبات تغيير الراتب", "Salary change requests")}</h1>
      </div>

      <div className="note note--info">
        <Icon name="shield" />
        <div>
          {t(
            "الـHR مالهاش صلاحية تعدّل راتب مباشرة — الطلب من هنا والموافقة من المالك.",
            "HR cannot edit a salary directly. The request starts here, the owner approves, and approval is what writes the salary record that accounting then sees.",
          )}
        </div>
      </div>

      <div className="card">
        <div className="card__head">
          <Icon name="hand" />
          <h3>{t("مستني قرار المالك", "Waiting for the owner")}</h3>
        </div>
        {data.pending.map((row) => (
          <div className="card card--flat" key={row.id} data-pending={row.id}>
            <div className="row row--between">
              <div>
                <b>{row.user.name}</b>
                <div className="mono">
                  {row.current_amount} → <b>{row.new_amount}</b>{" "}
                  <span className={row.delta.startsWith("-") ? "deadline--late" : "deadline--ok"}>({row.delta})</span>
                </div>
                <div className="muted">
                  {t("ساري من", "From")} <span className="mono">{row.effective_from}</span>
                  {row.requested_by && (
                    <>
                      {" "}
                      · {t("طلب", "asked by")} {row.requested_by}
                    </>
                  )}
                </div>
                {row.reason && <div className="muted">{row.reason}</div>}
              </div>
              {data.can.decide ? (
                <div className="row row--tight">
                  <button className="btn btn--ok btn--sm" type="button" disabled={decide.isPending} onClick={() => act(row.id, "approve")}>
                    <Icon name="check" size="sm" />
                    <span>{t("وافق", "Approve")}</span>
                  </button>
                  <input
                    className="input"
                    type="text"
                    aria-label={t("السبب", "Reason")}
                    placeholder={t("السبب", "Reason")}
                    maxLength={250}
                    value={notes[row.id] ?? ""}
                    onChange={(event) => setNotes((previous) => ({ ...previous, [row.id]: event.target.value }))}
                  />
                  <button className="btn btn--danger btn--sm" type="button" disabled={decide.isPending} onClick={() => act(row.id, "reject")}>
                    <Icon name="x" size="sm" />
                    <span>{t("ارفض", "Reject")}</span>
                  </button>
                </div>
              ) : (
                <span className="badge badge--wait">{t("مستني المالك", "With the owner")}</span>
              )}
            </div>
          </div>
        ))}
        {data.pending.length === 0 && <div className="empty">{t("مفيش طلبات مستنية.", "Nothing waiting.")}</div>}
      </div>

      <div className="grid grid--main">
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
                  <th>{t("من", "From")}</th>
                  <th>{t("إلى", "To")}</th>
                  <th>{t("ساري من", "Effective")}</th>
                  <th>{t("الحالة", "Status")}</th>
                  <th>{t("مين", "By")}</th>
                </tr>
              </thead>
              <tbody>
                {data.decided.map((row) => (
                  <tr key={row.id} data-decided={row.id}>
                    <td>{row.user.name}</td>
                    <td className="mono">{row.current_amount}</td>
                    <td className="mono">{row.new_amount}</td>
                    <td className="mono">{row.effective_from}</td>
                    <td>
                      {row.status === "approved" ? (
                        <span className="badge badge--ok">{t("اتوافق عليه", "Approved")}</span>
                      ) : (
                        <span className="badge badge--dead">{t("مرفوض", "Rejected")}</span>
                      )}
                    </td>
                    <td>{row.decided_by ?? "—"}</td>
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

        <div className="sticky-side">
          <div className="card">
            <div className="card__head">
              <Icon name="plus" />
              <h3>{t("اطلب تغيير", "Request a change")}</h3>
            </div>
            <div className="field">
              <label htmlFor="salary-person">{t("الموظف", "Employee")}</label>
              <select id="salary-person" className="input" value={data.person?.id ?? ""} onChange={(event) => setParams(event.target.value ? { user: event.target.value } : {})}>
                <option value="">{t("اختار", "Pick")}</option>
                {data.people.map((one) => (
                  <option key={one.id} value={one.id}>
                    {one.name}
                  </option>
                ))}
              </select>
            </div>
            {data.person && (
              <>
                <div className="kv">
                  <span>{t("الراتب الحالي", "Current salary")}</span>
                  <b className="mono" data-current>
                    {data.current}
                  </b>
                </div>
                <form onSubmit={submit}>
                  <DjangoForm fields={data.form} edits={edits} errors={errors} prefix="salary" />
                  {problem && (
                    <div className="note note--high" role="alert">
                      <Icon name="alert" />
                      <div>{problem}</div>
                    </div>
                  )}
                  <button className="btn btn--primary btn--block" type="submit" disabled={ask.isPending || !edits.dirty}>
                    <Icon name="send" size="sm" />
                    <span>{t("ابعت للمالك", "Send to the owner")}</span>
                  </button>
                </form>
              </>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
