import { Loading } from "../components/Loading";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import { ApiError, api } from "../api/client";
import { useAssignment } from "../api/queries";
import type { AssignmentResponse } from "../api/types";
import { OriginBadge } from "../components/Badges";
import { Icon } from "../components/Icon";
import { useToasts } from "../components/Toasts";
import { useAssignmentDecision } from "../hooks/useAssignmentDecision";
import { useCountdown } from "../hooks/useCountdown";
import { useNow } from "../hooks/useNow";
import { usePreferences } from "../i18n/Preferences";
import { safeInternalPath } from "../lib/safeUrl";
import { deadlineLeft } from "../lib/timeLeft";
import { useQueryClient } from "@tanstack/react-query";
import { qk } from "../api/keys";

/** A file of the job: a picture is drawn as one, anything else is a card with its name and size. */
function PreviewFile({ file }: { file: AssignmentResponse["task"]["files"][number] }) {
  const href = safeInternalPath(file.url);
  const body = (
    <>
      {file.image && href ? <img src={href} alt={file.name} loading="lazy" /> : <Icon name="paperclip" size="lg" />}
      <span className="preview-file__name">{file.name}</span>
      <span className="preview-file__size muted mono">{file.size}</span>
    </>
  );
  if (!href) return <span className="preview-file">{body}</span>;
  return (
    <a className={`preview-file${file.image ? " preview-file--img" : ""}`} href={href} target="_blank" rel="noopener noreferrer">
      {body}
    </a>
  );
}

/** Accept and decline, with the time that is left. Only while the hand-off is waiting for an answer. */
function Decision({ data }: { data: AssignmentResponse }) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const client = useQueryClient();
  const { assignment, task } = data;
  const left = useCountdown(assignment.seconds_left, assignment.id) ?? assignment.seconds_left;
  const [reason, setReason] = useState("");
  const reasonBox = useRef<HTMLInputElement>(null);
  const expired = useRef(false);
  const { busy, accept, decline } = useAssignmentDecision(
    { id: assignment.id, role: assignment.role, taskCode: task.code, taskUrl: `/tasks/${task.code}/` },
    () => undefined,
  );

  // The window ran out while the page was open: the server has dealt with it, so read it again and say so.
  useEffect(() => {
    if (left > 0 || expired.current) return;
    expired.current = true;
    push({ level: "danger", title: t("عدى وقت الرد", "Response window expired"), body: t("اتخصم من تقييمك.", "A rating penalty was applied.") });
    void client.invalidateQueries({ queryKey: qk.assignment(assignment.id) });
  }, [left, assignment.id, client, push, t]);

  return (
    <div className="card preview-decide">
      <div className="row row--tight">
        <Icon name="timer" />
        <strong>{t("باقي على تأكيد الاستلام", "Time left to confirm")}</strong>
        <span className="badge badge--wait mono" role="timer">
          {left}s
        </span>
      </div>
      <p className="muted" style={{ fontSize: ".8rem" }}>
        {t("فتح الصفحة دي مش استلام — العداد لسه شغال.", "Opening this page is not accepting - the timer is still running.")}
      </p>
      <div className="field">
        <label htmlFor="preview-reason">{t("سبب الرفض (لازم لو هترفض)", "Reason (required to decline)")}</label>
        <input
          ref={reasonBox}
          className="input"
          id="preview-reason"
          maxLength={250}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder={t("مشغول بتاسك تانية / مش تخصصي…", "Busy with another task / not my field…")}
        />
      </div>
      <div className="row">
        <button className="btn btn--ok grow" type="button" disabled={busy} onClick={() => void accept()}>
          <Icon name="check" />
          <span>{t("استلمت", "Accept")}</span>
        </button>
        <button
          className="btn btn--danger"
          type="button"
          disabled={busy}
          onClick={() => void decline(reason).then((sent) => !sent && reasonBox.current?.focus())}
        >
          <Icon name="x" />
          <span>{t("رفض", "Decline")}</span>
        </button>
      </div>
    </div>
  );
}

