import { useState } from "react";
import { ApiError } from "../../api/client";
import { useHandIn } from "../../api/queries";
import { usePreferences } from "../../i18n/Preferences";
import { Icon } from "../Icon";
import { Modal } from "../Modal";

/**
 * The bar that replaces the box to write in while a translator is handing their work in («خلصت التاسك»): how many
 * files are ticked, which task if they have several, and the button. Pressing it asks once more - it moves the task
 * to review, which is not something to do by a stray tap - and then says the result. Which files count, and whether
 * this person may hand this task in at all, is the server's: its reason is shown when it refuses.
 */
export function HandInBar({
  room,
  code,
  tasks,
  files,
  onCancel,
  onDone,
}: {
  room: number;
  /** The conversation's code, so what the hand-in changes in it is asked for again. */
  code: string;
  tasks: { code: string; title: string }[];
  /** The ids of the ticked files. */
  files: number[];
  onCancel: () => void;
  /** It went to review: the task's code. */
  onDone: (task: string) => void;
}) {
  const { t } = usePreferences();
  const hand = useHandIn(room, code);
  const [picked, setPicked] = useState(tasks[0]?.code ?? "");
  const [confirming, setConfirming] = useState(false);
  const [problem, setProblem] = useState("");
  // A task that has left the list (it was handed in elsewhere) is not the one that is meant.
  const task = tasks.some((one) => one.code === picked) ? picked : (tasks[0]?.code ?? "");

  const send = () => {
    if (hand.isPending || !task || files.length === 0) return;
    setProblem("");
    hand.mutate(
      { task, files },
      {
        onSuccess: () => {
          setConfirming(false);
          onDone(task);
        },
        onError: (error) => {
          if (error instanceof ApiError && error.detail) setProblem(error.detail);
          else if (error instanceof ApiError && error.status < 500) setProblem(t("مش ممكن.", "Not possible."));
          else setProblem(t("مش متأكدين إن التاسك راحت. بص على التاسك قبل ما تبعت تاني.", "We are not sure it went through. Look at the task before sending again."));
        },
      },
    );
  };

  return (
    <>
      <div className="cchat__pickbar" role="toolbar" aria-label={t("خلصت التاسك", "Task done")}>
        <Icon name="check-circle" size="sm" />
        <span aria-live="polite">
          <b className="mono">{files.length}</b> {t("ملف متحدد", "selected")}
        </span>
        {tasks.length > 1 ? (
          <select className="input cchat__pickday" value={task} onChange={(event) => setPicked(event.target.value)} aria-label={t("التاسك", "Task")}>
            {tasks.map((one) => (
              <option key={one.code} value={one.code}>
                {one.code} · {one.title.length > 30 ? `${one.title.slice(0, 29)}…` : one.title}
              </option>
            ))}
          </select>
        ) : (
          <span className="chip chip--sm mono">{task}</span>
        )}
        <span className="grow" />
        <button type="button" className="btn btn--sm" onClick={onCancel}>
          {t("إلغاء", "Cancel")}
        </button>
        <button type="button" className="btn btn--sm btn--primary" disabled={files.length === 0 || !task} onClick={() => setConfirming(true)}>
          <Icon name="check" size="sm" />
          <span>{t("خلصت التاسك", "Task done")}</span>
        </button>
      </div>

      {confirming && (
        <Modal title={t("خلصت التاسك", "Task done")} icon="check-circle" busy={hand.isPending} onClose={() => setConfirming(false)}>
          <p>
            {t(
              `الملفات دي هتتسجّل على ${task} والتاسك هتروح للمراجعة. تمام؟`,
              `These files go on ${task} and the task goes to review. Go ahead?`,
            )}
          </p>
          <div className="row" style={{ marginTop: 14, alignItems: "center" }}>
            <div role="alert" style={{ color: "var(--danger, #e5484d)", fontSize: ".8rem" }}>
              {problem}
            </div>
            <div className="grow" />
            <button type="button" className="btn" onClick={() => setConfirming(false)} disabled={hand.isPending}>
              {t("إلغاء", "Cancel")}
            </button>
            <button type="button" className="btn btn--primary" onClick={send} disabled={hand.isPending}>
              <Icon name="check" size="sm" />
              <span>{hand.isPending ? t("بيتبعت...", "Sending...") : t("تمام، ابعت", "Yes, send")}</span>
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
