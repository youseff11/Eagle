import { useState } from "react";
import {
  useAssignTranslator,
  useDecideExtension,
  useFinishReview,
  useSaveTranslatorDeadline,
  useUploadReviewed,
  type TranslatorDate,
} from "../../api/opsActions";
import type { OpsTask } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { prettySize } from "../../lib/size";
import { taskProblem } from "../../lib/taskProblem";
import { Confirm } from "../Confirm";
import { Icon } from "../Icon";
import { useToasts } from "../Toasts";

const EMPTY: TranslatorDate = { days: "", hours: "", minutes: "" };

function Problem({ text }: { text: string }) {
  if (!text) return null;
  return (
    <div className="note note--high mt" role="alert">
      <Icon name="alert" />
      <div>{text}</div>
    </div>
  );
}

/** Days, hours and minutes from now - not a calendar: the question the person is answering is "in how long". */
function Duration({ value, onChange, label }: { value: TranslatorDate; onChange: (next: TranslatorDate) => void; label: string }) {
  const { t } = usePreferences();
  return (
    <div className="dur" role="group" aria-label={label}>
      {(
        [
          ["days", t("يوم", "Days")],
          ["hours", t("ساعة", "Hours")],
          ["minutes", t("دقيقة", "Minutes")],
        ] as const
      ).map(([name, unit]) => (
        <label className="dur__part" key={name}>
          <input
            className="input dur__num"
            type="number"
            min={0}
            step={1}
            inputMode="numeric"
            aria-label={`${label} - ${unit}`}
            value={value[name]}
            onChange={(event) => onChange({ ...value, [name]: event.target.value })}
          />
          <span className="dur__unit">{unit}</span>
        </label>
      ))}
    </div>
  );
}

const typed = (value: TranslatorDate) => value.days.trim() !== "" || value.hours.trim() !== "" || value.minutes.trim() !== "";

/**
 * «ابعتها للمترجم»: the task goes to one translator of the leader's team, who has a minute to say yes. The leader's own
 * date goes with it - shorter than the client's on purpose, the difference being the time the leader keeps to review the
 * work; left empty it is the client's own date. Who is free is said beside the name, so nobody is handed work blind.
 */
export function AssignTranslatorBox({ task }: { task: OpsTask }) {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const assign = useAssignTranslator(task.code);
  const lead = task.lead;
  const [chosen, setChosen] = useState<number | null>(null);
  const [date, setDate] = useState<TranslatorDate>(EMPTY);
  const [problem, setProblem] = useState("");
  if (!lead || !lead.can_assign) return null;

  if (lead.translators.length === 0) {
    return (
      <div className="note note--warn">
        <Icon name="alert" />
        <div>{t("مفيش مترجمين تحتك تبعتلهم التاسك.", "There are no translators in your team to send it to.")}</div>
      </div>
    );
  }
  const translator = chosen ?? lead.translators[0]!.id;
  const word = { free: t("فاضي", "free"), busy: t("مشغول", "busy"), off: t("أوفلاين", "offline") };

  return (
    <>
      <div className="field mt">
        <label htmlFor="translator-select">{t("اعمل assign لمترجم من فريقك", "Assign a translator from your team")}</label>
        <select id="translator-select" className="input" value={translator} onChange={(event) => setChosen(Number(event.target.value))}>
          {lead.translators.map((person) => (
            <option key={person.id} value={person.id}>
              {person.name} — {word[person.state]} · {person.rating.toFixed(2)}
            </option>
          ))}
        </select>
      </div>
      <div className="field" id="translatorDeadline">
        <label>{t("الديدلاين اللي هتديه للمترجم", "The deadline you are giving the translator")}</label>
        <Duration value={date} onChange={setDate} label={t("الديدلاين اللي هتديه للمترجم", "The deadline you are giving the translator")} />
        <small className="muted">
          {t(
            "شيل لنفسك وقت للمراجعة. سيبها فاضية يعني نفس ديدلاين العميل — ومش هيفضلّك وقت تراجع.",
            "Keep yourself some review time. Leave it empty and it is the client's own date, which leaves you none.",
          )}
        </small>
        {lead.client_due && (
          <small className="muted mono" title={t("ديدلاين العميل", "The client's deadline")}>
            <Icon name="clock" size="sm" /> {lang === "ar" ? lead.client_due.ar : lead.client_due.en}
          </small>
        )}
      </div>
      <button
        className="btn btn--primary btn--block"
        type="button"
        disabled={assign.isPending}
        onClick={() => {
          setProblem("");
          assign.mutate(
            { translator, date },
            {
              onSuccess: () => {
                setDate(EMPTY);
                push({ level: "success", title: t("اتبعتت للمترجم", "Sent to the translator") });
              },
              onError: (error) => setProblem(taskProblem(error, t)),
            },
          );
        }}
      >
        <Icon name="send" size="sm" />
        <span>{assign.isPending ? t("بيتبعت...", "Sending...") : t("ابعتها للمترجم", "Send to translator")}</span>
      </button>
      <Problem text={problem} />
    </>
  );
}

