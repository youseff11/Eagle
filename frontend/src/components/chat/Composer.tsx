import { useEffect, useLayoutEffect, useRef, useState, type ChangeEvent, type FormEvent, type KeyboardEvent } from "react";
import { useFileTasks } from "../../api/queries";
import type { MeResponse } from "../../api/types";
import { useVoiceRecorder } from "../../hooks/useVoiceRecorder";
import { usePreferences } from "../../i18n/Preferences";
import type { ReplyTarget } from "../../lib/outbox";
import type { Recorded } from "../../lib/recorder";
import { prettySize } from "../../lib/size";
import { Icon } from "../Icon";
import { VoiceBar } from "./VoiceBar";

/** What was typed and attached in each conversation and not sent: kept while the person looks at another one, never longer than the page. */
interface Unsent {
  text: string;
  files: File[];
}
const drafts = new Map<string, Unsent>();

/** Forget every unsent draft (a test starts from nothing). */
export function forgetDrafts(): void {
  drafts.clear();
}

const MAX_HEIGHT = 140;

/**
 * The limits, until the server says (`me.limits`): the longest message (WhatsApp cuts a text at 4000 characters,
 * silently; a client group adds the sender's role in front, which counts) and the files in one message.
 */
export const DEFAULT_LIMITS: MeResponse["limits"] = {
  to_client: 4000,
  to_client_group: 3987,
  inside: 10000,
  files: { count: 10, bytes: 95 * 1024 * 1024, total_bytes: 95 * 1024 * 1024 },
  voice: { seconds: 300, bytes: 15 * 1024 * 1024 },
};

/** What is wrong with these files, if anything: too many, one too big, or all together too big. */
export function filesProblem(files: File[], limits: MeResponse["limits"]["files"]): "" | "count" | "big" | "total" {
  if (files.length > limits.count) return "count";
  if (files.some((file) => file.size > limits.bytes)) return "big";
  if (files.reduce((sum, file) => sum + file.size, 0) > limits.total_bytes) return "total";
  return "";
}

/**
 * What is sent from the box: the words, the files, the task the files are for (`none`, a code, or nothing), and a voice
 * note. A voice note goes by itself (with the words typed beside it): the files that are attached wait for their own send.
 */
export interface Written {
  body: string;
  files: File[];
  task: string;
  voice: Recorded | null;
}

/**
 * Where a message is written (chat slices 3b and 3c: words, replies and files; voice comes with its own step).
 *
 * Enter sends, Shift+Enter is a new line, and neither does anything while an input method is still composing.
 * Escape drops the reply that was chosen. One message at a time is on its way (`busy`): it keeps what the
 * person writes in order, and a second tap cannot send the same words twice. When WhatsApp's 24-hour window
 * is closed (`closed`) the box is off and says why - the server would only be told "no" by Meta.
 *
 * Files are chosen with the clip and shown as chips that can be taken off. In a work group or a chat with a
 * colleague they have to say which task they are for (`pickTasks`): a wrong guess once put a translation on
 * the wrong task, so with several to choose from the person is asked and the send waits for the answer.
 */
