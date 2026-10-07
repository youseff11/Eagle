import { useState } from "react";
import {
  useAssignTranslator,
  useDecideExtension,
  useFinishReview,
  useSaveTranslatorDeadline,
  useUploadReviewed,
  type DeadlineChoice,
  type TranslatorDate,
} from "../../api/opsActions";
import type { OpsTask } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { prettySize } from "../../lib/size";
import { taskProblem } from "../../lib/taskProblem";
import { Confirm } from "../Confirm";
import { Countdown } from "../Countdown";
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

/** How long a typed duration is, in seconds (what is not a whole number counts as nothing: the server says why when it is sent). */
const seconds = (value: TranslatorDate) => {
  const part = (raw: string) => (/^\d+$/.test(raw.trim()) ? Number(raw.trim()) : 0);
  return part(value.days) * 86400 + part(value.hours) * 3600 + part(value.minutes) * 60;
};

/**
 * «ابعتها للمترجم»: the task goes to one translator of the leader's team, who has a minute to say yes. The leader is handed the operation's
 * deadline and the time left, and CHOOSES what the translator gets: the same deadline, or a shorter one (the difference being the time
 * he keeps to review). Nothing is chosen for him - the send waits for the answer - and a shorter one has to be written and has to be
 * shorter than what is left. Who is free is said beside the name, so nobody is handed work blind.
 */
export function AssignTranslatorBox({ task }: { task: OpsTask }) {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const assign = useAssignTranslator(task.code);
  const lead = task.lead;
  const [chosen, setChosen] = useState<number | null>(null);
  const [choice, setChoice] = useState<DeadlineChoice | null>(null);
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

  // What is left of the operation's deadline, and whether the shorter one typed is really shorter (the server asks the same).
  const left = task.due_iso ? Math.floor((Date.parse(task.due_iso) - Date.now()) / 1000) : null;
  const typedLength = seconds(date);
  const tooLong = left !== null && typedLength >= left;
  const ready = choice === "same" || (choice === "shorter" && typed(date) && typedLength > 0 && !tooLong);

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

      <fieldset className="field" id="translatorDeadline" style={{ border: 0, padding: 0 }}>
        <legend className="label">{t("الديدلاين اللي هتديه للمترجم", "The deadline you are giving the translator")}</legend>
        <div className="muted mono" title={t("الديدلاين اللي حدده الأوبريشن", "The deadline the operation gave")}>
          <Icon name="clock" size="sm" /> {lead.client_due ? (lang === "ar" ? lead.client_due.ar : lead.client_due.en) : t("من غير ديدلاين", "No deadline")}
        </div>
        <Countdown iso={task.due_iso} state={task.due_state} />
        <label className="row row--tight mt">
          <input type="radio" name="translator-deadline-choice" value="same" checked={choice === "same"} onChange={() => setChoice("same")} />
          <span>{t("نفس ديدلاين الأوبريشن", "The same as the operation's deadline")}</span>
        </label>
        <label className="row row--tight">
          <input type="radio" name="translator-deadline-choice" value="shorter" checked={choice === "shorter"} onChange={() => setChoice("shorter")} />
          <span>{t("ديدلاين أقل", "A shorter deadline")}</span>
        </label>
        {choice === "shorter" && (
          <>
            <Duration value={date} onChange={setDate} label={t("الديدلاين الأقل - من دلوقتي", "The shorter deadline - from now")} />
            <small className="muted">
              {t(
                "اكتب بعد قد إيه من دلوقتي المترجم يسلّم. لازم يكون أقل من الوقت الباقي، والفرق هو وقت المراجعة بتاعك.",
                "Type how long from now the translator has. It has to be less than the time left; the difference is your review time.",
              )}
            </small>
            {tooLong && (
              <small className="note note--high" role="alert">
                {t("لازم يكون أقل من الوقت الباقي على ديدلاين الأوبريشن.", "It has to be less than the time left on the operation's deadline.")}
              </small>
            )}
          </>
        )}
        {choice === null && (
          <small className="muted">{t("اختار الأول: نفس الديدلاين ولا أقل.", "Choose first: the same deadline, or a shorter one.")}</small>
        )}
      </fieldset>

      <button
        className="btn btn--primary btn--block"
        type="button"
        disabled={assign.isPending || !ready}
        onClick={() => {
          if (choice === null) return;
          setProblem("");
          assign.mutate(
            { translator, choice, date },
            {
              onSuccess: () => {
                setDate(EMPTY);
                setChoice(null);
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
