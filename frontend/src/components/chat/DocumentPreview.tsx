import type { MouseEvent } from "react";
import type { ThreadFile } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { prettySize } from "../../lib/size";
import { Icon } from "../Icon";
import { downloadUrl } from "../../lib/fileUrl";
import { viewerKind } from "./FileViewer";

/** What the badge on a file says and how it is coloured: a PDF is red, a Word file blue, anything else grey with its extension. */
function badgeOf(file: ThreadFile): { kind: "pdf" | "word" | "other"; label: string } {
  const extension = /\.([a-z0-9]{1,8})$/i.exec(file.name)?.[1]?.toLowerCase() ?? "";
  const kind = viewerKind(file);
  if (kind === "pdf") return { kind: "pdf", label: "PDF" };
  if (kind === "word") return { kind: "word", label: "DOC" };
  return { kind: "other", label: extension.slice(0, 4).toUpperCase() };
}

/** What is inside a document card: the badge, the name, and the type and size under it. The card around it is a link, or - while the file is on its way - not. */
export function DocumentFace({ file, task = "" }: { file: ThreadFile; task?: string }) {
  const { t } = usePreferences();
  const badge = badgeOf(file);
  const extension = /\.([a-z0-9]{1,8})$/i.exec(file.name)?.[1]?.toUpperCase() ?? "";
  return (
    <>
      <span className={`document-card__badge document-card__badge--${badge.kind}`} aria-hidden="true">
        {badge.kind === "other" && badge.label === "" ? <Icon name="file" /> : badge.label}
      </span>
      <span className="document-card__details">
        <span className="document-card__name" dir="auto">
          {file.name}
        </span>
        <span className="document-card__meta">
          <span className="mono">
            {extension || t("ملف", "FILE")}
            {file.size > 0 ? ` · ${prettySize(file.size)}` : ""}
          </span>
          {task && <span className="chip chip--sm mono document-card__task" title={t("التاسك", "Task")}>{task}</span>}
        </span>
      </span>
    </>
  );
}

/**
 * A file of the chat as a small card, as WhatsApp draws it: a badge that says what kind of file it is (PDF, Word), the name, and
 * the type and size under it. It shows nothing of what is inside the file - a press saves the file at once (no preview).
 * `task` is the code of the task the file belongs to, written on the card. `viewer` is off while the page is picking files
 * (a press then ticks the file, it saves nothing).
 */
export function DocumentPreview({ file, url, viewer = true, task = "" }: { file: ThreadFile; url: string; viewer?: boolean; task?: string }) {
  const hold = (event: MouseEvent<HTMLAnchorElement>) => {
    if (!viewer) event.preventDefault();
  };

  return (
    <a className="document-card" href={downloadUrl(url)} download={file.name} aria-label={file.name} title={file.name} onClick={hold}>
      <DocumentFace file={file} task={task} />
    </a>
  );
}
