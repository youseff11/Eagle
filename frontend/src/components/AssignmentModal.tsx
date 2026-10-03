import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Link, matchPath, useLocation } from "react-router";
import { usePending } from "../api/queries";
import type { PendingAssignment } from "../api/types";
import { useAssignmentDecision } from "../hooks/useAssignmentDecision";
import { useCountdown } from "../hooks/useCountdown";
import { usePreferences } from "../i18n/Preferences";
import { clockText } from "../lib/clock";
import { chime } from "../lib/chime";
import { safeInternalPath } from "../lib/safeUrl";
import { deadlineLeft } from "../lib/timeLeft";
import { Icon } from "./Icon";
import { useToasts } from "./Toasts";

/** The seconds, left, at which the popup rings once more - as the classic one does. */
const WARNINGS = new Set([20, 10, 5]);
/** From here on the ring is red and the number pulses. */
const CRITICAL = 15;

function Popup({ pending, onGone }: { pending: PendingAssignment; onGone: () => void }) {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const left = useCountdown(pending.seconds_left, pending.id) ?? pending.seconds_left;
  const [reason, setReason] = useState("");
  const reasonBox = useRef<HTMLInputElement>(null);
  const { busy, accept, decline } = useAssignmentDecision(
    { id: pending.id, role: pending.role, taskCode: pending.task_code, taskUrl: pending.task_url },
    onGone,
  );
  const rang = useRef(new Set<number>());
  const expired = useRef(false);
  const taskHref = safeInternalPath(pending.task_url);
  const wait = deadlineLeft(pending.deadline_iso, Date.now(), t);

  // A new hand-off rings: three times, loud (a sound the browser allows after the first click on the page).
  useEffect(() => chime(3, 980), []);

  useEffect(() => {
    if (WARNINGS.has(left) && !rang.current.has(left)) {
      rang.current.add(left);
      chime(1, 1200);
    }
  }, [left]);

  // The window ran out: the server has taken the rating penalty already (the beat that follows says so), and
  // the popup goes - the answer would be refused now anyway.
  useEffect(() => {
    if (left > 0 || expired.current) return;
    expired.current = true;
    push({ level: "danger", title: t("عدى وقت الرد", "Response window expired"), body: t("اتخصم من تقييمك.", "A rating penalty was applied.") });
    onGone();
  }, [left, onGone, push, t]);

  const ring = { "--pct": Math.max(0, Math.min(100, (left / Math.max(1, pending.window)) * 100)) } as CSSProperties;

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="assign-title" data-assignment={pending.id}>
      <div className="modal">
        <div className="modal__title" id="assign-title">
          {t("تاسك جديدة ليك", "A task is waiting for you")}
        </div>
        <div className="muted" style={{ fontSize: ".84rem" }}>
          {t("أكد الاستلام قبل ما العداد يخلص، وإلا هيتخصم من تقييمك.", "Confirm before the timer runs out, otherwise a rating penalty applies.")}
        </div>

        <div className={`countdown${left <= CRITICAL ? " is-critical" : ""}`} style={ring} role="timer" aria-label={t("الوقت المتبقي", "Time left")}>
          <span className="countdown__num">{left}</span>
        </div>

        <div className="card card--flat" style={{ textAlign: "start", padding: "12px 14px" }}>
          <div className="kv">
            <span>{t("التاسك", "Task")}</span>
            <strong className="mono">
              {pending.task_code} · {pending.task_title}
            </strong>
          </div>
          <div className="kv">
            <span>{t("كود العميل", "Client code")}</span>
            <strong className="mono">{pending.client}</strong>
          </div>
          <div className="kv">
            <span>{t("من", "From")}</span>
            <strong>{pending.assigned_by || "—"}</strong>
          </div>
          <div className="kv">
            <span>{t("الديدلاين", "Deadline")}</span>
            <strong className="mono">{pending.deadline ? clockText(pending.deadline, lang) : "—"}</strong>
          </div>
          {wait.text && <div className={`deadline-left${wait.late ? " is-late" : ""}`}>{wait.text}</div>}
          {pending.note && (
            <div className="muted" style={{ fontSize: ".8rem" }}>
              {pending.note}
            </div>
          )}
        </div>

        {/* Reading before deciding: the job's own page. It does not answer the hand-off, and the window keeps running. */}
        <Link className="btn btn--ghost" style={{ marginTop: 10 }} to={`/assignments/${pending.id}`}>
          <Icon name="paperclip" size="sm" />
          <span>{t("شوف الملفات والتفاصيل الأول", "See the files and details first")}</span>
        </Link>

        <div className="field" style={{ marginTop: 10, textAlign: "start" }}>
          <label htmlFor="assign-reason">{t("سبب الرفض (لازم لو هترفض)", "Reason (required to decline)")}</label>
          <input
            ref={reasonBox}
            className="input"
            id="assign-reason"
            maxLength={250}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder={t("مشغول بتاسك تانية / مش تخصصي…", "Busy with another task / not my field…")}
          />
        </div>

        <div className="row modal__actions" style={{ justifyContent: "center" }}>
          <button className="btn btn--ok" type="button" disabled={busy} onClick={() => void accept()}>
            <Icon name="check" size="sm" />
            <span>{t("استلمت", "Accept")}</span>
          </button>
          <button
            className="btn btn--danger"
            type="button"
            disabled={busy}
            onClick={() => void decline(reason).then((sent) => !sent && reasonBox.current?.focus())}
          >
            <Icon name="x" size="sm" />
            <span>{t("رفض", "Decline")}</span>
          </button>
          {taskHref && (
            <a className="btn btn--ghost" href={taskHref}>
              {t("افتح التاسك", "Open task")}
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * The 60-second accept screen: a task was handed to this person and the window is open.
 *
 * Drawn over whatever page they are on, as the classic popup is, because the answer is on a clock and a person
 * who has not seen it loses the assignment and part of their rating. It is not drawn on the hand-off's own page
 * (`/assignments/<id>`), which has the same countdown and the same two buttons, and it is not drawn again for a
 * hand-off that has been answered or has run out - the next beat says it is gone.
 */
export function AssignmentModal() {
  const pending = usePending();
  const { pathname } = useLocation();
  const [gone, setGone] = useState<number | null>(null);
  if (!pending || gone === pending.id) return null;
  if (matchPath("/assignments/:id", pathname)?.params.id === String(pending.id)) return null;
  return <Popup key={pending.id} pending={pending} onGone={() => setGone(pending.id)} />;
}
