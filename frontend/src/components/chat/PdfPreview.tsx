import { useEffect, useRef, useState } from "react";
import type { PDFDocumentLoadingTask } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { usePreferences } from "../../i18n/Preferences";
import { PreviewPlaceholder } from "./DocumentPreview";

export default function PdfPreview({ url, name }: { url: string; name: string }) {
  const { t } = usePreferences();
  const canvas = useRef<HTMLCanvasElement>(null);
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading");
  useEffect(() => {
    let stopped = false;
    let task: PDFDocumentLoadingTask | undefined;
    const draw = async () => {
      try {
        const { getDocument, GlobalWorkerOptions } = await import("pdfjs-dist");
        if (stopped) return;
        // Bundle the worker with the app: client documents never go to an outside viewer.
        GlobalWorkerOptions.workerSrc = workerUrl;
        task = getDocument({ url, withCredentials: true, useSystemFonts: true });
        const document = await task.promise;
        if (stopped) return;
        const page = await document.getPage(1);
        const node = canvas.current;
        if (stopped || !node) return;
        const natural = page.getViewport({ scale: 1 });
        const viewport = page.getViewport({ scale: Math.min(500 / natural.width, 600 / natural.height) });
        node.width = Math.ceil(viewport.width);
        node.height = Math.ceil(viewport.height);
        await page.render({ canvas: node, viewport }).promise;
        if (!stopped) setState("ready");
      } catch {
        if (!stopped) setState("failed");
      } finally {
        if (!stopped) void task?.destroy().catch(() => undefined);
      }
    };
    void draw();
    return () => {
      stopped = true;
      void task?.destroy().catch(() => undefined);
    };
  }, [url]);

  return (
    <>
      {state !== "ready" && <PreviewPlaceholder loading={state === "loading"} />}
      <canvas ref={canvas} hidden={state !== "ready"} role="img" aria-label={t("معاينة: ", "Preview: ") + name} />
    </>
  );
}
