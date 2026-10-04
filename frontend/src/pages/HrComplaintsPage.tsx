import { useState, type FormEvent } from "react";
import { Navigate, useSearchParams } from "react-router";
import { formErrors } from "../api/adminActions";
import { useLogComplaint, useResolveComplaint } from "../api/hrActions";
import { useHrComplaints } from "../api/queries";
import type { FormErrors } from "../api/types";
import { Waiting, refusal } from "../components/accounts/shared";
import { DjangoForm, useFormEdits } from "../components/admin/DjangoForm";
import { useHrAllowed } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { LeaveStatusBadge } from "../components/leave/shared";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

/** Complaints clients made about a translator's work. A client is named by code and a task by code: HR need not know who the client is. */
export function HrComplaintsPage() {
  const { t } = usePreferences();
  const { push } = useToasts();
  const { me, allowed } = useHrAllowed();
  const [params, setParams] = useSearchParams();
  const translator = params.get("translator") ?? "";
  const query = useHrComplaints(translator, allowed);
  const log = useLogComplaint();
  const resolve = useResolveComplaint();
  const data = query.data;
  const edits = useFormEdits(data?.form);
  const [errors, setErrors] = useState<FormErrors>({});
  const [problem, setProblem] = useState("");

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!data) return <Waiting failed={query.isError} />;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    setProblem("");
    log.mutate(edits.edited, {
      onSuccess: () => {
        edits.reset();
        push({ level: "success", title: t("اتسجلت", "Logged") });
      },
      onError: (error) => {
        const found = formErrors(error);
        if (found) setErrors(found);
        else setProblem(refusal(error, t("حصلت مشكلة، ماتسجلتش.", "Something went wrong, nothing was logged.")));
      },
    });
  };
  const toggle = (id: number) =>
    resolve.mutate(id, { onError: (error) => push({ level: "danger", title: refusal(error, t("حصلت مشكلة.", "Something went wrong.")) }) });

  return (
    <>
      <div className="page-head">
        <h1>{t("شكاوى العملاء", "Client complaints")}</h1>
        <div className="grow" />
        <select
          className="input"
          aria-label={t("المترجم", "Translator")}
          value={translator}
          onChange={(event) => setParams(event.target.value ? { translator: event.target.value } : {})}
        >
          <option value="">{t("كل المترجمين", "Everyone")}</option>
          {data.people.map((one) => (
            <option key={one.id} value={one.id}>
              {one.name}
            </option>
          ))}
        </select>
      </div>

      <div className="grid grid--main">
        <div className="card">
          <div className="card__head">
            <Icon name="thumbs-down" />
            <h3>{t("المسجّل", "Logged")}</h3>
          </div>
          <div className="table-wrap">
            <table className="table" data-table="complaints">
              <thead>
                <tr>
                  <th>{t("اليوم", "Date")}</th>
                  <th>{t("الشكوى", "Complaint")}</th>
                  <th>{t("المترجم", "Translator")}</th>
                  <th>{t("التاسك", "Task")}</th>
                  <th>{t("الدرجة", "Severity")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.id} data-complaint={row.id}>
                    <td className="mono">{row.date ?? "—"}</td>
                    <td>
                      {row.summary}
                      {row.detail && <div className="muted">{row.detail.length > 90 ? `${row.detail.slice(0, 89)}…` : row.detail}</div>}
                    </td>
                    <td>{row.translator ?? "—"}</td>
                    <td className="mono muted">{row.task ?? "—"}</td>
                    <td>
                      <LeaveStatusBadge status={row.severity} />
                    </td>
                    <td>
                      <button className="btn btn--sm btn--ghost" type="button" disabled={resolve.isPending} onClick={() => toggle(row.id)}>
                        <Icon name={row.resolved ? "check-circle" : "check"} size="sm" />
                        <span>{row.resolved ? t("اتقفلت", "Resolved") : t("اقفلها", "Resolve")}</span>
                      </button>
                    </td>
                  </tr>
                ))}
                {data.rows.length === 0 && (
                  <tr>
                    <td colSpan={6} className="empty">
                      {t("مفيش شكاوى — وده خبر كويس.", "No complaints, which is good news.")}
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
              <h3>{t("سجّل شكوى", "Log a complaint")}</h3>
            </div>
            <form onSubmit={submit}>
              <DjangoForm fields={data.form} edits={edits} errors={errors} prefix="complaint" />
              {problem && (
                <div className="note note--high" role="alert">
                  <Icon name="alert" />
                  <div>{problem}</div>
                </div>
              )}
              <button className="btn btn--primary btn--block" type="submit" disabled={log.isPending || !edits.dirty}>
                <Icon name="check" size="sm" />
                <span>{t("سجّل", "Log")}</span>
              </button>
            </form>
          </div>
        </div>
      </div>
    </>
  );
}
