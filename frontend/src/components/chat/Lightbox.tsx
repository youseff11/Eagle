import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { usePreferences } from "../../i18n/Preferences";
import { Icon } from "../Icon";

export interface LightboxImage {
  url: string;
  name: string;
}

/**
 * The photos of one message, one at a time and in the order they were sent: the arrows (and the keyboard's) step to the next
 * and back, the counter says where it is, and Escape, the cross or a press on the dark ground close it. It stops at the first
 * and the last. The buttons are on the screen's left and right whichever the language: they follow the picture row, not the
 * text.
 */
export function Lightbox({ images, start, onClose }: { images: LightboxImage[]; start: number; onClose: () => void }) {
  const { t } = usePreferences();
  const last = images.length - 1;
  const [at, setAt] = useState(Math.min(Math.max(start, 0), last));
  const closer = useRef<HTMLButtonElement>(null);
  const step = useCallback((by: number) => setAt((now) => Math.min(last, Math.max(0, now + by))), [last]);

  useEffect(() => {
    closer.current?.focus();
    const keys = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      else if (event.key === "ArrowRight") step(1);
      else if (event.key === "ArrowLeft") step(-1);
    };
    document.addEventListener("keydown", keys);
    return () => document.removeEventListener("keydown", keys);
  }, [onClose, step]);

  const image = images[at];
  if (!image) return null;
  // In the body, not in the bubble: a bubble that is being swiped carries a transform, and a fixed box inside one is not fixed to
  // the screen. Its presses are the lightbox's own, not the bubble's (React sends an event on through a portal to the parent).
  return createPortal(
    <div
      className="lightbox"
      role="dialog"
      aria-modal="true"
      aria-label={t("الصور", "Photos")}
      onClick={(event) => event.stopPropagation()}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="lightbox__bar">
        <span className="lightbox__count mono" data-lightbox-count="">
          {at + 1} / {images.length}
        </span>
        <button ref={closer} type="button" className="icon-btn" onClick={onClose} title={t("إغلاق", "Close")} aria-label={t("إغلاق", "Close")}>
          <Icon name="x" />
        </button>
      </div>
      <button
        type="button"
        className="icon-btn lightbox__nav lightbox__prev"
        disabled={at === 0}
        onClick={() => step(-1)}
        title={t("اللي قبلها", "Previous")}
        aria-label={t("اللي قبلها", "Previous")}
      >
        <Icon name="arrow-right" />
      </button>
      <img className="lightbox__img" src={image.url} alt={image.name} />
      <button
        type="button"
        className="icon-btn lightbox__nav lightbox__next"
        disabled={at === last}
        onClick={() => step(1)}
        title={t("اللي بعدها", "Next")}
        aria-label={t("اللي بعدها", "Next")}
      >
        <Icon name="arrow-right" />
      </button>
    </div>,
    document.body,
  );
}