export function Composer({
  code,
  toClient,
  pickTasks,
  limit,
  fileLimits,
  voiceLimits,
  reply,
  onClearReply,
  closed,
  busy,
  onSend,
}: {
  code: string;
  /** What is written here reaches a client's phone. */
  toClient: boolean;
  /** Files sent here are asked which task they are for (a work group, a colleague). */
  pickTasks: boolean;
  /** The most characters one message may have here (what the server allows this person in this conversation). */
  limit: number;
  fileLimits: MeResponse["limits"]["files"];
  voiceLimits: MeResponse["limits"]["voice"];
  reply: ReplyTarget | null;
  onClearReply: () => void;
  closed: boolean;
  busy: boolean;
  onSend: (written: Written) => void;
}) {
  const { t } = usePreferences();
  const [text, setText] = useState(() => drafts.get(code)?.text ?? "");
  const [files, setFiles] = useState<File[]>(() => drafts.get(code)?.files ?? []);
  const [task, setTask] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);
  const voice = useVoiceRecorder(voiceLimits.seconds);

  // The box grows with what is typed, up to a limit, then scrolls. An empty box takes the height the style gives
  // it: measuring the placeholder (which wraps in a narrow column) froze a tall box while the layout settled.
  useLayoutEffect(() => {
    const node = box.current;
    if (!node) return;
    if (text === "") {
      node.style.height = "";
      return;
    }
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, MAX_HEIGHT)}px`;
  }, [text]);

  // Choosing a message to answer puts the cursor back in the box.
  useEffect(() => {
    if (reply) box.current?.focus();
  }, [reply]);

  const remember = (nextText: string, nextFiles: File[]) => {
    if (nextText === "" && nextFiles.length === 0) drafts.delete(code);
    else drafts.set(code, { text: nextText, files: nextFiles });
  };

  const body = text.trim();
  const over = body.length > limit;
  const problem = filesProblem(files, fileLimits);

  // Which task: asked once there are files, in the places where files must say. One choice is preselected; several
  // have to be chosen (and the send waits); "not for a task" is always allowed.
  const wantsTask = pickTasks && files.length > 0;
  const tasks = useFileTasks(code, wantsTask);
  const choices = wantsTask ? (tasks.data?.tasks ?? []) : [];
  const chosen = task !== "" ? task : choices.length === 1 ? choices[0]!.code : "";
  const mustChoose = wantsTask && choices.length > 1 && chosen === "";
  const waiting = wantsTask && tasks.isPending;

  const hasContent = body !== "" || files.length > 0;
  const ready = hasContent && !busy && !closed && !over && problem === "" && !mustChoose && !waiting;

  const changeText = (value: string) => {
    setText(value);
    remember(value, files);
  };

  const pick = (event: ChangeEvent<HTMLInputElement>) => {
    const chosenFiles = Array.from(event.target.files ?? []);
    // Choosing the same file again must still fire: the input forgets what it held.
    event.target.value = "";
    if (chosenFiles.length === 0) return;
    const next = [...files, ...chosenFiles];
    setFiles(next);
    remember(text, next);
  };

  const dropFile = (index: number) => {
    const next = files.filter((_file, position) => position !== index);
    setFiles(next);
    if (next.length === 0) setTask("");
    remember(text, next);
  };

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (!ready) return;
    onSend({ body, files, task: wantsTask && choices.length > 0 ? chosen : "", voice: null });
    setText("");
    setFiles([]);
    setTask("");
    remember("", []);
  };

  // The take is sent with the words typed beside it, and the files that are attached stay for their own send.
  const sendVoice = () => {
    if (!voice.recorded || busy || closed || over) return;
    onSend({ body, files: [], task: "", voice: voice.recorded });
    setText("");
    remember("", files);
    voice.discard();
  };

  const keys = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Escape" && reply) {
      onClearReply();
    } else if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  const placeholder = closed
    ? t("نافذة الـ24 ساعة قفلت: مينفعش تبعت دلوقتي.", "The 24-hour window is closed: you cannot send now.")
    : toClient
      ? t("اكتب رسالتك للعميل...", "Write your reply to the client...")
      : t("اكتب رسالة...", "Write a message...");

  const megabytes = (bytes: number) => Math.round(bytes / (1024 * 1024));
  const problemText = {
    count: t(`الحد الأقصى ${fileLimits.count} ملفات في الرسالة.`, `At most ${fileLimits.count} files in a message.`),
    big: t(
      `فيه ملف أكبر من ${megabytes(fileLimits.bytes)} ميجا: شيله.`,
      `A file is bigger than ${megabytes(fileLimits.bytes)} MB: take it off.`,
    ),
    total: t(
      `الملفات مع بعض أكبر من ${megabytes(fileLimits.total_bytes)} ميجا.`,
      `The files together are bigger than ${megabytes(fileLimits.total_bytes)} MB.`,
    ),
  };

  return (
    <>
      {reply && (
        <div className="cchat__replybar">
          <Icon name="reply" size="sm" />
          <div className="cchat__replybar-body">
            <b>{reply.who}</b>
            <span>{reply.text}</span>
          </div>
          <button
            type="button"
            className="icon-btn"
            onClick={onClearReply}
            title={t("إلغاء الرد", "Cancel the reply")}
            aria-label={t("إلغاء الرد", "Cancel the reply")}
          >
            <Icon name="x" size="sm" />
          </button>
        </div>
      )}
      {body.length > limit * 0.9 && (
        <div className={`cchat__count mono${over ? " is-over" : ""}`} role={over ? "alert" : undefined}>
          {body.length} / {limit}
          {over && (
            <span>
              {" "}
              {toClient
                ? t("— قصّرها: واتساب مش هيوصّل أكتر من كده.", "— shorten it: WhatsApp will not carry more than that.")
                : t("— قصّرها.", "— shorten it.")}
            </span>
          )}
        </div>
      )}
      {wantsTask && choices.length > 0 && (
        <div className={`cchat__pickbar cchat__filetask${mustChoose ? " is-missing" : ""}`}>
          <Icon name="layers" size="sm" />
          <span>{t("الملفات دي تبع:", "These files are for:")}</span>
          <select
            className="input cchat__pickday"
            value={chosen}
            onChange={(event) => setTask(event.target.value)}
            aria-label={t("التاسك", "Task")}
          >
            {choices.length > 1 && <option value="">{t("اختار التاسك...", "Pick the task...")}</option>}
            {choices.map((choice) => (
              <option key={choice.code} value={choice.code}>
                {choice.code} · {choice.title.length > 30 ? `${choice.title.slice(0, 29)}…` : choice.title}
              </option>
            ))}
            <option value="none">{t("مش تبع تاسك", "Not for a task")}</option>
          </select>
        </div>
      )}
      <form className="cchat__composer" onSubmit={submit} autoComplete="off">
        <label className="icon-btn" title={t("ملف", "File")}>
          <Icon name="paperclip" />
          <input
            type="file"
            multiple
            hidden
            disabled={closed}
            aria-label={t("إرفاق ملفات", "Attach files")}
            onChange={pick}
          />
        </label>
        <button
          type="button"
          id="micBtn"
          className={`icon-btn${voice.phase === "recording" ? " is-live" : ""}`}
          disabled={closed || voice.phase !== "idle"}
          onClick={voice.start}
          title={t("سجّل رسالة صوتية", "Record a voice note")}
          aria-label={t("سجّل رسالة صوتية", "Record a voice note")}
        >
          <Icon name="mic" />
        </button>
        <textarea
          ref={box}
          className="input grow cchat__input"
          rows={1}
          value={text}
          disabled={closed}
          placeholder={placeholder}
          aria-label={t("الرسالة", "Message")}
          onChange={(event) => changeText(event.target.value)}
          onKeyDown={keys}
        />
        <button className="btn btn--primary" type="submit" id="chatSend" disabled={!ready}>
          <Icon name="send" size="sm" />
          <span>{t("إرسال", "Send")}</span>
        </button>
      </form>
      <VoiceBar voice={voice} busy={busy || closed || over} maxBytes={voiceLimits.bytes} onSend={sendVoice} />
      {files.length > 0 && (
        <div className="cchat__files">
          {files.map((file, index) => (
            <span className="chip" key={`${file.name}-${index}`}>
              <Icon name="paperclip" size="sm" />
              {file.name}
              <span className="muted mono">{prettySize(file.size)}</span>
              <button
                type="button"
                aria-label={t(`شيل ${file.name}`, `Remove ${file.name}`)}
                onClick={() => dropFile(index)}
              >
                <Icon name="x" size="sm" />
              </button>
            </span>
          ))}
        </div>
      )}
      {wantsTask && tasks.isError && (
        <div className="cchat__count is-over" role="alert">
          {t(
            "مش قادرين نجيب التاسكات اللي الملفات ممكن تبعها. حدّث المحادثة وجرّب تاني.",
            "Could not load the tasks the files could be for. Reload the conversation and try again.",
          )}
        </div>
      )}
      {problem !== "" && (
        <div className="cchat__count is-over" role="alert">
          {problemText[problem]}
        </div>
      )}
    </>
  );
}
