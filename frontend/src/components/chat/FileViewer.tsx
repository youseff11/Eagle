import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../../api/client";
import type { ThreadFile } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { downloadUrl, previewUrl } from "../../lib/fileUrl";
import { prettySize } from "../../lib/size";
import { Icon } from "../Icon";
import PdfPages from "./PdfPages";

export type ViewerKind = "pdf" | "word" | "text" | "video" | "other";

/** What a file can be shown as inside the page: a PDF, a Word file's text, a plain text file, a video. Anything else is only saved. */
export function viewerKind(file: Pick<ThreadFile, "name" | "mime">): ViewerKind {
  const extension = /\.([a-z0-9]{1,8})$/i.exec(file.name)?.[1]?.toLowerCase() ?? "";
  const mime = file.mime.split(";")[0]?.trim().toLowerCase() ?? "";
  if (["docx", "docm", "dotx"].includes(extension)) return "word";
  if (extension === "pdf" || mime === "application/pdf") return "pdf";
  if (extension === "txt" || mime === "text/plain") return "text";
  if (mime.startsWith("video/")) return "video";
  return "other";
}

function Unavailable({ name }: { name: string }) {
  const { t } = usePreferences();
  return (
    <div className="fileviewer__empty" role="status">
      <Icon name="file" size="xl" />
      <span>{t("مش قادرين نعرض الملف ده هنا. تقدر تنزّله.", "This file cannot be shown here. You can download it.")}</span>
      <small className="muted" dir="auto">
        {name}
      </small>
    </div>
  );
}

function WordText({ url, name }: { url: string; name: string }) {
  const { t } = usePreferences();
  const query = useQuery({
    queryKey: ["document-full", url],
    queryFn: ({ signal }) => api<{ text: string; truncated: boolean }>(previewUrl(url, "full"), { signal }),
    staleTime: 5 * 60_000,
    retry: false,
  });
  if (query.isPending) return <div className="fileviewer__empty">{t("بنفتح الملف…", "Opening the file…")}</div>;
  if (!query.data?.text) return <Unavailable name={name} />;
  return (
    <div className="fileviewer__paper" dir="auto" data-viewer="word">
      {query.data.text}
      {query.data.truncated && (
        <p className="muted">{t("الملف أطول من اللي بيتعرض هنا. نزّله عشان تشوفه كله.", "The file is longer than what is shown here. Download it to read all of it.")}</p>
      )}
    </div>
  );
}

const TEXT_LIMIT = 100_000;

function PlainText({ url, name }: { url: string; name: string }) {
  const { t } = usePreferences();
  const query = useQuery({
    queryKey: ["document-text", url],
    queryFn: async ({ signal }) => {
      const response = await fetch(url, { credentials: "same-origin", signal });
      if (!response.ok) throw new Error("not ok");
      return response.text();
    },
    staleTime: 5 * 60_000,
    retry: false,
  });
  if (query.isPending) return <div className="fileviewer__empty">{t("بنفتح الملف…", "Opening the file…")}</div>;
  if (query.data === undefined) return <Unavailable name={name} />;
  return (
    <div className="fileviewer__paper" dir="auto" data-viewer="text">
      {query.data.slice(0, TEXT_LIMIT)}
      {query.data.length > TEXT_LIMIT && (
        <p className="muted">{t("الملف أطول من اللي بيتعرض هنا. نزّله عشان تشوفه كله.", "The file is longer than what is shown here. Download it to read all of it.")}</p>
      )}
    </div>
  );
}

/**
 * A file of the chat opened over it, without saving anything: a PDF page by page, a Word file's text, a text file, a video. The
 * button beside the name saves it (`?dl=1`, the same protected address, so the same rule decides who may). Escape, the cross or a
 * press on the dark ground close it. A type the page cannot show says so and leaves the download.
 */
export function FileViewer({ file, url, onClose }: { file: ThreadFile; url: string; onClose: () => void }) {
  const { t } = usePreferences();
  const closer = useRef<HTMLButtonElement>(null);
  const [failed, setFailed] = useState(false);
  const kind = viewerKind(file);

  useEffect(() => {
    closer.current?.focus();
    const keys = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", keys);
    return () => document.removeEventListener("keydown", keys);
  }, [onClose]);

  // In the body, not in the bubble: a bubble that is swiped carries a transform, and a fixed box inside one is not fixed to the screen.
  return createPortal(
    <div
      className="fileviewer"
      role="dialog"
      aria-modal="true"
      aria-label={file.name}
      onClick={(event) => event.stopPropagation()}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="fileviewer__bar">
        <button ref={closer} type="button" className="icon-btn" onClick={onClose} title={t("إغلاق", "Close")} aria-label={t("إغلاق", "Close")}>
          <Icon name="x" />
        </button>
        <div className="fileviewer__title">
          <span dir="auto">{file.name}</span>
          {file.size > 0 && <small className="mono">{prettySize(file.size)}</small>}
        </div>
        <a className="btn btn--primary btn--sm" href={downloadUrl(url)} download={file.name} data-download="">
          <Icon name="download" size="sm" />
          <span>{t("تنزيل", "Download")}</span>
        </a>
      </div>
      <div className="fileviewer__body">
        {kind === "pdf" && !failed && <PdfPages url={url} name={file.name} onFail={() => setFailed(true)} />}
        {kind === "pdf" && failed && <Unavailable name={file.name} />}
        {kind === "word" && <WordText url={url} name={file.name} />}
        {kind === "text" && <PlainText url={url} name={file.name} />}
        {kind === "video" && <video className="fileviewer__video" controls preload="metadata" src={url} />}
        {kind === "other" && <Unavailable name={file.name} />}
      </div>
    </div>,
    document.body,
  );
}
