import { useState, type FormEvent } from "react";
import { Link, Navigate, useParams } from "react-router";
import { formErrors } from "../api/adminActions";
import { ApiError } from "../api/client";
import { useScoreInterview } from "../api/hrActions";
import { useHrInterview } from "../api/queries";
import type { FormErrors } from "../api/types";
import { Waiting, refusal } from "../components/accounts/shared";
import { DjangoForm, useFormEdits } from "../components/admin/DjangoForm";
import { useHrAllowed, useStamp } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { useLeaveWords } from "../components/leave/shared";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

/** The five marks, each out of ten, and a comment. The total is the system's: there is no box to type it in. */
export function HrInterviewPage() {
  const { t } = usePreferences();
  const words = useLeaveWords();
  const stamp = useStamp();
  const { push } = useToasts();
  const { me, allowed } = useHrAllowed();
  const id = Number(useParams().id);
  const query = useHrInterview(id, allowed);
  const save = useScoreInterview(id);
  const data = query.data;
  const edits = useFormEdits(data?.form);
  const [errors, setErrors] = useState<FormErrors>({});
  const [problem, setProblem] = useState("");

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (query.error instanceof ApiError && query.error.status === 404) {
    return (
      <div className="card empty" role="alert">
        <span>{t("الصفحة دي مش موجودة.", "That page does not exist.")}</span>
      </div>
    );
  }
  if (!data) return <Waiting failed={query.isError} />;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    setProblem("");
    save.mutate(edits.edited, {
      onSuccess: () => {
        edits.reset();
        push({ level: "success", title: t("التقييم اتسجل", "The score was saved") });
      },
      onError: (error) => {
        const found = formErrors(error);
        if (found) setErrors(found);
        else setProblem(refusal(error, t("حصلت مشكلة، ماتحفظش.", "Something went wrong, nothing was saved.")));
      },
    });
  };
  const row = data.interview;

  return (
    <>
      <div className="page-head">
        <h1>{data.candidate.name}</h1>
        <span className="mono muted">
          {stamp(row.at)} · {words(row.kind)}
        </span>
      </div>

      <div className="grid grid--main">
        <div className="card" data-card="scores">
          <div className="card__head">
            <Icon name="star" />
            <h3>{t("الدرجات", "Scores")}</h3>
            <div className="grow" />
            <span className="muted">{t("كل بند من 10", "Each out of 10")}</span>
          </div>
          <form onSubmit={submit}>
            <DjangoForm fields={data.form} edits={edits} errors={errors} prefix="score" />
            {problem && (
              <div className="note note--high" role="alert">
                <Icon name="alert" />
                <div>{problem}</div>
              </div>
            )}
            <button className="btn btn--primary btn--block mt" type="submit" disabled={save.isPending || !edits.dirty}>
              <Icon name="check" size="sm" />
              <span>{t("احفظ التقييم", "Save")}</span>
            </button>
            <small className="muted">{t("الإجمالي بيتحسب من النظام — مفيش خانة تكتبه فيها.", "The total is the system's; there is no box to type it in.")}</small>
          </form>
        </div>

        <div className="sticky-side">
          <div className="card" data-card="total">
            <div className="card__head">
              <Icon name="chart" />
              <h3>{t("الإجمالي", "Total")}</h3>
            </div>
            <div className="kpi">
              <div className="kpi__label">{t("الدرجة الحالية", "Current score")}</div>
              <div className="kpi__value mono">
                {row.total} / {row.max}
              </div>
            </div>
            <Link className="btn btn--sm btn--ghost btn--block mt" to={`/hr/candidates/${data.candidate.code}`}>
              <Icon name="arrow-right" size="sm" />
              <span>{t("ارجع للمرشح", "Back to the candidate")}</span>
            </Link>
          </div>
          {(row.meeting_link || row.location || row.notes) && (
            <div className="card card--flat" data-card="meeting">
              {row.meeting_link && (
                <div className="kv">
                  <span>{t("لينك الاجتماع", "Meeting link")}</span>
                  <b className="mono" dir="ltr">
                    {row.meeting_link}
                  </b>
                </div>
              )}
              {row.location && (
                <div className="kv">
                  <span>{t("المكان", "Location")}</span>
                  <b>{row.location}</b>
                </div>
              )}
              {row.notes && <p className="muted">{row.notes}</p>}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
