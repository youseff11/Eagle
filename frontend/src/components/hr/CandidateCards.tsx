import { useRef, useState, type FormEvent } from "react";
import { formErrors } from "../../api/adminActions";
import { ApiError } from "../../api/client";
import {
  useBookInterview,
  useMessageCandidate,
  useMoveCandidate,
  useRevealCandidate,
  useSaveCandidate,
  useSetCandidateTest,
  useUploadCv,
} from "../../api/hrActions";
import type { FormErrors, HrCandidate } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { refusal } from "../accounts/shared";
import { DjangoForm, useFormEdits } from "../admin/DjangoForm";
import { Icon } from "../Icon";
import { useLeaveWords } from "../leave/shared";
import { useToasts } from "../Toasts";
import { FileChip, useStamp } from "./shared";

type Props = { data: HrCandidate };

function Problem({ text }: { text: string }) {
  if (!text) return null;
  return (
    <div className="note note--high" role="alert">
      <Icon name="alert" />
      <div>{text}</div>
    </div>
  );
}

/** Where the candidate may go from here: only what the pipeline allows. A move to the owner's queue tells the owner. */
export function StatusCard({ data }: Props) {
  const { t } = usePreferences();
  const words = useLeaveWords();
  const { push } = useToasts();
  const code = data.candidate.code;
  const move = useMoveCandidate(code);
  const [pick, setPick] = useState("");
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState("");
  const chosen = pick || data.next_statuses[0]?.value || "";

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setProblem("");
    move.mutate(
      { status: chosen, reason: reason.trim() },
      {
        onSuccess: () => {
          setPick("");
          setReason("");
          push({ level: "success", title: t("اتغيرت الحالة", "The status changed") });
        },
        onError: (error) => setProblem(refusal(error, t("النقلة دي مش متاحة.", "That move is not available."))),
      },
    );
  };

  return (
    <div className="card" data-card="status">
      <div className="card__head">
        <Icon name="arrow-right" />
        <h3>{t("الحالة", "Status")}</h3>
      </div>
      {data.next_statuses.length > 0 ? (
        <form onSubmit={submit}>
          <div className="field">
            <select className="input" aria-label={t("الحالة الجديدة", "New status")} value={chosen} onChange={(event) => setPick(event.target.value)}>
              {data.next_statuses.map((one) => (
                <option key={one.value} value={one.value}>
                  {words(one)}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <input
              className="input"
              type="text"
              aria-label={t("سبب أو ملاحظة", "Reason or note")}
              placeholder={t("سبب أو ملاحظة", "Reason or note")}
              maxLength={250}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </div>
          <Problem text={problem} />
          <button className="btn btn--primary btn--block" type="submit" disabled={move.isPending || !chosen}>
            <Icon name="arrow-right" size="sm" />
            <span>{t("انقل", "Move")}</span>
          </button>
        </form>
      ) : (
        <div className="muted" data-note="no-move">
          {t("مفيش نقلة متاحة من الحالة دي.", "No move is available from here.")}
        </div>
      )}
      {data.candidate.status.value === "owner_approval" && (
        <div className="note note--warn mt" data-note="owner">
          <Icon name="user-check" />
          <div>{t("مستني قرار المالك — التعيين مش بيحصل تلقائي.", "Waiting for the owner. Hiring is never automatic.")}</div>
        </div>
      )}
      {data.candidate.status.value === "rejected" && data.candidate.rejection_reason && (
        <div className="note note--info mt" data-note="rejected">
          <Icon name="info" />
          <div>{data.candidate.rejection_reason}</div>
        </div>
      )}
    </div>
  );
}

/** The company's name is kept from this candidate until HR says otherwise. Saying so is logged, and cannot be taken back. */
export function IdentityCard({ data }: Props) {
  const { t } = usePreferences();
  const stamp = useStamp();
  const { push } = useToasts();
  const reveal = useRevealCandidate(data.candidate.code);
  const [reason, setReason] = useState("");
  const [sure, setSure] = useState(false);
  const [problem, setProblem] = useState("");
  const identity = data.candidate.identity;

  const go = () => {
    setProblem("");
    reveal.mutate(reason.trim(), {
      onSuccess: () => {
        setSure(false);
        setReason("");
        push({ level: "success", title: t("الهوية اتكشفت للمرشح ده", "The company was revealed to this candidate") });
      },
      onError: (error) => setProblem(refusal(error, t("حصلت مشكلة.", "Something went wrong."))),
    });
  };

  return (
    <div className="card" data-card="identity">
      <div className="card__head">
        <Icon name="shield" />
        <h3>{t("هوية الشركة", "Company identity")}</h3>
      </div>
      {identity.revealed ? (
        <>
          <div className="kv">
            <span>{t("اتكشفت", "Revealed")}</span>
            <b className="mono">{stamp(identity.at)}</b>
          </div>
          <div className="kv">
            <span>{t("مين كشفها", "By")}</span>
            <b>{identity.by ?? "—"}</b>
          </div>
        </>
      ) : (
        <>
          <p className="muted">
            {t(
              "كل رسالة بتروح للمرشح ده بيتشال منها اسم الشركة تلقائيًا. الزرار ده بيوقف ده، ومتسجل في سجل النشاط، ومابيترجعش.",
              "Every message to this candidate is scrubbed of the company's names. This stops that; it is logged and cannot be taken back.",
            )}
          </p>
          <div className="field">
            <input
              className="input"
              type="text"
              aria-label={t("السبب (اختياري)", "Reason (optional)")}
              placeholder={t("السبب (اختياري)", "Reason (optional)")}
              maxLength={250}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </div>
          <Problem text={problem} />
          {sure ? (
            <div className="row row--tight">
              <button className="btn btn--danger grow" type="button" disabled={reveal.isPending} onClick={go}>
                <Icon name="eye" size="sm" />
                <span>{t("أيوه، اكشف", "Yes, reveal")}</span>
              </button>
              <button className="btn btn--ghost" type="button" onClick={() => setSure(false)}>
                {t("لأ", "No")}
              </button>
            </div>
          ) : (
            <button className="btn btn--danger btn--block" type="button" onClick={() => setSure(true)}>
              <Icon name="eye" size="sm" />
              <span>{t("اكشف الهوية", "Reveal")}</span>
            </button>
          )}
        </>
      )}
    </div>
  );
}

/** A message to the candidate. The server sends it from the recruitment number, through the identity filter, and nothing else does. */
export function MessageCard({ data }: Props) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const send = useMessageCandidate(data.candidate.code);
  const [body, setBody] = useState("");
  const [problem, setProblem] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setProblem("");
    send.mutate(body.trim(), {
      onSuccess: () => {
        setBody("");
        push({ level: "success", title: t("الرسالة اتبعتت", "The message was sent") });
      },
      onError: (error) => {
        const found = formErrors(error);
        if (found?.body) setProblem(found.body.join(" "));
        else if (error instanceof ApiError && error.code === "no_recruit_line") {
          setProblem(t("رقم التوظيف مش متسجل، فالرسالة ماتبعتتش.", "No recruitment number is set, so the message was not sent."));
        } else if (error instanceof ApiError && error.code === "no_phone") {
          setProblem(t("المرشح ده مالوش رقم موبايل.", "This candidate has no phone number."));
        } else setProblem(refusal(error, t("مابعتتش.", "It was not sent.")));
      },
    });
  };

  return (
    <div className="card" data-card="message">
      <div className="card__head">
        <Icon name="send" />
        <h3>{t("ابعتله رسالة", "Message the candidate")}</h3>
      </div>
      <form onSubmit={submit}>
        <div className="field">
          <textarea
            className="input"
            rows={3}
            aria-label={t("الرسالة", "Message")}
            maxLength={4000}
            value={body}
            onChange={(event) => setBody(event.target.value)}
          />
        </div>
        {!data.line_ready && (
          <div className="note note--warn" data-note="no-line">
            <Icon name="alert" />
            <div>
              {t(
                "رقم التوظيف مش متسجل — الرسالة كانت هتروح من رقم العملاء، فمش هتتبعت. سجّله من إعدادات التوظيف.",
                "No recruitment number is set: a message would go out on the client number, so it is not sent. Set it in the recruitment settings.",
              )}
            </div>
          </div>
        )}
        <Problem text={problem} />
        <button className="btn btn--block" type="submit" disabled={send.isPending || !body.trim() || !data.line_ready}>
          <Icon name="send" size="sm" />
          <span>{t("ابعت", "Send")}</span>
        </button>
        <small className="muted">
          {t("بتروح من رقم التوظيف وبتعدي على نفس فلتر إخفاء الهوية.", "Goes out from the recruitment number, through the same identity filter.")}
        </small>
      </form>
    </div>
  );
}