/** Changing the translator's date afterwards: without it the leader gets one shot at the moment of handing over. */
export function TranslatorDeadlineBox({ task }: { task: OpsTask }) {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const save = useSaveTranslatorDeadline(task.code);
  const [date, setDate] = useState<TranslatorDate>(EMPTY);
  const [problem, setProblem] = useState("");
  if (!task.lead?.can_set_translator_deadline) return null;

  return (
    <form
      className="mt"
      onSubmit={(event) => {
        event.preventDefault();
        if (!typed(date) || save.isPending) return;
        setProblem("");
        save.mutate(date, {
          onSuccess: () => {
            setDate(EMPTY);
            push({ level: "success", title: t("ديدلاين المترجم اتحفظ", "The translator's deadline was saved") });
          },
          onError: (error) => setProblem(taskProblem(error, t)),
        });
      }}
    >
      <label className="label">{t("ديدلاين المترجم", "The translator's deadline")}</label>
      <Duration value={date} onChange={setDate} label={t("ديدلاين المترجم", "The translator's deadline")} />
      <small className="muted">
        {t(
          "سيبها فاضية يعني سيب الديدلاين زي ما هو. أصفار يعني المترجم يشتغل على ديدلاين العميل.",
          "Leave it empty to keep it. Zeros clear it: the translator then works to the client's date.",
        )}
        {task.translator_due && (
          <span className="mono"> · {lang === "ar" ? task.translator_due.ar : task.translator_due.en}</span>
        )}
      </small>
      <button className="btn btn--block btn--sm mt" type="submit" disabled={!typed(date) || save.isPending}>
        {t("حفظ ديدلاين المترجم", "Save the translator's deadline")}
      </button>
      <Problem text={problem} />
    </form>
  );
}

/** The translator asks for more time and nothing moves before the leader's yes or no (a yes is never past the client's date). */
export function ExtensionBox({ task }: { task: OpsTask }) {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const decide = useDecideExtension(task.code);
  const [declining, setDeclining] = useState(false);
  const [problem, setProblem] = useState("");
  const extension = task.lead?.extension;
  if (!extension || !task.lead) return null;
  const client = task.lead.client_due;

  const answer = (decision: "approve" | "decline") => {
    setProblem("");
    decide.mutate(
      { id: extension.id, decision },
      {
        onSuccess: () => {
          setDeclining(false);
          push({
            level: decision === "approve" ? "success" : "warning",
            title: decision === "approve" ? t("وافقت على الوقت الإضافي", "You approved the extra time") : t("رفضت الوقت الإضافي", "You declined the extra time"),
          });
        },
        onError: (error) => setProblem(taskProblem(error, t)),
      },
    );
  };

  return (
    <>
      <div className="note note--warn mt">
        <Icon name="timer" />
        <div>
          <strong>{t("المترجم طالب وقت إضافي", "The translator asks for more time")}</strong>
          <div>
            {extension.length}
            {extension.reason ? ` — ${extension.reason}` : ""}
          </div>
          <div className="muted mono">
            <span>{t("ديدلاينه هيبقى", "Their deadline becomes")}</span> {extension.new_due ? (lang === "ar" ? extension.new_due.ar : extension.new_due.en) : "—"}
            {client && (
              <>
                {" · "}
                <span>{t("العميل", "Client")}</span> {lang === "ar" ? client.ar : client.en}
              </>
            )}
          </div>
        </div>
      </div>
      <div className="row row--tight mt">
        <button className="btn btn--ok btn--sm grow" type="button" disabled={decide.isPending} onClick={() => answer("approve")}>
          <Icon name="check" size="sm" />
          <span>{t("موافق", "Approve")}</span>
        </button>
        <button
          className="btn btn--danger btn--sm grow"
          type="button"
          disabled={decide.isPending}
          onClick={() => {
            setProblem("");
            setDeclining(true);
          }}
        >
          <Icon name="x" size="sm" />
          <span>{t("رفض", "Decline")}</span>
        </button>
      </div>
      <Problem text={problem} />
      {declining && (
        <Confirm
          title={t("ترفض الوقت الإضافي؟", "Decline the extra time?")}
          yes={t("أيوه، ارفض", "Yes, decline")}
          danger
          busy={decide.isPending}
          problem={problem}
          onNo={() => setDeclining(false)}
          onYes={() => answer("decline")}
        />
      )}
    </>
  );
}

