import { useState, type FormEvent } from "react";
import { Link, Navigate, useSearchParams } from "react-router";
import { formErrors } from "../api/adminActions";
import { useDecideReview, useOpenReviews } from "../api/hrActions";
import { useHrProbation } from "../api/queries";
import type { FormErrors, FormField, HrProbation } from "../api/types";
import { Waiting, refusal } from "../components/accounts/shared";
import { DjangoForm, useFormEdits } from "../components/admin/DjangoForm";
import { useHrAllowed } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { LeaveStatusBadge, useLeaveWords } from "../components/leave/shared";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

/** The form that decides one review. Each row has its own, so what was typed for one is not carried to another. */
function Decision({ review, fields, onDone }: { review: number; fields: FormField[]; onDone: () => void }) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const decide = useDecideReview(review);
  const edits = useFormEdits(fields);
  const [errors, setErrors] = useState<FormErrors>({});
  const [problem, setProblem] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    setProblem("");
    decide.mutate(edits.edited, {
      onSuccess: () => {
        push({ level: "success", title: t("اتسجل", "Recorded") });
        onDone();
      },
      onError: (error) => {
        const found = formErrors(error);
        if (found) setErrors(found);
        else setProblem(refusal(error, t("حصلت مشكلة.", "Something went wrong.")));
      },
    });
  };

  return (
    <form className="mt" onSubmit={submit}>
      <DjangoForm fields={fields} edits={edits} errors={errors} prefix={`review${review}`} />
      {problem && (
        <div className="note note--high" role="alert">
          <Icon name="alert" />
          <div>{problem}</div>
        </div>
      )}
      <button className="btn btn--primary btn--sm" type="submit" disabled={decide.isPending || !edits.dirty}>
        <Icon name="check" size="sm" />
        <span>{t("احفظ", "Save")}</span>
      </button>
    </form>
  );
}

function ReviewRow({ row, fields }: { row: HrProbation["rows"][number]; fields: FormField[] }) {
  const { t } = usePreferences();
  const words = useLeaveWords();
  const [open, setOpen] = useState(false);
  return (
    <tr data-review={row.id}>
      <td>
        <Link to={`/hr/employees/${row.user.id}`}>{row.user.name}</Link>
      </td>
      <td>{words(row.stage)}</td>
      <td className={`mono${row.overdue ? " deadline--late" : ""}`}>{row.due_date}</td>
      <td>
        <LeaveStatusBadge status={row.outcome} />
      </td>
      <td className="mono">{row.score !== null ? `${row.score}/10` : "—"}</td>
      <td>
        {row.decided ? (
          <span className="muted">{row.reviewer ?? "—"}</span>
        ) : (
          <>
            <button className="btn btn--sm btn--ghost" type="button" aria-expanded={open} onClick={() => setOpen(!open)}>
              <Icon name="pen" size="sm" />
              <span>{t("قرّر", "Decide")}</span>
            </button>
            {open && <Decision review={row.id} fields={fields} onDone={() => setOpen(false)} />}
          </>
        )}
      </td>
    </tr>
  );
}

/** Who is on probation and which reviews have come due. Only the final review confirms or ends anybody. */
export function HrProbationPage() {
  const { t } = usePreferences();
  const { push } = useToasts();
  const { me, allowed } = useHrAllowed();
  const [params, setParams] = useSearchParams();
  const state = params.get("state") === "due" ? "due" : params.get("state") === "all" ? "all" : "";
  const query = useHrProbation(state, allowed);
  const open = useOpenReviews();
  const data = query.data;

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!data) return <Waiting failed={query.isError} />;

  const openFor = (id: number) =>
    open.mutate(id, {
      onSuccess: (answer) => push({ level: "success", title: t(`${answer.created} مراجعة اتفتحت`, `${answer.created} reviews opened`) }),
      onError: (error) => push({ level: "danger", title: refusal(error, t("حصلت مشكلة.", "Something went wrong.")) }),
    });
  const tab = (value: "" | "due" | "all", ar: string, en: string) => (
    <button
      key={value}
      type="button"
      role="tab"
      aria-selected={state === value}
      className={`tab${state === value ? " is-active" : ""}`}
      onClick={() => setParams(value ? { state: value } : {})}
    >
      {t(ar, en)}
    </button>
  );

  return (
    <>
      <div className="page-head">
        <h1>{t("فترة الاختبار", "Probation")}</h1>
        <div className="grow" />
        <div className="tabs" role="tablist">
          {tab("", "المفتوحة", "Open")}
          {tab("due", "المستحقة", "Due")}
          {tab("all", "الكل", "All")}
        </div>
      </div>

      {data.due_count > 0 && (
        <div className="note note--warn" data-note="due">
          <Icon name="alert" />
          <div>
            <b className="mono">{data.due_count}</b> {t("مراجعة استحقت ولسه مااتقررش فيها.", "reviews have come due and are still undecided.")}
          </div>
        </div>
      )}

      <div className="grid grid--main">
        <div className="card">
          <div className="card__head">
            <Icon name="hand" />
            <h3>{t("المراجعات", "Reviews")}</h3>
          </div>
          <div className="table-wrap">
            <table className="table" data-table="reviews">
              <thead>
                <tr>
                  <th>{t("الموظف", "Employee")}</th>
                  <th>{t("المرحلة", "Stage")}</th>
                  <th>{t("الاستحقاق", "Due")}</th>
                  <th>{t("النتيجة", "Outcome")}</th>
                  <th>{t("التقييم", "Score")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <ReviewRow key={row.id} row={row} fields={data.form} />
                ))}
                {data.rows.length === 0 && (
                  <tr>
                    <td colSpan={6} className="empty">
                      {t("مفيش مراجعات.", "No reviews.")}
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
              <Icon name="users" />
              <h3>{t("تحت الاختبار", "On probation")}</h3>
            </div>
            {data.on_probation.map((person) => (
              <div key={person.id} data-person={person.id}>
                <div className="kv">
                  <span>
                    <Link to={`/hr/employees/${person.id}`}>{person.name}</Link> <span className="muted">{person.department ?? ""}</span>
                  </span>
                  <span className="mono muted">{person.probation_end ?? "—"}</span>
                </div>
                {!person.has_reviews && (
                  <button className="btn btn--sm btn--block" type="button" disabled={open.isPending} onClick={() => openFor(person.id)}>
                    <Icon name="plus" size="sm" />
                    <span>{t("افتح المراجعات", "Open the reviews")}</span>
                  </button>
                )}
              </div>
            ))}
            {data.on_probation.length === 0 && <div className="muted">{t("مفيش حد تحت الاختبار.", "Nobody is on probation.")}</div>}
          </div>

          <div className="note note--info">
            <Icon name="info" />
            <div>
              {t(
                "المراجعات بتتفتح لوحدها وقت التعيين. التثبيت أو الإنهاء من المراجعة النهائية بس.",
                "The three reviews open themselves at hire. Only the final one confirms or ends anybody.",
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
