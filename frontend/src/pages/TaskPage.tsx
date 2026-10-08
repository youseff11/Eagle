import { Loading } from "../components/Loading";
import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useLocation, useParams } from "react-router";
import { ApiError } from "../api/client";
import { useAskMoreTime, useFinishTask, useMe, useTranslatorTask, useUploadTranslation } from "../api/queries";
import type { TaskFile, TranslatorTask } from "../api/types";
import { deadlineClass, OriginBadge, PriorityBadge, StatusBadge } from "../components/Badges";
import { Countdown } from "../components/Countdown";
import { Icon } from "../components/Icon";
import { Modal } from "../components/Modal";
import { PartBox } from "../components/PartBox";
import { AiCheckCard } from "../components/task/AiCheckCard";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";
import { lengthOfTime } from "../lib/duration";
import { ROLE_LABELS } from "../lib/roles";
import { safeInternalPath } from "../lib/safeUrl";
import { taskProblem } from "../lib/taskProblem";

const REQUIREMENT_ICON: Record<string, string> = { like: "thumbs-up", dislike: "thumbs-down", rule: "pin" };

/** A file of the job: a picture is shown as one, anything else is a link. The address is the server's, drawn only if it is a path on this site. */
function FileLink({ file, detail }: { file: TaskFile; detail?: string }) {
  const href = safeInternalPath(file.url);
  const title = detail ? `${file.size} · ${detail}` : file.size;
  if (!href) return <span className="file-pill">{file.name}</span>;
  if (file.image) {
    return (
      <a className="task-thumb" href={href} target="_blank" rel="noopener noreferrer" title={`${file.name} · ${title}`}>
        <img src={href} alt={file.name} loading="lazy" />
      </a>
    );
  }
  return (
    <a className="file-pill" href={href} target="_blank" rel="noopener noreferrer" title={title}>
      <Icon name="paperclip" size="sm" />
      {file.name}
      {detail && <span className="muted mono">{detail}</span>}
    </a>
  );
}

/** The translated file, into the group with the leader (limits: the same ones the chat has). */
function UploadTranslation({ code }: { code: string }) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const limits = useMe().data?.limits.files;
  const upload = useUploadTranslation(code);
  const [problem, setProblem] = useState("");

  const pick = (files: FileList | null) => {
    const picked = Array.from(files ?? []);
    if (picked.length === 0) return;
    setProblem("");
    if (limits && picked.length > limits.count) {
      setProblem(t(`لحد ${limits.count} ملفات في المرة.`, `Up to ${limits.count} files at a time.`));
      return;
    }
    if (limits && picked.reduce((sum, file) => sum + file.size, 0) > limits.total_bytes) {
      setProblem(t("الملفات أكبر من المسموح في المرة الواحدة.", "The files are bigger than one upload may be."));
      return;
    }
    upload.mutate(picked, {
      onSuccess: () => push({ level: "success", title: t("اترفع واتبعت في الجروب", "Uploaded and posted in the group") }),
      onError: (error) => setProblem(taskProblem(error, t)),
    });
  };

  return (
    <div className="mt">
      <div className="row row--tight">
        <label className={`btn btn--primary btn--sm${upload.isPending ? " is-busy" : ""}`}>
          <Icon name="upload" size="sm" />
          <span>{t("ارفع ملف الترجمة", "Upload the translation")}</span>
          <input
            type="file"
            multiple
            hidden
            disabled={upload.isPending}
            data-testid="translation-input"
            onChange={(event) => {
              pick(event.target.files);
              event.target.value = "";
            }}
          />
        </label>
        <small className="muted">{t("الملف بيتبعت في الجروب مع التيم ليدر لوحده.", "It is posted in your group with the team leader on its own.")}</small>
      </div>
      {problem && (
        <div className="note note--high mt" role="alert">
          <Icon name="alert" />
          <div>{problem}</div>
        </div>
      )}
    </div>
  );
}