/**
 * The file the leader corrected. The review sends on what is put here; with nothing put, it sends the translator's own file, and the box
 * says which of the two it will be. Put after the review, it goes to the operation at once and replaces what they were given.
 */
export function ReviewedFilesBox({ task }: { task: OpsTask }) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const upload = useUploadReviewed(task.code);
  const [chosen, setChosen] = useState<File[]>([]);
  const [problem, setProblem] = useState("");
  if (!task.lead?.can_upload_reviewed) return null;
  const reviewed = task.files.reviewed ?? [];
  const late = !task.lead.can_review;

  const send = () => {
    if (chosen.length === 0 || upload.isPending) return;
    setProblem("");
    upload.mutate(chosen, {
      onSuccess: () => {
        setChosen([]);
        push({
          level: "success",
          title: late ? t("اتبعتت للأوبريشن بدل اللي قبلها", "Sent to the operation in place of the first") : t("اتحفظت. هتروح مع المراجعة", "Saved. It goes with the review"),
        });
      },
      onError: (error) => setProblem(taskProblem(error, t)),
    });
  };

  return (
    <div className="field mt" data-box="reviewed-files">
      <label htmlFor="reviewed-files">{t("الملف اللي ظبطته", "The file you corrected")}</label>
      <input
        id="reviewed-files"
        className="input"
        type="file"
        multiple
        onChange={(event) => {
          setChosen(Array.from(event.target.files ?? []));
          event.target.value = "";
        }}
      />
      {chosen.length > 0 && (
        <ul className="muted" style={{ margin: "6px 0", paddingInlineStart: 18 }}>
          {chosen.map((file, index) => (
            <li key={`${file.name}-${index}`}>
              {file.name} <span className="mono">{prettySize(file.size)}</span>
            </li>
          ))}
        </ul>
      )}
      <button className="btn btn--block btn--sm mt" type="button" disabled={chosen.length === 0 || upload.isPending} onClick={send}>
        <Icon name="upload" size="sm" />
        <span>{upload.isPending ? t("بيترفع...", "Uploading...") : late ? t("ابعت الملف المعدّل للأوبريشن", "Send the corrected file to the operation") : t("احفظ الملف المعدّل", "Save the corrected file")}</span>
      </button>
      <small className="muted">
        {reviewed.length > 0
          ? t(`هيتبعت للأوبريشن ملفك (${reviewed.length}) مش ملف المترجم.`, `The operation gets your file (${reviewed.length}), not the translator's.`)
          : t("لو ماحطيتش ملف، هيتبعت للأوبريشن ملف المترجم زي ما هو.", "With none put here, the operation gets the translator's file as it is.")}
      </small>
      {reviewed.length > 0 && (
        <ul className="muted" style={{ margin: "6px 0 0", paddingInlineStart: 18 }}>
          {reviewed.map((file) => (
            <li key={file.id}>{file.name}</li>
          ))}
        </ul>
      )}
      <Problem text={problem} />
    </div>
  );
}

/** «تمت المراجعة»: the review is done and the task goes on to the operation. Asked first: it cannot be taken back from here. */
export function ReviewButton({ task }: { task: OpsTask }) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const finish = useFinishReview(task.code);
  const [asking, setAsking] = useState(false);
  const [problem, setProblem] = useState("");
  if (!task.lead?.can_review) return null;

  return (
    <>
      <button
        className="btn btn--ok btn--block mt"
        type="button"
        onClick={() => {
          setProblem("");
          setAsking(true);
        }}
      >
        <Icon name="check-circle" size="sm" />
        <span>{t("تمت المراجعة", "Review completed")}</span>
      </button>
      {asking && (
        <Confirm
          title={t("تأكيد إن المراجعة خلصت؟", "Confirm the review is done?")}
          yes={t("أيوه، خلصت", "Yes, it is done")}
          icon="check-circle"
          busy={finish.isPending}
          problem={problem}
          onNo={() => setAsking(false)}
          onYes={() =>
            finish.mutate(undefined, {
              onSuccess: () => {
                setAsking(false);
                push({ level: "success", title: t("المراجعة خلصت", "Review completed") });
              },
              onError: (error) => setProblem(taskProblem(error, t)),
            })
          }
        />
      )}
    </>
  );
}
