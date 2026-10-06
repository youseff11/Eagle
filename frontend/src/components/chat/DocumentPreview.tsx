import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type MouseEvent } from "react";
import { api } from "../../api/client";
import type { ThreadFile } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { previewUrl } from "../../lib/fileUrl";
import { prettySize } from "../../lib/size";
import { Icon } from "../Icon";
import { FileViewer } from "./FileViewer";
import PdfPreview from "./PdfPreview";

function WordPreview({ url, name }: { url: string; name: string }) {
  const { t } = usePreferences();
  const [brokenImage, setBrokenImage] = useState(false);
  const query = useQuery({
    queryKey: ["document-preview", url],
    queryFn: ({ signal }) => api<{ text: string; thumb: boolean }>(previewUrl(url, "1"), { signal }),
    staleTime: 5 * 60_000,
    retry: false,
  });
  if (query.data?.thumb && !brokenImage) {
    return <img src={previewUrl(url, "thumb")} alt={t("معاينة: ", "Preview: ") + name} onError={() => setBrokenImage(true)} />;
  }
  if (query.data?.text) {
    return <span className="document-card__paper" dir="auto">{query.data.text}</span>;
  }
  return <PreviewPlaceholder loading={query.isPending} />;
}

export function PreviewPlaceholder({ loading = false }: { loading?: boolean }) {
  const { t } = usePreferences();
  return (
    <span className="document-card__placeholder">
      <Icon name="file" size="xl" />
      <span>{loading ? t("تحميل المعاينة…", "Loading preview…") : t("المعاينة غير متاحة", "Preview unavailable")}</span>
    </span>
  );
}

/** Load only nearby cards, using the same protected file addresses as a download. */
export function DocumentPreview({ file, url, viewer = true }: { file: ThreadFile; url: string; viewer?: boolean }) {
  const { t } = usePreferences();
  const element = useRef<HTMLAnchorElement>(null);
  const [visible, setVisible] = useState(false);
  const [open, setOpen] = useState(false);
  const extension = /\.([a-z0-9]{1,8})$/i.exec(file.name)?.[1]?.toLowerCase() ?? "";
  const word = ["docx", "docm", "dotx"].includes(extension);
  const pdf = !word && (extension === "pdf" || file.mime.split(";")[0]?.trim().toLowerCase() === "application/pdf");

  useEffect(() => {
    const node = element.current;
    if (!node) return;
    if (typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        setVisible(true);
        observer.disconnect();
      }
    }, { root: node.closest(".cchat__stream"), rootMargin: "160px" });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  // A press opens the file over the chat, with a button that saves it; the address stays a real link, so a middle or modified press
  // still opens it in a tab. `viewer` is off while the page is picking files (a press then ticks the file, it opens nothing).
  const show = (event: MouseEvent<HTMLAnchorElement>) => {
    if (!viewer || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    setOpen(true);
  };

  return (
    <>
    <a ref={element} className="document-card" href={url} target="_blank" rel="noopener noreferrer" aria-label={file.name} title={file.name} onClick={show}>
      <span className="document-card__preview">
        {visible && word ? <WordPreview key={url} url={url} name={file.name} /> : visible && pdf ? (
          <PdfPreview key={url} url={url} name={file.name} />
        ) : <PreviewPlaceholder loading={!visible && (word || pdf)} />}
      </span>
      <span className="document-card__details">
        <span className="document-card__name" dir="auto">{file.name}</span>
        <span className="document-card__meta">
          <span className="mono">{extension.toUpperCase() || t("ملف", "FILE")}{file.size > 0 ? ` · ${prettySize(file.size)}` : ""}</span>
          <Icon name="file" size="sm" />
        </span>
      </span>
    </a>
    {open && <FileViewer file={file} url={url} onClose={() => setOpen(false)} />}
    </>
  );
}