/** Book an interview. */
export function InterviewCard({ data }: Props) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const book = useBookInterview(data.candidate.code);
  const edits = useFormEdits(data.interview_form);
  const [errors, setErrors] = useState<FormErrors>({});
  const [problem, setProblem] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    setProblem("");
    book.mutate(edits.edited, {
      onSuccess: () => {
        edits.reset();
        push({ level: "success", title: t("المقابلة اتسجلت", "The interview was booked") });
      },
      onError: (error) => {
        const found = formErrors(error);
        if (found) setErrors(found);
        else setProblem(refusal(error, t("حصلت مشكلة.", "Something went wrong.")));
      },
    });
  };

  return (
    <div className="card" data-card="interview-new">
      <div className="card__head">
        <Icon name="calendar" />
        <h3>{t("حدّد مقابلة", "Schedule an interview")}</h3>
      </div>
      <form onSubmit={submit}>
        <DjangoForm fields={data.interview_form} edits={edits} errors={errors} prefix="interview" />
        <Problem text={problem} />
        <button className="btn btn--block mt" type="submit" disabled={book.isPending || !edits.dirty}>
          <Icon name="plus" size="sm" />
          <span>{t("سجّل", "Add")}</span>
        </button>
      </form>
    </div>
  );
}

/** Set a test: the form, how long the candidate gets, and the file if there is one. */
export function TestCard({ data }: Props) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const set = useSetCandidateTest(data.candidate.code);
  const edits = useFormEdits(data.test_form);
  const [errors, setErrors] = useState<FormErrors>({});
  const [problem, setProblem] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const picker = useRef<HTMLInputElement>(null);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    setProblem("");
    set.mutate(
      { values: edits.edited, file },
      {
        onSuccess: () => {
          edits.reset();
          setFile(null);
          if (picker.current) picker.current.value = "";
          push({ level: "success", title: t("الاختبار اتسجل", "The test was set") });
        },
        onError: (error) => {
          const found = formErrors(error);
          if (found) setErrors(found);
          else setProblem(refusal(error, t("حصلت مشكلة.", "Something went wrong.")));
        },
      },
    );
  };

  return (
    <div className="card" data-card="test-new">
      <div className="card__head">
        <Icon name="file" />
        <h3>{t("اضبط اختبار", "Set a test")}</h3>
      </div>
      <form onSubmit={submit}>
        <DjangoForm fields={data.test_form} edits={edits} errors={errors} prefix="test" />
        <div className="field mt">
          <label htmlFor="test-file">{t("ملف الاختبار", "Test file")}</label>
          <input id="test-file" ref={picker} className="input" type="file" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
        </div>
        <Problem text={problem} />
        <button className="btn btn--block" type="submit" disabled={set.isPending || (!edits.dirty && !file)}>
          <Icon name="plus" size="sm" />
          <span>{t("سجّل", "Add")}</span>
        </button>
      </form>
    </div>
  );
}

