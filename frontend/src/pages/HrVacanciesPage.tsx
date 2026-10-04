import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router";
import { formErrors } from "../api/adminActions";
import { useCreateVacancy } from "../api/hrActions";
import { useHrVacancies } from "../api/queries";
import type { FormErrors } from "../api/types";
import { Waiting, refusal } from "../components/accounts/shared";
import { DjangoForm, useFormEdits } from "../components/admin/DjangoForm";
import { useHrAllowed } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { LeaveStatusBadge, useLeaveWords } from "../components/leave/shared";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

/** Every vacancy with how many applied, and the form that adds one. After saving you pick the questions the bot will ask for it. */
export function HrVacanciesPage() {
  const { t } = usePreferences();
  const words = useLeaveWords();
  const { push } = useToasts();
  const navigate = useNavigate();
  const { me, allowed } = useHrAllowed();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const query = useHrVacancies(status, allowed);
  const create = useCreateVacancy();
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
    create.mutate(edits.edited, {
      onSuccess: (answer) => {
        edits.reset();
        push({ level: "success", title: t("اتسجلت", "Recorded") });
        navigate(`/hr/vacancies/${answer.code}`);
      },
      onError: (error) => {
        const found = formErrors(error);
        if (found) setErrors(found);
        else setProblem(refusal(error, t("حصلت مشكلة، ماتسجلتش.", "Something went wrong, nothing was recorded.")));
      },
    });
  };

  return (
    <>
      <div className="page-head">
        <h1>{t("الوظائف", "Vacancies")}</h1>
        <div className="grow" />
        <select className="input" aria-label={t("الحالة", "Status")} value={status} onChange={(event) => setParams(event.target.value ? { status: event.target.value } : {})}>
          <option value="">{t("كل الحالات", "All")}</option>
          {data.statuses.map((one) => (
            <option key={one.value} value={one.value}>
              {words(one)}
            </option>
          ))}
        </select>
      </div>

      <div className="grid grid--main">
        <div className="card">
          <div className="card__head">
            <Icon name="layers" />
            <h3>{t("الوظائف المسجلة", "All vacancies")}</h3>
          </div>
          <div className="table-wrap">
            <table className="table" data-table="vacancies">
              <thead>
                <tr>
                  <th>{t("الكود", "Code")}</th>
                  <th>{t("المسمى", "Title")}</th>
                  <th>{t("القسم", "Department")}</th>
                  <th>{t("النظام", "Mode")}</th>
                  <th>{t("متقدمين", "Applicants")}</th>
                  <th>{t("الحالة", "Status")}</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.code} data-vacancy={row.code}>
                    <td className="mono">
                      <Link to={`/hr/vacancies/${row.code}`}>{row.code}</Link>
                    </td>
                    <td>{row.title}</td>
                    <td className="muted">{row.department ?? "—"}</td>
                    <td>
                      <span className="chip">{words(row.work_mode)}</span>
                    </td>
                    <td className="mono">{row.applicants}</td>
                    <td>
                      <LeaveStatusBadge status={row.status} />
                    </td>
                  </tr>
                ))}
                {data.rows.length === 0 && (
                  <tr>
                    <td colSpan={6} className="empty">
                      {t("مفيش وظايف لسه.", "No vacancies yet.")}
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
              <h3>{t("وظيفة جديدة", "New vacancy")}</h3>
            </div>
            <form onSubmit={submit}>
              <DjangoForm fields={data.form} edits={edits} errors={errors} prefix="vacancy" />
              {problem && (
                <div className="note note--high" role="alert">
                  <Icon name="alert" />
                  <div>{problem}</div>
                </div>
              )}
              <button className="btn btn--primary btn--block" type="submit" disabled={create.isPending || !edits.dirty}>
                <Icon name="check" size="sm" />
                <span>{t("احفظ", "Save")}</span>
              </button>
              <small className="muted">{t("بعد الحفظ تقدر تختار أسئلة البوت للوظيفة دي.", "After saving you pick the questions the bot will ask for it.")}</small>
            </form>
          </div>
        </div>
      </div>
    </>
  );
}