function Files({ task }: { task: TranslatorTask }) {
  const { t, lang } = usePreferences();
  const { original, translation } = task.files;
  if (original.length === 0 && !task.mine) return null;
  return (
    <div className="task-files mt">
      {original.length > 0 && (
        <div className="task-files__set">
          <div className="label">
            <Icon name="paperclip" size="sm" />
            <span>{t("الملف الأصلي (من العميل)", "Original (from the client)")}</span> <span className="chip chip--sm">{original.length}</span>
          </div>
          <div className="files">
            {original.map((file) => (
              <FileLink key={file.id} file={file} />
            ))}
          </div>
        </div>
      )}
      {task.mine && (
        <div className="task-files__set task-files__set--translation">
          <div className="label">
            <Icon name="file" size="sm" />
            <span>{t("ملف الترجمة (من المترجم)", "Translation (from the translator)")}</span> <span className="chip chip--sm">{translation.length}</span>
          </div>
          {translation.length > 0 ? (
            <div className="files">
              {translation.map((file) => (
                <FileLink key={file.id} file={file} detail={file.at ? (lang === "ar" ? file.at.ar : file.at.en) : undefined} />
              ))}
            </div>
          ) : (
            <div className="muted" style={{ fontSize: ".84rem" }}>
              {t("المترجم لسه مارفعش ملف الترجمة.", "The translator has not uploaded the translation yet.")}
            </div>
          )}
          {task.can_upload && <UploadTranslation code={task.code} />}
        </div>
      )}
    </div>
  );
}