/** The profile as HR corrects it, and the CV (which is a file, so it has a button of its own). */
export function ProfileCard({ data }: Props) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const save = useSaveCandidate(data.candidate.code);
  const upload = useUploadCv(data.candidate.code);
  const edits = useFormEdits(data.form);
  const [errors, setErrors] = useState<FormErrors>({});
  const [problem, setProblem] = useState("");
  const [cvProblem, setCvProblem] = useState("");
  const picker = useRef<HTMLInputElement>(null);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    setProblem("");
    save.mutate(edits.edited, {
      onSuccess: () => {
        edits.reset();
        push({ level: "success", title: t("اتحفظ", "Saved") });
      },
      onError: (error) => {
        const found = formErrors(error);
        if (found) setErrors(found);
        else setProblem(refusal(error, t("حصلت مشكلة، ماتحفظش.", "Something went wrong, nothing was saved.")));
      },
    });
  };
  const send = (file: File | undefined) => {
    if (!file) return;
    setCvProblem("");
    upload.mutate(file, {
      onSuccess: () => push({ level: "success", title: t("الـCV اتحفظ", "The CV was saved") }),
      onError: (error) =>
        setCvProblem(
          error instanceof ApiError && error.code === "bad_file"
            ? t("الملف فاضي أو أكبر من الحد (20 ميجا).", "The file is empty or over the limit (20 MB).")
            : refusal(error, t("الـCV ماتحفظش.", "The CV was not saved.")),
        ),
    });
    if (picker.current) picker.current.value = "";
  };

  return (
    <div className="card" data-card="profile">
      <div className="card__head">
        <Icon name="contact" />
        <h3>{t("ملف المرشح", "Candidate profile")}</h3>
      </div>
      <form onSubmit={submit}>
        <DjangoForm fields={data.form} edits={edits} errors={errors} prefix="profile" />
        <Problem text={problem} />
        <button className="btn btn--primary btn--block mt" type="submit" disabled={save.isPending || !edits.dirty}>
          <Icon name="check" size="sm" />
          <span>{t("احفظ", "Save")}</span>
        </button>
      </form>
      <div className="field mt" data-field="cv">
        <label htmlFor="cv-file">{t("الـCV", "CV")}</label>
        {data.candidate.cv && <FileChip file={data.candidate.cv} />}
        <input id="cv-file" ref={picker} className="input" type="file" disabled={upload.isPending} onChange={(event) => send(event.target.files?.[0])} />
        <Problem text={cvProblem} />
      </div>
    </div>
  );
}
