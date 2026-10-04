import { useRef, useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router";
import { formErrors } from "../api/adminActions";
import { ApiError } from "../api/client";
import { useMarkTest } from "../api/hrActions";
import { useReviewerTest } from "../api/queries";
import type { FormErrors } from "../api/types";
import { Waiting, refusal } from "../components/accounts/shared";
import { DjangoForm, useFormEdits } from "../components/admin/DjangoForm";
import { FileChip, useReviewerAllowed, useStamp } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

/**
 * Marking one test. A reviewer reads the candidate as a code: the page says so, and the server sends no name, phone, salary or
 * vacancy, and a plain word for the candidate's file. The owner, who may read who it is, sees the name. Each mark is out of ten;
 * the total is the system's.
 */
export function ReviewerTestPage() {
  const { t } = usePreferences();
  const stamp = useStamp();
  const { push } = useToasts();
  const navigate = useNavigate();
  const { me, allowed } = useReviewerAllowed();
  const id = Number(useParams().id);
  const query = useReviewerTest(id, allowed);
  const mark = useMarkTest(id);
  const data = query.data;
  const edits = useFormEdits(data?.form);
  const [errors, setErrors] = useState<FormErrors>({});
  const [problem, setProblem] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const picker = useRef<HTMLInputElement>(null);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (query.error instanceof ApiError && query.error.status === 404) {
    return (
      <div className="card empty" role="alert">
        <span>{t("الصفحة دي مش موجودة.", "That page does not exist.")}</span>
      </div>
    );
  }
  if (!data) return <Waiting failed={query.isError} />;
  const test = data.test;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    setProblem("");
    mark.mutate(
      { values: edits.edited, file },
      {
        onSuccess: () => {
          edits.reset();
          setFile(null);
          push({ level: "success", title: t("التقييم اتسجل", "The score was saved") });
          navigate("/reviewer/tests");
        },
        onError: (error) => {
          const found = formErrors(error);
          if (found) setErrors(found);
          else if (error instanceof ApiError && error.code === "bad_file") {
            setProblem(t("الملف فاضي أو أكبر من الحد (20 ميجا).", "The file is empty or over the limit (20 MB)."));
          } else setProblem(refusal(error, t("حصلت مشكلة، ماتحفظش.", "Something went wrong, nothing was saved.")));
        },
      },
    );
  };

  return (
    <>
      <div className="page-head">
        <h1>{data.blind ? <span className="mono">{data.candidate.code}</span> : (data.candidate.name ?? data.candidate.code)}</h1>
        {!data.blind && <span className="mono muted">{data.candidate.code}</span>}
        <span className="muted">{test.title || "—"}</span>
      </div>

      {data.blind && (
        <div className="note note--info" data-note="blind">
          <Icon name="shield" />
          <div>
            {t(
              "بتشوف الشغل بس — بيانات المرشح وراتبه المتوقع مش من صلاحية المراجع.",
              "You see the work only. The candidate's name, details and expected salary are not a reviewer's business.",
            )}
          </div>
        </div>
      )}

      <div className="grid grid--main">
        <div className="card" data-card="marks">
          <div className="card__head">
            <Icon name="check-circle" />
            <h3>{t("التقييم", "Evaluation")}</h3>
            <div className="grow" />
            <span className="muted">{t("كل بند من 10", "Each out of 10")}</span>
          </div>
          <form onSubmit={submit}>
            <div className="field" data-field="submission">
              <label htmlFor="mark-submission">{t("ملف تسليم المرشح", "The candidate's submission")}</label>
              {test.submission && <FileChip file={test.submission} />}
              <input id="mark-submission" ref={picker} className="input" type="file" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
            </div>
            <DjangoForm fields={data.form} edits={edits} errors={errors} prefix="mark" />
            {problem && (
              <div className="note note--high" role="alert">
                <Icon name="alert" />
                <div>{problem}</div>
              </div>
            )}
            <button className="btn btn--primary btn--block mt" type="submit" disabled={mark.isPending || (!edits.dirty && !file)}>
              <Icon name="check" size="sm" />
              <span>{t("احفظ التقييم", "Save")}</span>
            </button>
          </form>
        </div>

        <div className="sticky-side">
          <div className="card card--flat" data-card="test">
            <div className="card__head">
              <Icon name="file" />
              <h3>{t("الاختبار", "The test")}</h3>
            </div>
            <div className="kv">
              <span>{t("زوج اللغات", "Language pair")}</span>
              <b className="mono">{test.language_pair || "—"}</b>
            </div>
            <div className="kv">
              <span>{t("عدد الكلمات", "Word count")}</span>
              <b className="mono">{test.word_count}</b>
            </div>
            <div className="kv">
              <span>{t("آخر موعد", "Deadline")}</span>
              <b className="mono">{stamp(test.deadline)}</b>
            </div>
            {test.assignment && (
              <div className="mt">
                <FileChip file={test.assignment} />
              </div>
            )}
            {test.brief && <p className="muted mt">{test.brief}</p>}
          </div>
          <div className="card" data-card="total">
            <div className="kpi">
              <div className="kpi__label">{t("الإجمالي", "Total")}</div>
              <div className="kpi__value mono">
                {test.total} / {test.max}
              </div>
            </div>
            <Link className="btn btn--sm btn--ghost btn--block mt" to="/reviewer/tests">
              <Icon name="arrow-right" size="sm" />
              <span>{t("ارجع للقايمة", "Back to the queue")}</span>
            </Link>
          </div>
        </div>
      </div>
    </>
  );
}