/** «خلصت الترجمة»: asks first, because it sends the job to the leader's review. */
function FinishButton({ task }: { task: TranslatorTask }) {
  const { t } = usePreferences();
  const finish = useFinishTask(task.code);
  const [asking, setAsking] = useState(false);
  const [problem, setProblem] = useState("");

  const confirm = () => {
    setProblem("");
    finish.mutate(undefined, {
      onSuccess: () => setAsking(false),
      onError: (error) => setProblem(taskProblem(error, t)),
    });
  };

  return (
    <>
      {task.translation_missing && (
        <div className="note note--warn">
          <Icon name="upload" />
          <div>{t("ارفع ملف الترجمة من فوق الأول — «خلصت» بتتفتح بعده.", "Upload the translated file above first - Finished opens after it.")}</div>
        </div>
      )}
      <button
        className={`btn btn--primary btn--block${task.translation_missing ? " mt" : ""}`}
        type="button"
        disabled={task.translation_missing}
        onClick={() => {
          setProblem("");
          setAsking(true);
        }}
      >
        <Icon name="check" size="sm" />
        <span>{t("خلصت الترجمة", "Finished")}</span>
      </button>
      {asking && (
        <Modal title={t("خلصت الترجمة؟", "Finished?")} icon="check" busy={finish.isPending} onClose={() => setAsking(false)}>
          <p>{t("متأكد إنك رفعت ملف الترجمة النهائي وخلصت؟", "Is the final translated file uploaded?")}</p>
          {problem && (
            <div className="note note--high" role="alert">
              <Icon name="alert" />
              <div>{problem}</div>
            </div>
          )}
          <div className="row" style={{ marginTop: 14 }}>
            <div className="grow" />
            <button type="button" className="btn" disabled={finish.isPending} onClick={() => setAsking(false)}>
              {t("إلغاء", "Cancel")}
            </button>
            <button type="button" className="btn btn--primary" disabled={finish.isPending} onClick={confirm}>
              <Icon name="check" size="sm" />
              <span>{finish.isPending ? t("بيتبعت...", "Sending...") : t("أيوه، خلصت", "Yes, finished")}</span>
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}

/** The translator asks, the leader answers: days, hours, minutes and why. Nothing moves before the answer. */
function MoreTime({ task, open, onToggle }: { task: TranslatorTask; open: boolean; onToggle: () => void }) {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const ask = useAskMoreTime(task.code);
  const first = useRef<HTMLInputElement>(null);
  const [values, setValues] = useState({ days: "0", hours: "0", minutes: "0", reason: "" });
  const [problem, setProblem] = useState("");
  const { pending, last, can_ask: canAsk } = task.extension;

  useEffect(() => {
    if (open) {
      first.current?.focus();
      first.current?.select();
    }
  }, [open]);

  const number = (raw: string) => {
    const value = Number.parseInt(raw, 10);
    return Number.isFinite(value) && value > 0 ? value : 0;
  };
  const length = number(values.days) * 24 * 60 + number(values.hours) * 60 + number(values.minutes);

  const send = () => {
    setProblem("");
    ask.mutate(
      { days: number(values.days), hours: number(values.hours), minutes: number(values.minutes), reason: values.reason.trim() },
      {
        onSuccess: () => {
          push({ level: "success", title: t("الطلب اتبعت للتيم ليدر", "Sent to your team leader") });
          setValues({ days: "0", hours: "0", minutes: "0", reason: "" });
          onToggle();
        },
        onError: (error) => setProblem(taskProblem(error, t)),
      },
    );
  };

  return (
    <>
      {pending ? (
        <div className="note note--warn mt">
          <Icon name="timer" />
          <div>
            <strong>{t("طلبت وقت إضافي", "You asked for more time")}</strong>
            <div>
              {lengthOfTime(pending.minutes, t)}
              {pending.reason && ` — ${pending.reason}`}
            </div>
            <div className="muted">{t("مستني رد التيم ليدر.", "Waiting for the team leader.")}</div>
          </div>
        </div>
      ) : (
        last && (
          <div className={`note ${last.status === "approved" ? "note--ok" : "note--high"} mt`}>
            <Icon name="timer" />
            <div>
              <div className="note__where mono">
                {last.at ? `${lang === "ar" ? last.at.ar : last.at.en} · ` : ""}
                {lengthOfTime(last.minutes, t)}
              </div>
              <div>
                {last.status === "approved"
                  ? t("التيم ليدر وافق على الوقت الإضافي.", "The team leader approved the extra time.")
                  : t("التيم ليدر رفض الوقت الإضافي.", "The team leader declined the extra time.")}
              </div>
              {last.note && <div className="muted">{last.note}</div>}
            </div>
          </div>
        )
      )}

      {canAsk && (
        <div className="mt" id="more-time">
          <button className="btn btn--block btn--sm" type="button" aria-expanded={open} onClick={onToggle}>
            <Icon name="clock" size="sm" />
            <span>{t("اطلب وقت أطول", "Ask for more time")}</span>
          </button>
          {open && (
            <form
              className="mt"
              onSubmit={(event) => {
                event.preventDefault();
                if (length > 0 && !ask.isPending) send();
              }}
            >
              <div className="row row--tight">
                {(
                  [
                    ["days", t("يوم", "Days"), 14],
                    ["hours", t("ساعة", "Hours"), 23],
                    ["minutes", t("دقيقة", "Minutes"), 59],
                  ] as const
                ).map(([name, label, max], index) => (
                  <label className="grow" key={name}>
                    <small>{label}</small>
                    <input
                      ref={index === 0 ? first : undefined}
                      className="input"
                      type="number"
                      min={0}
                      max={max}
                      dir="ltr"
                      value={values[name]}
                      onChange={(event) => setValues({ ...values, [name]: event.target.value })}
                    />
                  </label>
                ))}
              </div>
              <textarea
                className="input mt"
                rows={2}
                maxLength={300}
                placeholder={t("السبب (اختياري)", "Why (optional)")}
                aria-label={t("السبب", "Reason")}
                value={values.reason}
                onChange={(event) => setValues({ ...values, reason: event.target.value })}
              />
              {problem && (
                <div className="note note--high mt" role="alert">
                  <Icon name="alert" />
                  <div>{problem}</div>
                </div>
              )}
              <button className="btn btn--primary btn--block btn--sm mt" type="submit" disabled={ask.isPending || length === 0}>
                <Icon name="send" size="sm" />
                <span>{ask.isPending ? t("بيتبعت...", "Sending...") : t("ابعت الطلب للتيم ليدر", "Ask the team leader")}</span>
              </button>
            </form>
          )}
        </div>
      )}
    </>
  );
}

function Person({ label, name }: { label: string; name: string | null }) {
  return (
    <div>
      <div className="label">{label}</div>
      <div>{name ?? "—"}</div>
    </div>
  );
}

const HISTORY_BADGE: Record<string, [string, string, string]> = {
  accepted: ["badge--ok", "استلم", "Accepted"],
  expired: ["badge--dead", "مردش", "Expired"],
  declined: ["badge--dead", "رفض", "Declined"],
  pending: ["badge--wait", "مستني", "Pending"],
};

function Task({ task }: { task: TranslatorTask }) {
  const { t, lang } = usePreferences();
  const location = useLocation();
  const [more, setMore] = useState(location.hash === "#more-time");
  const due = task.due ? (lang === "ar" ? task.due.ar : task.due.en) : null;
  const chat = task.chat ? safeInternalPath(task.chat.url) : null;
  const heading = useRef<HTMLDivElement>(null);

  // "Ask for more time" on the desk comes here with the box open, and the box is what the person came for.
  useEffect(() => {
    if (location.hash === "#more-time" && task.extension.can_ask) {
      setMore(true);
      heading.current?.scrollIntoView?.({ block: "start" });
    }
  }, [location.hash, task.extension.can_ask]);

  return (
    <>
      <div className="page-head" ref={heading}>
        <h1 className="mono">{task.code}</h1>
        <StatusBadge status={task.status} />
        <PriorityBadge priority={task.priority} />
        <div className="grow" />
        {/* The translator's own date, which their team leader chose. Never the client's: the server decides which one this is. */}
        <span className={`row row--tight mono ${deadlineClass(task.due_state)}`}>
          <Icon name="clock" size="sm" />
          {due ?? t("من غير ديدلاين", "No deadline")}
        </span>
        <Countdown iso={task.due_iso} state={task.due_state} />
        {task.extension.can_ask && (
          <button className="btn btn--sm" type="button" onClick={() => setMore(true)}>
            <Icon name="clock" size="sm" />
            <span>{t("اطلب وقت أطول", "Ask for more time")}</span>
          </button>
        )}
        {task.extension.pending && task.mine && (
          <span className="chip chip--sm">{t("طلبت وقت أطول - مستني الرد", "More time asked - waiting")}</span>
        )}
      </div>

      <div className="card" style={{ marginBottom: 14 }}>
        <div className="row row--between">
          <div>
            <h2 style={{ margin: 0 }}>
              {task.title} <OriginBadge origin={task.origin} />
            </h2>
            <div className="muted mono" style={{ fontSize: ".82rem" }}>
              {task.client} · {task.part?.source_lang || task.source_lang || "—"} → {task.part?.target_lang || task.target_lang || "—"}
            </div>
          </div>
          <div className="row" style={{ gap: 22 }}>
            <Person label={t("الأوبريشن", "Operation")} name={task.people.operation} />
            <Person label={t("التيم ليدر", "Team leader")} name={task.people.team_lead} />
            <Person label={t("المترجم", "Translator")} name={task.people.translator} />
          </div>
        </div>
        {task.description && (
          <div className="msg-item__text mt" style={{ whiteSpace: "pre-wrap" }}>
            {task.description}
          </div>
        )}
        <PartBox part={task.part} handedIn={task.handed_in} />
        <Files task={task} />
      </div>

      <div className="grid grid--main">
        <div>
          {chat && task.chat && (
            <div className="card">
              <a className="btn btn--block" href={chat}>
                <Icon name="message" size="sm" />
                <span>{lang === "ar" ? task.chat.label_ar : task.chat.label_en}</span>
              </a>
            </div>
          )}
          {task.ai.visible && <AiCheckCard code={task.code} ai={task.ai} />}
        </div>

        <div className="sticky-side">
          <div className="card">
            <div className="card__head">
              <Icon name="list-checks" />
              <h3>{t("الإجراءات", "Actions")}</h3>
            </div>
            {task.mine && task.can_upload && <FinishButton task={task} />}
            {task.under_review && (
              <div className="note note--info">
                <Icon name="info" />
                <div>
                  {task.handed_in && task.status.value === "in_progress"
                    ? t("سلّمت جزءك. مستنيين باقي المترجمين على التاسك.", "Your part is in. Waiting for the other translators on the task.")
                    : t("التيم ليدر بيراجع دلوقتي.", "The team leader is reviewing.")}
                </div>
              </div>
            )}
            {task.mine && <MoreTime task={task} open={more} onToggle={() => setMore((current) => !current)} />}
            {!task.mine && <div className="muted">{t("التاسك دي مش بتاعتك: للقراءة بس.", "This task is not yours: read only.")}</div>}
          </div>

          <div className="card">
            <div className="card__head">
              <Icon name="list-checks" />
              <h3>{t("متطلبات العميل", "Client requirements")}</h3>
              <div className="grow" />
              <span className="chip mono">{task.client}</span>
            </div>
            {task.requirements.map((requirement) => (
              <div className={`note${requirement.kind.value === "dislike" ? " note--high" : ""}`} key={requirement.id}>
                <Icon name={REQUIREMENT_ICON[requirement.kind.value] ?? "pin"} />
                <div>
                  <div className="note__where">
                    {lang === "ar" ? requirement.kind.ar : requirement.kind.en} · {requirement.author ?? "—"}
                  </div>
                  <div>{requirement.text}</div>
                </div>
              </div>
            ))}
            {task.requirements.length === 0 && <div className="muted">{t("مفيش متطلبات مسجلة لحد دلوقتي.", "No requirements recorded yet.")}</div>}
          </div>

          <div className="card">
            <div className="card__head">
              <Icon name="history" />
              <h3>{t("سجل التوزيع", "Assignment history")}</h3>
            </div>
            <ul className="timeline">
              {task.history.map((row) => {
                const [tone, ar, en] = HISTORY_BADGE[row.status] ?? ["", "ملغي", "Cancelled"];
                return (
                  <li key={row.id}>
                    <span className="avatar avatar--sm">{row.initials}</span>
                    <div className="grow">
                      <div>
                        {row.name} <span className="chip">{ROLE_LABELS[row.role]?.[lang === "ar" ? 0 : 1] ?? row.role}</span>
                      </div>
                      <small className="muted mono">{row.at ? (lang === "ar" ? row.at.ar : row.at.en) : ""}</small>
                    </div>
                    <span className={`badge ${tone}`}>{t(ar, en)}</span>
                  </li>
                );
              })}
              {task.history.length === 0 && <li className="muted">{t("لسه مفيش توزيع.", "Not assigned yet.")}</li>}
            </ul>
          </div>
        </div>
      </div>
    </>
  );
}

/** One task, as its translator reads it: the same page the classic interface has, without the cards that are the operation's and the leader's. */
export function TaskPage() {
  const { t } = usePreferences();
  const { code = "" } = useParams();
  const me = useMe();
  // The same people the server lets in (`api_role_required`: translators, and the admin).
  const allowed = me.data !== undefined && (me.data.user.role === "translator" || me.data.user.is_admin);
  const query = useTranslatorTask(code, allowed && code !== "");

  if (me.data && !allowed) return <Navigate to="/" replace />;

  if (query.data) return <Task task={query.data.task} />;

  const missing = query.error instanceof ApiError && query.error.status === 404;
  return (
    <>
      <div className="page-head">
        <h1 className="mono">{code}</h1>
        <div className="grow" />
        <Link className="btn btn--sm" to="/translator">
          <Icon name="arrow-right" size="sm" />
          <span>{t("شغلي", "My work")}</span>
        </Link>
      </div>
      <div className="card">
        {query.isError ? (
          <div className="empty" role="alert">
            <Icon name="alert" size="xl" />
            <span>{missing ? t("التاسك دي مش متاحة ليك.", "This task is not available to you.") : t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
          </div>
        ) : (
          <Loading className="empty" />
        )}
      </div>
    </>
  );
}
