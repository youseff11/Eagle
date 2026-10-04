import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useSearchParams } from "react-router";
import { formErrors } from "../api/adminActions";
import { useAddDepartment, useSaveQuestion } from "../api/hrActions";
import { useHrQuestions } from "../api/queries";
import type { FormErrors } from "../api/types";
import { Waiting, refusal } from "../components/accounts/shared";
import { DjangoForm, useFormEdits } from "../components/admin/DjangoForm";
import { useHrAllowed } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { useLeaveWords } from "../components/leave/shared";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

/**
 * The central bank the bot's questions come from. No set of questions is forced on a department: the department only helps HR
 * find a question, and HR chooses each vacancy's list. A department added here needs no code change.
 */
export function HrQuestionsPage() {
  const { t } = usePreferences();
  const words = useLeaveWords();
  const { push } = useToasts();
  const { me, allowed } = useHrAllowed();
  const [params, setParams] = useSearchParams();
  const department = params.get("department") ?? "";
  const edit = params.get("edit") ?? "";
  const query = useHrQuestions(department, edit, allowed);
  const save = useSaveQuestion();
  const addDepartment = useAddDepartment();
  const data = query.data;
  const edits = useFormEdits(data?.form);
  const departmentEdits = useFormEdits(data?.department_form);
  const [errors, setErrors] = useState<FormErrors>({});
  const [departmentErrors, setDepartmentErrors] = useState<FormErrors>({});
  const [problem, setProblem] = useState("");
  const editing = data?.editing ?? null;
  const { reset } = edits;
  useEffect(() => {
    reset();
    setErrors({});
    setProblem("");
  }, [editing, reset]);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!data) return <Waiting failed={query.isError} />;

  const go = (next: { department?: string; edit?: string }) => {
    const merged = new URLSearchParams();
    const nextDepartment = next.department ?? department;
    if (nextDepartment) merged.set("department", nextDepartment);
    if (next.edit) merged.set("edit", next.edit);
    setParams(merged);
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    setProblem("");
    save.mutate(
      { id: editing, values: edits.edited },
      {
        onSuccess: () => {
          edits.reset();
          push({ level: "success", title: t("اتحفظ", "Saved") });
          if (editing !== null) go({});
        },
        onError: (error) => {
          const found = formErrors(error);
          if (found) setErrors(found);
          else setProblem(refusal(error, t("حصلت مشكلة، ماتحفظش.", "Something went wrong, nothing was saved.")));
        },
      },
    );
  };
  const submitDepartment = (event: FormEvent) => {
    event.preventDefault();
    setDepartmentErrors({});
    addDepartment.mutate(departmentEdits.edited, {
      onSuccess: () => {
        departmentEdits.reset();
        push({ level: "success", title: t("اتسجل", "Recorded") });
      },
      onError: (error) => {
        const found = formErrors(error);
        if (found) setDepartmentErrors(found);
        else push({ level: "danger", title: refusal(error, t("القسم مش مظبوط.", "The department is not right.")) });
      },
    });
  };

  return (
    <>
      <div className="page-head">
        <h1>{t("بنك أسئلة التوظيف", "Recruitment question bank")}</h1>
        <div className="grow" />
        <select className="input" aria-label={t("القسم", "Department")} value={department} onChange={(event) => go({ department: event.target.value })}>
          <option value="">{t("كل الأقسام", "All departments")}</option>
          {data.departments.map((one) => (
            <option key={one.id} value={one.id}>
              {one.label}
            </option>
          ))}
        </select>
      </div>

      <div className="note note--info">
        <Icon name="info" />
        <div>
          {t(
            "مفيش أسئلة مفروضة على أي قسم — القسم بيساعدك توصل للسؤال بس، والاختيار كله بتاعك.",
            "No set of questions is forced on a department. The department only helps you find a question; you choose each vacancy's list.",
          )}
        </div>
      </div>

      <div className="grid grid--main">
        <div className="card">
          <div className="card__head">
            <Icon name="list-checks" />
            <h3>{t("الأسئلة", "Questions")}</h3>
          </div>
          <div className="table-wrap">
            <table className="table" data-table="questions">
              <thead>
                <tr>
                  <th>{t("السؤال", "Question")}</th>
                  <th>{t("القسم", "Department")}</th>
                  <th>{t("النوع", "Type")}</th>
                  <th>{t("بيملا حقل", "Fills")}</th>
                  <th>{t("الحالة", "Status")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.id} data-question={row.id}>
                    <td>
                      {row.text}
                      {row.options.length > 0 && <div className="muted mono">{row.options.join(" · ")}</div>}
                    </td>
                    <td className="muted">{row.department ?? t("عام", "General")}</td>
                    <td className="muted">{words(row.kind)}</td>
                    <td className="mono muted">{row.maps_to ? words(row.maps_to) : "—"}</td>
                    <td>{row.is_active ? <span className="badge badge--ok">{t("شغال", "Active")}</span> : <span className="badge">{t("مقفول", "Off")}</span>}</td>
                    <td>
                      <Link className="btn btn--sm btn--ghost" to={`/hr/questions?${new URLSearchParams({ ...(department ? { department } : {}), edit: String(row.id) })}`}>
                        <Icon name="pen" size="sm" />
                        <span>{t("عدّل", "Edit")}</span>
                      </Link>
                    </td>
                  </tr>
                ))}
                {data.rows.length === 0 && (
                  <tr>
                    <td colSpan={6} className="empty">
                      {t("بنك الأسئلة فاضي — ابدأ بسؤال.", "The bank is empty. Start with one question.")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="sticky-side">
          <div className="card" data-card="question">
            <div className="card__head">
              <Icon name="pen" />
              <h3>{editing !== null ? t("تعديل سؤال", "Edit a question") : t("سؤال جديد", "New question")}</h3>
              {editing !== null && (
                <>
                  <div className="grow" />
                  <button className="btn btn--sm btn--ghost" type="button" onClick={() => go({})}>
                    {t("سؤال جديد بدل التعديل", "New question instead")}
                  </button>
                </>
              )}
            </div>
            <form onSubmit={submit}>
              <DjangoForm fields={data.form} edits={edits} errors={errors} prefix="question" />
              {problem && (
                <div className="note note--high" role="alert">
                  <Icon name="alert" />
                  <div>{problem}</div>
                </div>
              )}
              <button className="btn btn--primary btn--block mt" type="submit" disabled={save.isPending || !edits.dirty}>
                <Icon name="check" size="sm" />
                <span>{t("احفظ", "Save")}</span>
              </button>
            </form>
          </div>

          <div className="card card--flat" data-card="departments">
            <div className="card__head">
              <Icon name="layers" />
              <h3>{t("الأقسام", "Departments")}</h3>
            </div>
            {data.departments.map((one) => (
              <div className="kv" key={one.id}>
                <span>{one.label}</span>
                <span className="mono muted">{one.questions}</span>
              </div>
            ))}
            <form className="mt" onSubmit={submitDepartment}>
              <DjangoForm fields={data.department_form} edits={departmentEdits} errors={departmentErrors} prefix="department" />
              <button className="btn btn--sm btn--block" type="submit" disabled={addDepartment.isPending || !departmentEdits.dirty}>
                <Icon name="plus" size="sm" />
                <span>{t("ضيف قسم", "Add")}</span>
              </button>
            </form>
            <small className="muted">{t("قسم جديد مش محتاج أي تعديل في الكود.", "A new department needs no code change.")}</small>
          </div>
        </div>
      </div>
    </>
  );
}
