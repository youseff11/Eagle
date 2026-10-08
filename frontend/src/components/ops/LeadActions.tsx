import { useState } from "react";
import {
  useAssignTranslator,
  useCloseTranslation,
  useDecideExtension,
  useFinishReview,
  useSavePartWords,
  useSaveTranslatorDeadline,
  useUploadReviewed,
  type DeadlineChoice,
  type TranslatorDate,
} from "../../api/opsActions";
import type { OpsPart, OpsTask } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { MAX_PARTS, rowProblems, wordsTyped, type PartRow } from "../../lib/parts";
import { prettySize } from "../../lib/size";
import { taskProblem } from "../../lib/taskProblem";
import { Confirm } from "../Confirm";
import { Countdown } from "../Countdown";
import { Icon } from "../Icon";
import { pagesOf } from "../PartBox";
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

/** Keys for the rows the leader adds; the first row of an untouched form is key 0. */
let nextKey = 1;
const freshRow = (key: number, translator: number | null): PartRow => ({ key, translator, from: "", to: "" });

/**
 * «ابعتها للمترجم»: the task goes to one translator of the leader's team - or to several, each with their own share - and each has a minute
 * to say yes. The language pair is the task's own (the operation said it, and it is only read here: with none said the send waits for the
 * operation); the words are not asked now - the leader writes them for each translator when the translation comes back for review. With
 * more than one translator on the task he says which pages, so nobody translates the same page twice. The leader is handed the
 * operation's deadline and the time left, and CHOOSES what the translators get: the same deadline, or a shorter one (the difference being
 * the time he keeps to review). Nothing is chosen for him - the send waits for the answer. Who is free is said beside the name, so nobody
 * is handed work blind. A task already being translated takes one more share without touching the others.
 */
