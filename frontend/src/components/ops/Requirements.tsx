import { useState } from "react";
import type { NewRequirement } from "../../api/opsActions";
import type { Labelled, TaskFile, ThreadFile } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { downloadUrl } from "../../lib/fileUrl";
import { safeInternalPath } from "../../lib/safeUrl";
import { taskProblem } from "../../lib/taskProblem";
import { FileViewer, ViewerBody, viewerKind } from "../chat/FileViewer";
import { Icon } from "../Icon";
import { useToasts } from "../Toasts";

const REQUIREMENT_ICON: Record<string, string> = { like: "thumbs-up", dislike: "thumbs-down", rule: "pin" };
/** The biggest file a requirement may carry: the server's own limit (`api_ops.MAX_REQUIREMENT_FILE_BYTES`). */
const MAX_FILE_BYTES = 25 * 1024 * 1024;
const REQUIREMENT_KINDS: [string, string, string][] = [
  ["rule", "قاعدة", "Rule"],
  ["like", "بيحب", "Likes"],
  ["dislike", "بيكره", "Dislikes"],
];

/** A thing the client likes, dislikes or insists on. The words are masked by the server for whoever may not know the client. */
export interface Requirement {
  id: number;
  kind: Labelled;
  author: string | null;
  text: string;
  /** The file attached to it, when there is one. Opens from `/files/`, under the name the server masked. */
  file?: TaskFile | null;
  /** The day it was written, when the page shows it (the client page does, the task page does not). */
  at?: { ar: string; en: string } | null;
}

/**
 * The file of a requirement, shown itself and not as a link: a picture as a picture, a PDF page by page, a Word file's text, a text
 * file - the chat viewer's own drawing (`ViewerBody`), in a box that scrolls. A type the page cannot draw says so and leaves the
 * download. «فتح كبير» opens the same file over the page. Every page that lists requirements draws it the same way.
 */
export function RequirementFile({ file }: { file: TaskFile }) {
  const { t } = usePreferences();
  const [big, setBig] = useState(false);
  const href = safeInternalPath(file.url);
  if (!href) return <span className="file-pill">{file.name}</span>;
  const thread: ThreadFile = { id: file.id, url: href, name: file.name, size: 0, mime: "", voice: false, audio: false, length: "", image: file.image };
  const kind = file.image ? "image" : viewerKind(thread);
  return (
    <div className="req-file" data-requirement-file="">
      <div className="req-file__bar">
        <Icon name="paperclip" size="sm" />
        <span className="req-file__name" dir="auto">
          {file.name}
        </span>
        <span className="muted mono">{file.size}</span>
        <div className="grow" />
        {kind !== "image" && kind !== "other" && (
          <button className="btn btn--sm" type="button" onClick={() => setBig(true)}>
            <Icon name="eye" size="sm" />
            <span>{t("فتح كبير", "Open large")}</span>
          </button>
        )}
        <a className="btn btn--sm" href={downloadUrl(href)} download={file.name} data-download="">
          <Icon name="download" size="sm" />
          <span>{t("تنزيل", "Download")}</span>
        </a>
      </div>
      <div className="req-file__preview">
        {kind === "image" ? (
          <a href={href} target="_blank" rel="noopener noreferrer">
            <img src={href} alt={file.name} loading="lazy" />
          </a>
        ) : (
          <ViewerBody kind={kind} url={href} name={file.name} />
        )}
      </div>
      {big && <FileViewer file={thread} url={href} onClose={() => setBig(false)} />}
    </div>
  );
}

/** What the form needs of the action it adds with: the mutation of either page fits. */
export interface AddsRequirement {
  mutate: (
    values: NewRequirement,
    options: { onSuccess: () => void; onError: (error: unknown) => void },
  ) => void;
  isPending: boolean;
}

/** What the client likes, dislikes and insists on, read by everybody on the job - and the form that adds one. */
export function Requirements({ requirements, add }: { requirements: Requirement[]; add: AddsRequirement | null }) {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const [kind, setKind] = useState("rule");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  // A new key empties the file box: a file input cannot be cleared from its value in every browser.
  const [pickerKey, setPickerKey] = useState(0);
  const [problem, setProblem] = useState("");

  return (
    <>
      {requirements.map((requirement) => (
        <div className={`note${requirement.kind.value === "dislike" ? " note--high" : ""}`} key={requirement.id}>
          <Icon name={REQUIREMENT_ICON[requirement.kind.value] ?? "pin"} />
          <div>
            <div className="note__where">
              {lang === "ar" ? requirement.kind.ar : requirement.kind.en} · {requirement.author ?? "—"}
              {requirement.at ? ` · ${lang === "ar" ? requirement.at.ar : requirement.at.en}` : ""}
            </div>
            {requirement.text && <div>{requirement.text}</div>}
            {requirement.file && <RequirementFile file={requirement.file} />}
          </div>
        </div>
      ))}
      {requirements.length === 0 && <div className="muted">{t("مفيش متطلبات مسجلة لحد دلوقتي.", "No requirements recorded yet.")}</div>}

      {add && (
        <form
          className="mt"
          onSubmit={(event) => {
            event.preventDefault();
            if ((!text.trim() && !file) || add.isPending) return;
            if (file && file.size > MAX_FILE_BYTES) {
              setProblem(t("الملف أكبر من 25 ميجا.", "The file is bigger than 25 MB."));
              return;
            }
            setProblem("");
            add.mutate(
              { kind, text: text.trim(), file },
              {
                onSuccess: () => {
                  setText("");
                  setFile(null);
                  setPickerKey((current) => current + 1);
                  push({ level: "success", title: t("المتطلب اتضاف", "Requirement added") });
                },
                onError: (error) => setProblem(taskProblem(error, t)),
              },
            );
          }}
        >
          <div className="field">
            <select className="input" value={kind} aria-label={t("النوع", "Kind")} onChange={(event) => setKind(event.target.value)}>
              {REQUIREMENT_KINDS.map(([value, ar, en]) => (
                <option key={value} value={value}>
                  {lang === "ar" ? ar : en}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <textarea
              className="input"
              rows={2}
              maxLength={2000}
              value={text}
              aria-label={t("المتطلب", "Requirement")}
              onChange={(event) => setText(event.target.value)}
            />
          </div>
          <div className="field">
            <label className="label" htmlFor="requirement-file">
              {t("ملف (اختياري)", "File (optional)")}
            </label>
            <input
              id="requirement-file"
              key={pickerKey}
              className="input"
              type="file"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </div>
          <button className="btn btn--sm btn--block" type="submit" disabled={(!text.trim() && !file) || add.isPending}>
            <Icon name="plus" size="sm" />
            <span>{t("ضيف متطلب", "Add requirement")}</span>
          </button>
          {problem && (
            <div className="note note--high mt" role="alert">
              <Icon name="alert" />
              <div>{problem}</div>
            </div>
          )}
        </form>
      )}
    </>
  );
}
