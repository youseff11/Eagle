import { useEffect, useRef, useState } from "react";
import type { PDFDocumentLoadingTask } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { usePreferences } from "../../i18n/Preferences";

/** Pages drawn one under the other, as far as this: a longer file is saved with the button, not drawn page by page. */
const MAX_PAGES = 60;
const MAX_WIDTH = 980;

/**
 * Every page of a PDF, drawn by pdf.js with the worker bundled in the app (a client's document never goes to an outside viewer),
 * one canvas under the other, as wide as the window lets it be. The first page shows as soon as it is drawn, the rest follow.
 */
export default function PdfPages({ url, name, onFail }: { url: string; name: string; onFail: () => void }) {
  const { t } = usePreferences();
  const box = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<{ phase: "loading" | "ready"; pages: number; shown: number }>({ phase: "loading", pages: 0, shown: 0 });

  useEffect(() => {
    let stopped = false;
    let task: PDFDocumentLoadingTask | undefined;
    const draw = async () => {
      try {
        const { getDocument, GlobalWorkerOptions } = await import("pdfjs-dist");
        if (stopped) return;
        GlobalWorkerOptions.workerSrc = workerUrl;
        task = getDocument({ url, withCredentials: true, useSystemFonts: true });
        const document = await task.promise;
        const host = box.current;
        if (stopped || !host) return;
        const total = Math.min(document.numPages, MAX_PAGES);
        setState({ phase: "ready", pages: document.numPages, shown: 0 });
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        for (let number = 1; number <= total; number += 1) {
          const page = await document.getPage(number);
          if (stopped) return;
          const natural = page.getViewport({ scale: 1 });
          const width = Math.min(host.clientWidth || MAX_WIDTH, MAX_WIDTH);
          const viewport = page.getViewport({ scale: (width / natural.width) * ratio });
          const canvas = window.document.createElement("canvas");
          canvas.width = Math.ceil(viewport.width);
          canvas.height = Math.ceil(viewport.height);
          canvas.className = "fileviewer__page";
          canvas.setAttribute("role", "img");
          canvas.setAttribute("aria-label", `${name} - ${number}`);
          host.appendChild(canvas);
          await page.render({ canvas, viewport }).promise;
          if (!stopped) setState((now) => ({ ...now, shown: number }));
        }
      } catch {
        if (!stopped) onFail();
      }
    };
    void draw();
    return () => {
      stopped = true;
      void task?.destroy().catch(() => undefined);
    };
    // The address is the file: a new one is a new document.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  return (
    <>
      {state.phase === "loading" && <div className="fileviewer__empty">{t("بنفتح الملف…", "Opening the file…")}</div>}
      <div ref={box} className="fileviewer__pages" data-viewer="pdf" />
      {state.pages > MAX_PAGES && (
        <p className="muted fileviewer__more">{t(`الملف فيه ${state.pages} صفحة، المعروض أول ${MAX_PAGES}. نزّله عشان تشوفه كله.`, `The file has ${state.pages} pages; the first ${MAX_PAGES} are shown. Download it to read all of it.`)}</p>
      )}
    </>
  );
}
