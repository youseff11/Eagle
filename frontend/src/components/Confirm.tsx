import type { ReactNode } from "react";
import { usePreferences } from "../i18n/Preferences";
import { Icon } from "./Icon";
import { Modal } from "./Modal";

/**
 * "Are you sure?" - the site's own box instead of the browser's grey one (what `Eagle.ask` is on the classic pages).
 *
 * It asks, and says why when the answer was refused: the question stays open with the reason under it, so a refusal
 * is read where it happened and the person can say no or try again. While the answer is on its way nothing closes it.
 */
export function Confirm({
  title,
  body,
  yes,
  danger = false,
  busy = false,
  problem = "",
  icon = "alert",
  onYes,
  onNo,
}: {
  title: string;
  body?: ReactNode;
  /** What the confirming button says. */
  yes: string;
  /** A question about something that cannot be undone: the button is red. */
  danger?: boolean;
  busy?: boolean;
  /** Why the last try was refused. */
  problem?: string;
  icon?: string;
  onYes: () => void;
  onNo: () => void;
}) {
  const { t } = usePreferences();
  return (
    <Modal title={title} icon={icon} busy={busy} onClose={onNo}>
      {body && <div style={{ margin: "8px 0" }}>{body}</div>}
      {problem && (
        <div className="note note--high" role="alert">
          <Icon name="alert" />
          <div>{problem}</div>
        </div>
      )}
      <div className="row" style={{ marginTop: 14 }}>
        <div className="grow" />
        <button type="button" className="btn" disabled={busy} onClick={onNo}>
          {t("إلغاء", "Cancel")}
        </button>
        <button type="button" className={`btn ${danger ? "btn--danger" : "btn--primary"}`} disabled={busy} onClick={onYes}>
          <span>{yes}</span>
        </button>
      </div>
    </Modal>
  );
}
