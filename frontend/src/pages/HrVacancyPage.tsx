import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useParams } from "react-router";
import { formErrors } from "../api/adminActions";
import { ApiError } from "../api/client";
import { useAddVacancyQuestion, useOrderVacancyQuestions, useRemoveVacancyQuestion, useSaveVacancy } from "../api/hrActions";
import { useHrVacancy } from "../api/queries";
import type { FormErrors } from "../api/types";
import { Waiting, refusal } from "../components/accounts/shared";
import { DjangoForm, useFormEdits } from "../components/admin/DjangoForm";
import { useHrAllowed } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { LeaveStatusBadge, useLeaveWords } from "../components/leave/shared";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";
import { CandidateRows } from "./HrRecruitmentPage";

interface Row {
  id: number;
  order: number;
  required: boolean;
}

/**
 * One vacancy: the questions the bot will ask for it, in exactly the order HR gives, and who applied. The questions are HR's to
 * choose: a department only helps find one. The deadline is left alone unless a number of days is written in it.
 */
export function HrVacancyPage() {
  const { t } = usePreferences();
  const words = useLeaveWords();
  const { push } = useToasts();
  const { me, allowed } = useHrAllowed();
  const params = useParams();
  const code = params.code ?? "";
  const query = useHrVacancy(code, allowed);
  const save = useSaveVacancy(code);
  const add = useAddVacancyQuestion(code);
  const order = useOrderVacancyQuestions(code);
  const remove = useRemoveVacancyQuestion();
  const data = query.data;
  const edits = useFormEdits(data?.form);
  const [errors, setErrors] = useState<FormErrors>({});
  const [problem, setProblem] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [pick, setPick] = useState("");
  const links = data?.links;
  useEffect(() => {
    setRows((links ?? []).map((one) => ({ id: one.id, order: one.order, required: one.required })));
  }, [links]);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (query.error instanceof ApiError && query.error.status === 404) {
    return (
      <div className="card empty" role="alert">
        <span>{t("الصفحة دي مش موجودة.", "That page does not exist.")}</span>
      </div>
    );
  }
  if (!data) return <Waiting failed={query.isError} />;

  const mine = (id: number) => rows.find((row) => row.id === id) ?? { id, order: 0, required: true };
  const change = (id: number, patch: Partial<Row>) => setRows((previous) => previous.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  const fail = (error: unknown) => push({ level: "danger", title: refusal(error, t("حصلت مشكلة.", "Something went wrong.")) });
  const chosen = pick || String(data.pool[0]?.id ?? "");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    setProblem("");
    save.mutate(edits.edited, {
      onSuccess: () => {
        edits.reset();
        push({ level: "success", title: t("اتحفظت", "Saved") });
      },
      onError: (error) => {
        const found = formErrors(error);
        if (found) setErrors(found);
        else setProblem(refusal(error, t("حصلت مشكلة، ماتحفظتش.", "Something went wrong, nothing was saved.")));
      },
    });
  };

  return (
    <>
      <div className="page-head">
        <h1>{data.vacancy.title}</h1>
        <span className="mono muted">{data.vacancy.code}</span>
        <LeaveStatusBadge status={data.vacancy.status} />
        <div className="grow" />
        <span className="chip mono">
          {data.vacancy.applicants} {t("متقدم", "applicants")}
        </span>
      </div>

      <div className="grid grid--main">
        <div className="stack">
          <div className="card" data-card="questions">
            <div className="card__head">
              <Icon name="list-checks" />
              <h3>{t("أسئلة البوت للوظيفة دي", "The bot's questions")}</h3>
              <div className="grow" />
              <span className="muted">{t("بالترتيب ده بالظبط", "In exactly this order")}</span>
            </div>
            {data.links.length === 0 && (
              <div className="note note--warn" data-note="no-questions">
                <Icon name="alert" />
                <div>{t("مفيش أسئلة متختارة — البوت هيسأل عن الشيفت بس ويحوّل للـHR.", "No questions selected: the bot will only ask about the shift and hand over.")}</div>
              </div>
            )}
            <div className="table-wrap">
              <table className="table" data-table="links">
                <thead>
                  <tr>
                    <th>{t("الترتيب", "Order")}</th>
                    <th>{t("السؤال", "Question")}</th>
                    <th>{t("النوع", "Type")}</th>
                    <th>{t("بيملا", "Fills")}</th>
                    <th>{t("إجباري", "Required")}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.links.map((link) => (
                    <tr key={link.id} data-link={link.id}>
                      <td>
                        <input
                          className="input"
                          type="number"
                          min={1}
                          style={{ width: "5rem" }}
                          aria-label={t("الترتيب", "Order")}
                          value={mine(link.id).order}
                          onChange={(event) => change(link.id, { order: Number(event.target.value) })}
                        />
                      </td>
                      <td>{link.question.text}</td>
                      <td className="muted">{words(link.question.kind)}</td>
                      <td className="muted mono">{link.question.maps_to ? words(link.question.maps_to) : "—"}</td>
                      <td>
                        <input
                          type="checkbox"
                          aria-label={t("إجباري", "Required")}
                          checked={mine(link.id).required}
                          onChange={(event) => change(link.id, { required: event.target.checked })}
                        />
                      </td>
                      <td>
                        <button
                          className="btn btn--sm btn--ghost"
                          type="button"
                          aria-label={t("شيل السؤال", "Remove the question")}
                          disabled={remove.isPending}
                          onClick={() => remove.mutate(link.id, { onError: fail })}
                        >
                          <Icon name="trash" size="sm" />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {data.links.length === 0 && (
                    <tr>
                      <td colSpan={6} className="empty">
                        {t("ضيف أسئلة من القايمة جنبها.", "Add questions from the list beside this.")}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            {data.links.length > 0 && (
              <button
                className="btn btn--primary mt"
                type="button"
                disabled={order.isPending}
                onClick={() =>
                  order.mutate(rows, {
                    onSuccess: () => push({ level: "success", title: t("اتحفظ الترتيب", "The order was saved") }),
                    onError: fail,
                  })
                }
              >
                <Icon name="check" size="sm" />
                <span>{t("احفظ الترتيب", "Save the order")}</span>
              </button>
            )}
          </div>

          <div className="card">
            <div className="card__head">
              <Icon name="contact" />
              <h3>{t("المتقدمين", "Applicants")}</h3>
            </div>
            <CandidateRows rows={data.candidates} empty={t("مفيش متقدمين لسه.", "No applicants yet.")} />
          </div>
        </div>

        <div className="sticky-side">
          <div className="card" data-card="add">
            <div className="card__head">
              <Icon name="plus" />
              <h3>{t("ضيف سؤال", "Add a question")}</h3>
            </div>
            <div className="field">
              <select className="input" aria-label={t("السؤال", "Question")} value={chosen} onChange={(event) => setPick(event.target.value)}>
                {data.pool.map((one) => (
                  <option key={one.id} value={one.id}>
                    [{one.department ?? t("عام", "General")}] {one.text}
                  </option>
                ))}
                {data.pool.length === 0 && (
                  <option value="" disabled>
                    {t("مفيش أسئلة متاحة", "No questions available")}
                  </option>
                )}
              </select>
            </div>
            <button
              className="btn btn--block"
              type="button"
              disabled={add.isPending || !chosen}
              onClick={() => add.mutate(Number(chosen), { onSuccess: () => setPick(""), onError: fail })}
            >
              <Icon name="plus" size="sm" />
              <span>{t("ضيف", "Add")}</span>
            </button>
            <Link className="btn btn--sm btn--ghost btn--block mt" to="/hr/questions">
              <Icon name="list-checks" size="sm" />
              <span>{t("بنك الأسئلة", "Question bank")}</span>
            </Link>
          </div>

          <div className="card" data-card="details">
            <div className="card__head">
              <Icon name="sliders" />
              <h3>{t("بيانات الوظيفة", "Vacancy details")}</h3>
            </div>
            <form onSubmit={submit}>
              <DjangoForm fields={data.form} edits={edits} errors={errors} prefix="vacancy" />
              {problem && (
                <div className="note note--high" role="alert">
                  <Icon name="alert" />
                  <div>{problem}</div>
                </div>
              )}
              <button className="btn btn--primary btn--block" type="submit" disabled={save.isPending || !edits.dirty}>
                <Icon name="check" size="sm" />
                <span>{t("احفظ", "Save")}</span>
              </button>
            </form>
          </div>
        </div>
      </div>
    </>
  );
}