function Handoff({ data }: { data: AssignmentResponse }) {
  const { t, lang } = usePreferences();
  const { assignment, task } = data;
  const now = useNow();
  const wait = deadlineLeft(task.due_iso, now, t);
  const opened = useRef(false);

  // Looking is recorded, never answering: a POST of its own (a GET changes nothing), once for this visit.
  useEffect(() => {
    if (opened.current || !assignment.pending || !assignment.mine) return;
    opened.current = true;
    void api(`/api/assignments/${assignment.id}/files/`, { form: {} }).catch(() => undefined);
  }, [assignment.id, assignment.pending, assignment.mine]);

  return (
    <div className="assign-preview" id="assignPreview" data-id={assignment.id}>
      <div className="page-head">
        <h1>
          {task.title} <OriginBadge origin={task.origin} />
        </h1>
        <span className="page-head__sub mono">
          {task.code} · {task.client} · {task.source_lang || "—"} → {task.target_lang || "—"}
        </span>
      </div>

      <div className="grid grid--main">
        <div>
          <div className="card">
            <div className="card__head">
              <Icon name="paperclip" />
              <h3>{t("ملفات التاسك", "Task files")}</h3>
              <span className="chip chip--sm">{task.files.length}</span>
            </div>
            {task.files.length > 0 ? (
              <div className="preview-files">
                {task.files.map((file) => (
                  <PreviewFile key={file.id} file={file} />
                ))}
              </div>
            ) : (
              <div className="empty">
                <Icon name="paperclip" size="xl" />
                <span>{t("التاسك دي مفيهاش ملفات من العميل.", "This task carries no client files.")}</span>
              </div>
            )}
          </div>

          <div className="card">
            <div className="card__head">
              <Icon name="list-checks" />
              <h3>{t("الوصف", "Description")}</h3>
            </div>
            {task.description ? (
              <div className="msg-item__text" style={{ whiteSpace: "pre-wrap" }}>
                {task.description}
              </div>
            ) : (
              <div className="muted">{t("مفيش وصف مكتوب.", "No description.")}</div>
            )}
            {assignment.note && (
              <div className="note mt">
                <Icon name="message" />
                <div>
                  <div className="note__where">{assignment.from ?? "—"}</div>
                  <div>{assignment.note}</div>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="sticky-side">
          <div className="card">
            <div className="kv">
              <span>{t("من", "From")}</span>
              <strong>{assignment.from ?? "—"}</strong>
            </div>
            <div className="kv">
              <span>{t("الديدلاين", "Deadline")}</span>
              <strong className="mono">{task.due ? (lang === "ar" ? task.due.ar : task.due.en) : "—"}</strong>
            </div>
            {wait.text && <div className={`deadline-left${wait.late ? " is-late" : ""}`}>{wait.text}</div>}
          </div>

          {assignment.pending && assignment.mine ? (
            <Decision data={data} />
          ) : (
            <>
              <div className="note">
                <Icon name="info" />
                <div>
                  {assignment.pending
                    ? t("التسليم ده لمستخدم تاني: للقراءة بس.", "This hand-off is somebody else's: read only.")
                    : t("التسليم ده اتقفل (اتستلم أو اترفض أو الوقت خلص).", "This hand-off is closed (accepted, declined or timed out).")}
                </div>
              </div>
              {assignment.status === "accepted" && assignment.mine && assignment.role === "translator" && (
                <Link className="btn btn--primary" to={`/tasks/${encodeURIComponent(task.code)}`}>
                  <Icon name="arrow-right" size="sm" />
                  <span>{t("افتح التاسك", "Open the task")}</span>
                </Link>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/** A hand-off read before it is taken: the files, the brief and the time left, with accept and decline right there. */
export function AssignmentPage() {
  const { t } = usePreferences();
  const { id = "" } = useParams();
  const numeric = /^\d{1,15}$/.test(id) ? Number(id) : null;
  const query = useAssignment(numeric);

  if (query.data) return <Handoff data={query.data} />;

  const missing = numeric === null || (query.error instanceof ApiError && query.error.status === 404);
  return (
    <div className="card">
      {query.isError || missing ? (
        <div className="empty" role="alert">
          <Icon name="alert" size="xl" />
          <span>{missing ? t("التسليم ده مش متاح ليك.", "This hand-off is not available to you.") : t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
        </div>
      ) : (
        <Loading className="empty" />
      )}
    </div>
  );
}
