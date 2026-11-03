import { useRef, useState, type DragEvent } from "react";
import type { AiReviewLabel } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { prettySize } from "../../lib/size";
import { Icon } from "../Icon";

/** What the server can read: Word and text it turns into words, PDFs and pictures the model reads itself (`doc_review`). */
const ACCEPT = ".docx,.doc,.txt,.md,.csv,.tsv,.json,.srt,.vtt,.html,.htm,.pdf,.png,.jpg,.jpeg,.webp,.gif";

export interface PendingFile {
  file: File;
  label: AiReviewLabel;
}

/**
 * The box a line to the AI is written in: words, and any number of files, each with what the leader says it is (the source, the
 * translation, or nothing - the AI works that out). Files are dropped on it or chosen. It holds nothing itself: the page owns the
 * draft, so it survives a move to another session.
 */
export function ReviewComposer({
  text,
  files,
  limits,
  disabled,
  sending,
  note,
  problem,
  onText,
  onFiles,
  onSend,
}: {
  text: string;
  files: PendingFile[];
  limits: { files: number; megabytes: number; message_megabytes: number; text: number };
  /** Nothing can be sent now: the AI is off, or it is still answering in this session. */
  disabled: boolean;
  sending: boolean;
  /** Why it is disabled, in words. */
  note: string;
  problem: string;
  onText: (text: string) => void;
  onFiles: (files: PendingFile[]) => void;
  onSend: () => void;
}) {
  const { t } = usePreferences();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [warn, setWarn] = useState("");

  const add = (incoming: File[]) => {
    const fits = incoming.filter((file) => file.size <= limits.megabytes * 1024 * 1024);
    const tooBig = incoming.length - fits.length;
    const room = limits.files - files.length;
    // The whole line has a size too (what one upload may carry): files go in while they fit it.
    let total = files.reduce((sum, one) => sum + one.file.size, 0);
    const kept: File[] = [];
    let overTotal = 0;
    for (const file of fits.slice(0, Math.max(0, room))) {
      if (total + file.size > limits.message_megabytes * 1024 * 1024) overTotal += 1;
      else {
        total += file.size;
        kept.push(file);
      }
    }
    setWarn(
      tooBig > 0
        ? t(`فيه ${tooBig} ملف أكبر من ${limits.megabytes} ميجا ومااتضافش.`, `${tooBig} file(s) over ${limits.megabytes} MB were not added.`)
        : overTotal > 0
          ? t(
              `الملفات في الرسالة الواحدة لحد ${limits.message_megabytes} ميجا. ${overTotal} ملف ماااتضافش، ابعتهم في رسالة تانية.`,
              `A message carries up to ${limits.message_megabytes} MB of files. ${overTotal} file(s) were not added: send them in another message.`,
            )
          : fits.length > Math.max(0, room)
            ? t(`أقصى عدد ${limits.files} ملف في الرسالة.`, `At most ${limits.files} files in a message.`)
            : "",
    );
    onFiles([...files, ...kept.map((file) => ({ file, label: "other" as const }))]);
  };
  const drop = (event: DragEvent) => {
    event.preventDefault();
    setOver(false);
    if (!disabled) add(Array.from(event.dataTransfer.files));
  };
  const ready = !disabled && !sending && (text.trim() !== "" || files.length > 0);

  return (
    <form
      className={`revchat__form${over ? " is-over" : ""}`}
      data-box="review-composer"
      onSubmit={(event) => {
        event.preventDefault();
        if (ready) onSend();
      }}
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={drop}
    >
      {note && (
        <div className="note note--info" role="status">
          <Icon name="info" />
          <div>{note}</div>
        </div>
      )}
      {files.length > 0 && (
        <ul className="revchat__pending">
          {files.map((one, index) => (
            <li key={`${one.file.name}-${index}`}>
              <Icon name="file" size="sm" />
              <span className="revchat__pending-name" dir="auto">
                {one.file.name}
              </span>
              <small className="muted mono">{prettySize(one.file.size)}</small>
              <select
                className="input revchat__label"
                aria-label={t(`إيه ${one.file.name}؟`, `What is ${one.file.name}?`)}
                value={one.label}
                disabled={sending}
                onChange={(event) => onFiles(files.map((other, at) => (at === index ? { ...other, label: event.target.value as AiReviewLabel } : other)))}
              >
                <option value="other">{t("الـAI يحدد", "AI decides")}</option>
                <option value="source">{t("الأصل", "Source")}</option>
                <option value="translation">{t("الترجمة", "Translation")}</option>
              </select>
              <button
                className="btn btn--ghost btn--sm"
                type="button"
                aria-label={t(`شيل ${one.file.name}`, `Remove ${one.file.name}`)}
                disabled={sending}
                onClick={() => onFiles(files.filter((_, at) => at !== index))}
              >
                <Icon name="x" size="sm" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <textarea
        className="input"
        rows={3}
        maxLength={limits.text}
        aria-label={t("رسالتك للـAI", "Your message to the AI")}
        placeholder={t("اكتب للـAI... (Enter يبعت، Shift+Enter سطر جديد)", "Write to the AI... (Enter sends, Shift+Enter for a new line)")}
        value={text}
        onChange={(event) => onText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            if (ready) onSend();
          }
        }}
      />
      <input
        ref={input}
        type="file"
        multiple
        hidden
        accept={ACCEPT}
        data-input="review-files"
        aria-label={t("ملفات للـAI", "Files for the AI")}
        onChange={(event) => {
          add(Array.from(event.target.files ?? []));
          // The same file may be chosen again after it was taken off.
          event.target.value = "";
        }}
      />
      <div className="row row--tight">
        <button className="btn btn--sm" type="button" disabled={disabled || files.length >= limits.files} onClick={() => input.current?.click()}>
          <Icon name="paperclip" size="sm" />
          <span>{t("ارفع ملفات", "Attach files")}</span>
        </button>
        <small className="muted">
          {t(
            `Word وPDF وصور ونصوص، لحد ${limits.files} ملف (${limits.message_megabytes} ميجا كله) والملف لحد ${limits.megabytes} ميجا. أو اسحبهم هنا.`,
            `Word, PDF, pictures and text, up to ${limits.files} files (${limits.message_megabytes} MB in all), ${limits.megabytes} MB each. Or drop them here.`,
          )}
        </small>
        <div className="grow" />
        <button className="btn btn--primary btn--sm" type="submit" disabled={!ready}>
          <Icon name="send" size="sm" />
          <span>{sending ? t("بيتبعت...", "Sending...") : t("ابعت", "Send")}</span>
        </button>
      </div>
      {warn && <div className="note note--warn">{warn}</div>}
      {problem && (
        <div className="note note--high" role="alert">
          <Icon name="alert" />
          <div>{problem}</div>
        </div>
      )}
    </form>
  );
}
