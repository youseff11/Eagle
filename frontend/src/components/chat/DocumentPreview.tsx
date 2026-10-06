import { useState, type MouseEvent } from "react";
import type { ThreadFile } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { prettySize } from "../../lib/size";
import { Icon } from "../Icon";
import { FileViewer, viewerKind } from "./FileViewer";

/** What the badge on a file says and how it is coloured: a PDF is red, a Word file blue, anything else grey with its extension. */
function badgeOf(file: ThreadFile): { kind: "pdf" | "word" | "other"; label: string } {
  const extension = /\.([a-z0-9]{1,8})$/i.exec(file.name)?.[1]?.toLowerCase() ?? "";
  const kind = viewerKind(file);
  if (kind === "pdf") return { kind: "pdf", label: "PDF" };
  if (kind === "word") return { kind: "word", label: "DOC" };
  return { kind: "other", label: extension.slice(0, 4).toUpperCase() };
}

/**
 * A file of the chat as a small card, as WhatsApp draws it: a badge that says what kind of file it is (PDF, Word), the name, and
 * the type and size under it. It shows nothing of what is inside the file - a press opens the file over the chat (`FileViewer`),
 * with a button that saves it. The address stays a real link, so a middle or modified press opens it in a tab. `viewer` is off while
 * the page is picking files (a press then ticks the file, it opens nothing).
 */
export function DocumentPreview({ file, url, viewer = true }: { file: ThreadFile; url: string; viewer?: boolean }) {
  const { t } = usePreferences();
  const [open, setOpen] = useState(false);
  const badge = badgeOf(file);
  const extension = /\.([a-z0-9]{1,8})$/i.exec(file.name)?.[1]?.toUpperCase() ?? "";

  const show = (event: MouseEvent<HTMLAnchorElement>) => {
    if (!viewer || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    setOpen(true);
  };

  return (
    <>
      <a className="document-card" href={url} target="_blank" rel="noopener noreferrer" aria-label={file.name} title={file.name} onClick={show}>
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
          </span>
        </span>
      </a>
      {open && <FileViewer file={file} url={url} onClose={() => setOpen(false)} />}
    </>
  );
}
