import { useEffect, useRef, useState } from "react";
import { useAiChat, useSendAiChat } from "../../api/aiChat";
import type { AiChatLine, OpsTask } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { safeInternalPath } from "../../lib/safeUrl";
import { prettySize } from "../../lib/size";
import { taskProblem } from "../../lib/taskProblem";
import { Icon } from "../Icon";
import { Loading } from "../Loading";

/** Kinds the AI can be shown (`ai_translate.readable`), and the most the server takes (`ai_chat.MAX_FILE_BYTES`). */
const ACCEPT = ".png,.jpg,.jpeg,.webp,.gif,.pdf,.docx,.txt,.md,.csv,.json,.srt,.html,.htm";
const FILE_MAX = 10 * 1024 * 1024;
const TEXT_MAX = 4000;

function Attached({ line }: { line: AiChatLine }) {
  const file = line.file;
  if (!file) return null;
  const href = safeInternalPath(file.url);
  if (!href) return <span className="file-pill">{file.name}</span>;
  if (file.image) {
    return (
      <a className="task-thumb" href={href} target="_blank" rel="noopener noreferrer" title={file.name}>
        <img src={href} alt={file.name} loading="lazy" />
      </a>
    );
  }
  return (
    <a className="file-pill" href={href} target="_blank" rel="noopener noreferrer" title={file.size}>
      <Icon name="paperclip" size="sm" />
      {file.name}
    </a>
  );
}

/**
 * The team leader's talk with the AI that has his task (29/10/2026): he writes, optionally with a picture, a PDF or a Word file, and the
 * AI answers from the task's files and its own translation. Nothing is asked first and nothing in the task moves: it is a conversation.
 * The page asks again every few seconds only while an answer is being written.
 */
export function AiChatCard({ task }: { task: OpsTask }) {
  const { t, lang } = usePreferences();
  const enabled = task.lead?.ai_chat === true;
  const chat = useAiChat(task.code, enabled);
  const send = useSendAiChat(task.code);
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [problem, setProblem] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const lines = chat.data?.messages ?? [];
  const writing = chat.data?.pending === true;

  // The newest line is in view as it comes.
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "nearest" });
  }, [lines.length, writing]);

  if (!enabled) return null;

  const ready = (text.trim() !== "" || file !== null) && !send.isPending && !writing;
  const submit = () => {
    if (!ready) return;
    setProblem("");
    send.mutate(
      { text: text.trim(), file },
      {
        onSuccess: () => {
          setText("");
          setFile(null);
        },
        onError: (error) => setProblem(taskProblem(error, t)),
      },
    );
  };

  return (
    <div className="card" data-box="ai-chat" style={{ marginBottom: 14 }}>
      <div className="card__head">
        <Icon name="sparkles" />
        <h3>{t("اتكلم مع الـAI", "Talk to the AI")}</h3>
      </div>
      <small className="muted">
        {t(
          "اسأله ليه اختار كلمة، اطلب صياغة تانية، أو ابعتله صورة أو ملف يبصّ عليه. بيرد من الملفات الأصلية وترجمته. مفيش حاجة في التاسك بتتغيّر من هنا.",
          "Ask why it chose a word, ask for another wording, or send it a picture or file to look at. It answers from the source files and its translation. Nothing on the task changes from here.",
        )}
      </small>

      <div className="aichat__log" role="log" aria-live="polite" data-box="ai-chat-log">
        {chat.isLoading && <Loading className="empty" />}
        {chat.isSuccess && lines.length === 0 && (
          <div className="muted aichat__empty">{t("لسه مفيش كلام. اكتب للـAI.", "Nothing yet. Write to the AI.")}</div>
        )}
        {lines.map((line) => {
          const mine = line.role === "user";
          const at = typeof line.at === "string" ? line.at : lang === "ar" ? line.at.ar : line.at.en;
          return (
            <div key={line.id} className={`aichat__line ${mine ? "aichat__line--me" : "aichat__line--ai"}`} data-line={line.role}>
              {line.status === "pending" && (
                <span className="muted" role="status">
                  {t("الـAI بيكتب...", "The AI is writing...")}
                </span>
              )}
              {line.status === "error" && (
                <span className="aichat__error" role="alert">
                  <Icon name="alert" size="sm" /> {t("الـAI مردّش. ابعت تاني.", "The AI did not answer. Send again.")}
                </span>
              )}
              {line.file && <Attached line={line} />}
              {line.body && (
                <div className="aichat__text" dir="auto">
                  {line.body}
                </div>
              )}
              {line.status !== "pending" && <small className="muted mono">{at}</small>}
            </div>
          );
        })}
        <div ref={end} />
      </div>

      <form
        className="aichat__form"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <textarea
          className="input"
          rows={2}
          maxLength={TEXT_MAX}
          aria-label={t("رسالتك للـAI", "Your message to the AI")}
          placeholder={t("اكتب للـAI...", "Write to the AI...")}
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              submit();
            }
          }}
        />
        <input
          ref={input}
          type="file"
          hidden
          accept={ACCEPT}
          aria-label={t("ملف للـAI", "File for the AI")}
          data-input="ai-chat-file"
          onChange={(event) => {
            const picked = event.target.files?.[0] ?? null;
            event.target.value = "";
            if (!picked) return;
            if (picked.size > FILE_MAX) {
              setProblem(t("الملف أكبر من 10 ميجا.", "The file is over 10 MB."));
              return;
            }
            setProblem("");
            setFile(picked);
          }}
        />
        <div className="row row--tight">
          <button className="btn btn--sm" type="button" onClick={() => input.current?.click()}>
            <Icon name="paperclip" size="sm" />
            <span>{t("ميديا أو ملف", "Media or file")}</span>
          </button>
          {file && (
            <>
              <span dir="auto">{file.name}</span>
              <small className="muted mono">{prettySize(file.size)}</small>
              <button className="btn btn--sm btn--ghost" type="button" aria-label={t("شيل الملف", "Remove the file")} onClick={() => setFile(null)}>
                <Icon name="x" size="sm" />
              </button>
            </>
          )}
          <div className="grow" />
          <button className="btn btn--primary btn--sm" type="submit" disabled={!ready}>
            <Icon name="send" size="sm" />
            <span>{send.isPending || writing ? t("استنى...", "Wait...") : t("ابعت", "Send")}</span>
          </button>
        </div>
        <small className="muted">{t("صورة أو PDF أو Word أو نص، لحد 10 ميجا.", "A picture, PDF, Word or text file, up to 10 MB.")}</small>
        {problem && (
          <div className="note note--high mt" role="alert">
            <Icon name="alert" />
            <div>{problem}</div>
          </div>
        )}
      </form>
    </div>
  );
}