export function AssignTranslatorBox({ task }: { task: OpsTask }) {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const assign = useAssignTranslator(task.code);
  const lead = task.lead;
  const [rows, setRows] = useState<PartRow[] | null>(null);
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

  // The shares already taken stay; the offers nobody has answered yet are replaced by what goes out now.
  const taken = task.parts.filter((part) => part.status === "accepted");
  const waiting = task.parts.filter((part) => part.status === "pending");
  const takenIds = new Set(taken.map((part) => part.translator));
  const available = lead.translators.filter((person) => !takenIds.has(person.id));
  if (available.length === 0) return null;

  const names = new Map(lead.translators.map((person) => [person.id, person.name]));
  // The pair is the operation's: until it is said the task cannot go out, and the leader is told whose it is to say.
  const pair = task.source_lang.trim() !== "" && task.target_lang.trim() !== "";
  // Until the leader touches anything the form is one row with a key of its own that does not change between draws.
  const current = rows ?? [freshRow(0, available[0]!.id)];
  const problems = rowProblems(
    current,
    taken.map((part) => ({ name: part.name, page_from: part.page_from, page_to: part.page_to })),
    names,
    t,
  );
  const word = { free: t("فاضي", "free"), busy: t("مشغول", "busy"), off: t("أوفلاين", "offline") };
  const edit = (key: number, change: Partial<PartRow>) => setRows(current.map((row) => (row.key === key ? { ...row, ...change } : row)));
  const many = taken.length + current.length > 1;

  // What is left of the operation's deadline, and whether the shorter one typed is really shorter (the server asks the same).
  const left = task.due_iso ? Math.floor((Date.parse(task.due_iso) - Date.now()) / 1000) : null;
  const typedLength = seconds(date);
  const tooLong = left !== null && typedLength >= left;
  const dateReady = choice === "same" || (choice === "shorter" && typed(date) && typedLength > 0 && !tooLong);
  const ready = pair && dateReady && problems.every((text) => text === "");

  return (
    <>
      {pair ? (
        <div className="kv" data-box="task-pair">
          <span>{t("الترجمة", "Translation")}</span>
          <strong className="mono" dir="ltr">
            {task.source_lang} → {task.target_lang}
          </strong>
        </div>
      ) : (
        <div className="note note--warn" role="alert" data-box="task-pair-missing">
          <Icon name="alert" />
          <div>
            {t(
              "الأوبريشن لسه ماحددش لغة الترجمة (من لغة وإلى لغة) على التاسك دي. قوله يحددها وبعدين وزّعها.",
              "The operation has not said the language pair (from and to) on this task yet. Ask them to, then hand it out.",
            )}
          </div>
        </div>
      )}
      {taken.length > 0 && (
        <div className="note note--info mt">
          <Icon name="info" />
          <div>
            {t(
              "فيه مترجمين شغالين على التاسك دي. اللي هتبعته دلوقتي بيتضاف عليهم من غير ما يتأثروا.",
              "Translators are already on this task. What you send now is added to them, and they are not touched.",
            )}
          </div>
        </div>
      )}
      {waiting.length > 0 && (
        <div className="note note--warn mt">
          <Icon name="timer" />
          <div>
            {t(
              "فيه عروض لسه ماتردش عليها. الإرسال الجديد بيلغيها ويحط الجديد مكانها.",
              "Some offers have not been answered. Sending again cancels them and puts the new ones in their place.",
            )}
          </div>
        </div>
      )}

      {current.map((row, index) => (
        <fieldset className="card card--flat mt" key={row.key} data-part={index} style={{ padding: "10px 12px" }}>
          <legend className="label">
            {t("المترجم", "Translator")} {taken.length + index + 1}
          </legend>
          <div className="field">
            <label htmlFor={`part-translator-${row.key}`}>{t("اعمل assign لمترجم من فريقك", "Assign a translator from your team")}</label>
            <select
              id={`part-translator-${row.key}`}
              className="input"
              value={row.translator ?? ""}
              onChange={(event) => edit(row.key, { translator: Number(event.target.value) })}
            >
              {available.map((person) => (
                <option key={person.id} value={person.id}>
                  {person.name} — {word[person.state]} · {person.rating.toFixed(2)}
                </option>
              ))}
            </select>
          </div>
          <div className="row row--tight" style={{ flexWrap: "wrap" }}>
            <div className="field grow">
              <label htmlFor={`part-from-${row.key}`}>
                {t("من صفحة", "From page")} {!many && <small className="muted">({t("اختياري", "optional")})</small>}
              </label>
              <input
                id={`part-from-${row.key}`}
                className="input"
                dir="ltr"
                inputMode="numeric"
                placeholder="1"
                value={row.from}
                onChange={(event) => edit(row.key, { from: event.target.value })}
              />
            </div>
            <div className="field grow">
              <label htmlFor={`part-to-${row.key}`}>{t("لحد صفحة", "To page")}</label>
              <input
                id={`part-to-${row.key}`}
                className="input"
                dir="ltr"
                inputMode="numeric"
                placeholder="10"
                value={row.to}
                onChange={(event) => edit(row.key, { to: event.target.value })}
              />
            </div>
          </div>
          {problems[index] && (
            <small className="note note--high" role="alert">
              {problems[index]}
            </small>
          )}
          {current.length > 1 && (
            <button className="btn btn--sm btn--ghost mt" type="button" onClick={() => setRows(current.filter((one) => one.key !== row.key))}>
              <Icon name="x" size="sm" />
              <span>{t("شيل المترجم ده", "Remove this translator")}</span>
            </button>
          )}
        </fieldset>
      ))}

      <button
        className="btn btn--sm mt"
        type="button"
        disabled={current.length >= Math.min(MAX_PARTS, available.length)}
        onClick={() => {
          const used = new Set(current.map((row) => row.translator));
          const next = available.find((person) => !used.has(person.id));
          if (next) setRows([...current, freshRow(nextKey++, next.id)]);
        }}
      >
        <Icon name="plus" size="sm" />
        <span>{t("إضافة مترجم تاني على نفس التاسك", "Add another translator to this task")}</span>
      </button>

      <fieldset className="field" id="translatorDeadline" style={{ border: 0, padding: 0 }}>
        <legend className="label">{t("الديدلاين اللي هتديه للمترجمين", "The deadline you are giving the translators")}</legend>
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
          if (choice === null || !ready) return;
          setProblem("");
          assign.mutate(
            {
              parts: current.map((row) => ({
                translator: row.translator as number,
                page_from: row.from.trim(),
                page_to: row.to.trim(),
              })),
              choice,
              date,
            },
            {
              onSuccess: () => {
                setDate(EMPTY);
                setChoice(null);
                setRows(null);
                push({
                  level: "success",
                  title: current.length > 1 ? t("اتبعتت للمترجمين", "Sent to the translators") : t("اتبعتت للمترجم", "Sent to the translator"),
                });
              },
              onError: (error) => setProblem(taskProblem(error, t)),
            },
          );
        }}
      >
        <Icon name="send" size="sm" />
        <span>
          {assign.isPending
            ? t("بيتبعت...", "Sending...")
            : current.length > 1
              ? t("ابعتها للمترجمين", "Send to the translators")
              : t("ابعتها للمترجم", "Send to translator")}
        </span>
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
          <strong>
            {extension.by
              ? t(`${extension.by} طالب وقت إضافي`, `${extension.by} asks for more time`)
              : t("المترجم طالب وقت إضافي", "The translator asks for more time")}
          </strong>
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

/**
 * «اقفل الترجمة»: a share fell through after the other translators had handed theirs in, and the leader is not giving it to anybody
 * else. Nobody is left who can hand in, so he closes the translation himself and reviews what there is. Asked first: it cannot be taken
 * back from here, and the part that fell through is not in the files.
 */
