import { useEffect, useId, type ReactNode } from "react";
import { usePreferences } from "../i18n/Preferences";
import { Icon } from "./Icon";

/**
 * The frame of a dialog: the dim backdrop, the title row with its close button, and the three ways out - the button,
 * Escape and a press on the backdrop (not on the dialog itself). While `busy` (something is on its way) none of the
 * three works: closing then would hide the answer of a request that has already been sent.
 */
export function Modal({
  title,
  icon,
  count,
  busy = false,
  onClose,
  children,
}: {
  title: string;
  icon: string;
  /** A number beside the title (how many things this is about). */
  count?: number;
  busy?: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  const { t } = usePreferences();
  const titleId = useId();

  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [busy, onClose]);

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby={titleId} style={{ textAlign: "start" }}>
        <div className="row row--tight">
          <Icon name={icon} />
          <div className="modal__title" id={titleId}>
            {title}
          </div>
          {count !== undefined && <span className="chip chip--sm mono">{count}</span>}
          <div className="grow" />
          <button type="button" className="icon-btn" onClick={onClose} disabled={busy} title={t("إغلاق", "Close")} aria-label={t("إغلاق", "Close")}>
            <Icon name="x" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
