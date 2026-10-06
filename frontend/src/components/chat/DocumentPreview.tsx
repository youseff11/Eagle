import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { ThreadFile } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { prettySize } from "../../lib/size";
import { Icon } from "../Icon";
import PdfPreview from "./PdfPreview";

function previewUrl(url: string, mode: string) {
  const parsed = new URL(url, window.location.origin);
  parsed.searchParams.set("preview", mode);
  parsed.hash = "";
  return parsed.pathname + parsed.search;
}

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
export function DocumentPreview({ file, url }: { file: ThreadFile; url: string }) {
  const { t } = usePreferences();
  const element = useRef<HTMLAnchorElement>(null);
  const [visible, setVisible] = useState(false);
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

  return (
    <a ref={element} className="document-card" href={url} target="_blank" rel="noopener noreferrer" aria-label={file.name} title={file.name}>
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
  );
}