export function CloseTranslationButton({ task }: { task: OpsTask }) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const close = useCloseTranslation(task.code);
  const [asking, setAsking] = useState(false);
  const [problem, setProblem] = useState("");
  if (!task.lead?.can_close_translation) return null;

  return (
    <>
      <div className="note note--warn mt">
        <Icon name="alert" />
        <div>
          {t(
            "الكل سلّم وفيه جزء اترفض أو الوقت خلص عليه. وزّعه على مترجم تاني من فوق، أو اقفل الترجمة وراجع اللي اتسلّم.",
            "Everyone has handed in and one share fell through. Give it to another translator above, or close the translation and review what was handed in.",
          )}
        </div>
      </div>
      <button
        className="btn btn--block mt"
        type="button"
        onClick={() => {
          setProblem("");
          setAsking(true);
        }}
      >
        <Icon name="check" size="sm" />
        <span>{t("اقفل الترجمة وراجع اللي اتسلّم", "Close the translation and review what was handed in")}</span>
      </button>
      {asking && (
        <Confirm
          title={t("تقفل الترجمة من غير الجزء الناقص؟", "Close the translation without the missing part?")}
          yes={t("أيوه، اقفلها", "Yes, close it")}
          icon="check"
          busy={close.isPending}
          problem={problem}
          onNo={() => setAsking(false)}
          onYes={() =>
            close.mutate(undefined, {
              onSuccess: () => {
                setAsking(false);
                push({ level: "success", title: t("الترجمة اتقفلت وبقت عندك للمراجعة", "The translation is closed and with you for review") });
              },
              onError: (error) => setProblem(taskProblem(error, t)),
            })
          }
        />
      )}
    </>
  );
}

/** The shares a translator took: the ones the leader writes words for (an offer nobody answered has nothing to count). */
const takenShares = (task: OpsTask) => task.parts.filter((part) => part.status === "accepted");

/**
 * «عدد كلمات كل مترجم»: the team leader writes how many words each translator translated, while the translation is with him for review
 * (08/10/2026). It is the number the translator's month is counted from, and the review cannot be finished without it. The operation's
 * own count for the whole task is shown beside, for him to compare - it is not put in the boxes for him.
 */
export function PartWordsBox({ task }: { task: OpsTask }) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const save = useSavePartWords(task.code);
  const [typed, setTyped] = useState<Record<number, string>>({});
  const [problem, setProblem] = useState("");
  if (!task.lead?.can_set_part_words) return null;
  const shares = takenShares(task);
  if (shares.length === 0) return null;

  const value = (part: OpsPart) => typed[part.id] ?? (part.words > 0 ? String(part.words) : "");
  const numbers = shares.map((part) => wordsTyped(value(part)));
  const ready = numbers.every((number) => number !== null);
  const saved = shares.every((part) => part.words > 0) && Object.keys(typed).length === 0;
  const operation = task.words.state === "confirmed" ? task.words.value : null;

  return (
    <form
      className="mt"
      data-box="part-words"
      onSubmit={(event) => {
        event.preventDefault();
        if (!ready || save.isPending) return;
        setProblem("");
        save.mutate(
          shares.map((part, index) => ({ id: part.id, words: numbers[index] as number })),
          {
            onSuccess: () => {
              setTyped({});
              push({ level: "success", title: t("عدد الكلمات اتسجّل", "The words were saved") });
            },
            onError: (error) => setProblem(taskProblem(error, t)),
          },
        );
      }}
    >
      <div className="row row--tight">
        <label className="label grow">{t("عدد كلمات كل مترجم", "Each translator's words")}</label>
        {saved ? <span className="badge badge--ok">{t("متسجّل", "Set")}</span> : <span className="badge badge--wait">{t("لسه", "Not yet")}</span>}
      </div>
      {shares.map((part) => {
        const pages = pagesOf(part);
        return (
          <div className="field" key={part.id} data-part-words={part.id}>
            <label htmlFor={`part-words-${part.id}`}>
              {part.name}
              {pages && <small className="muted mono"> · {t("صفحات", "pages")} {pages}</small>}
            </label>
            <input
              id={`part-words-${part.id}`}
              className="input"
              dir="ltr"
              inputMode="numeric"
              placeholder="1200"
              value={value(part)}
              onChange={(event) => setTyped({ ...typed, [part.id]: event.target.value })}
            />
          </div>
        );
      })}
      <small className="muted">
        {t(
          "اكتب كام كلمة ترجم كل واحد. الحسابات بتحسب إنتاجه من الرقم ده، ومش هتقدر تخلّص المراجعة من غيره.",
          "Write how many words each one translated. Their production is counted from it, and the review cannot be finished without it.",
        )}
        {operation !== null && (
          <span className="mono"> · {t(`الأوبريشن كاتب ${operation} كلمة للتاسك كله`, `the operation wrote ${operation} words for the whole task`)}</span>
        )}
      </small>
      <button className="btn btn--block btn--sm mt" type="submit" disabled={!ready || save.isPending || saved}>
        {t("حفظ عدد الكلمات", "Save the words")}
      </button>
      <Problem text={problem} />
    </form>
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
  // The words of every translator come first: the server refuses a review without them, and says so here before it is pressed.
  const waitingForWords = task.lead.can_set_part_words === true && takenShares(task).some((part) => part.words === 0);

  return (
    <>
      {waitingForWords && (
        <div className="note note--warn mt" data-box="words-first">
          <Icon name="alert" />
          <div>{t("اكتب عدد كلمات كل مترجم واحفظه الأول، وبعدين خلّص المراجعة.", "Write and save each translator's words first, then finish the review.")}</div>
        </div>
      )}
      <button
        className="btn btn--ok btn--block mt"
        type="button"
        disabled={waitingForWords}
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
