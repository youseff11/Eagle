import { Loading } from "../components/Loading";
import { Link, Navigate, useParams } from "react-router";
import { ApiError } from "../api/client";
import { useMe, useOpsTask } from "../api/queries";
import type { OpsTask, TaskFile } from "../api/types";
import { deadlineClass, OriginBadge, PriorityBadge, StatusBadge } from "../components/Badges";
import { Countdown } from "../components/Countdown";
import { Icon } from "../components/Icon";
import { AiNotesCard } from "../components/ai/AiNotesCard";
import { AssignTranslatorBox, CloseTranslationButton, ExtensionBox, PartWordsBox, ReviewButton, ReviewedFilesBox, TranslatorDeadlineBox } from "../components/ops/LeadActions";
import { AddMemberBox, AssignLeadBox, CancelButton, DeadlineBox, DeliverBox, TakeOverBox } from "../components/ops/TaskActions";
import { DeliveriesCard, HistoryCard, LanguagesCard, MessagesCard, PartsCard, RequirementsCard, WordCountCard } from "../components/ops/TaskExtras";
import { usePreferences } from "../i18n/Preferences";
import { safeInternalPath } from "../lib/safeUrl";

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

function Person({ label, name }: { label: string; name: string | null }) {
  return (
    <div>
      <div className="label">{label}</div>
      <div>{name ?? "—"}</div>
    </div>
  );
}

function Files({ task }: { task: OpsTask }) {
  const { t, lang } = usePreferences();
  const { original, translation } = task.files;
  const reviewed = task.files.reviewed ?? [];
  if (original.length === 0 && !task.people.translator) return null;
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
      {task.people.translator && (
        <div className="task-files__set task-files__set--translation">
          <div className="label">
            <Icon name="file" size="sm" />
            <span>{t("ملف الترجمة (من المترجم)", "Translation (from the translator)")}</span> <span className="chip chip--sm">{translation.length}</span>
          </div>
          {translation.length > 0 ? (
            <div className="files">
              {translation.map((file) => (
                <FileLink
                  key={file.id}
                  file={file}
                  detail={[task.parts.length > 1 ? file.by : null, file.at ? (lang === "ar" ? file.at.ar : file.at.en) : null].filter(Boolean).join(" · ") || undefined}
                />
              ))}
            </div>
          ) : (
            <div className="muted" style={{ fontSize: ".84rem" }}>
              {t("المترجم لسه مارفعش ملف الترجمة.", "The translator has not uploaded the translation yet.")}
            </div>
          )}
        </div>
      )}
      {reviewed.length > 0 && (
        <div className="task-files__set task-files__set--reviewed">
          <div className="label">
            <Icon name="check-circle" size="sm" />
            <span>{t("بعد مراجعة التيم ليدر (النسخة النهائية)", "After the team leader's review (the final version)")}</span> <span className="chip chip--sm">{reviewed.length}</span>
          </div>
          <div className="files">
            {reviewed.map((file) => (
              <FileLink key={file.id} file={file} detail={file.at ? (lang === "ar" ? file.at.ar : file.at.en) : undefined} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Task({ task }: { task: OpsTask }) {
  const { t, lang } = usePreferences();
  // The AI's notes are the review's owner's: the admin, and the task's own team leader (the door refuses everybody else).
  const account = useMe().data?.user;
  const reviewer = account?.is_admin === true || account?.role === "team_lead";
  const { can, lead } = task;
  // The leader's own tools, drawn only when there is one to use; and the card only when anything is in it.
  const leadTools =
    lead !== null &&
    (lead.can_assign || lead.can_set_translator_deadline || lead.can_review || lead.can_set_part_words === true || lead.can_upload_reviewed === true || lead.can_close_translation === true || lead.extension !== null);
  const hasActions = can.assign_lead || can.take_over || can.deliver || can.set_deadline || can.add_member || can.cancel || leadTools;
  const due = task.due ? (lang === "ar" ? task.due.ar : task.due.en) : null;
  const chat = task.chat ? safeInternalPath(task.chat.url) : null;
  const clientChat = task.client_chat_url ? safeInternalPath(task.client_chat_url) : null;

  return (
    <>
      <div className="page-head">
        <h1 className="mono">{task.code}</h1>
        <StatusBadge status={task.status} />
        <PriorityBadge priority={task.priority} />
        <div className="grow" />
        {/* The client's date: the operation answers for the promise, and counts down to it. */}
        <span className={`row row--tight mono ${deadlineClass(task.due_state)}`}>
          <Icon name="clock" size="sm" />
          {due ?? t("من غير ديدلاين", "No deadline")}
        </span>
        <Countdown iso={task.due_iso} state={task.due_state} />
        {/* The leader gave the translator a shorter date: what they work to, counted down too. */}
        {task.translator_due && (
          <span className="chip chip--sm" title={t("الديدلاين اللي المترجم شايفه", "What the translator was given")}>
            <Icon name="pen" size="sm" />
            <span className="mono">{lang === "ar" ? task.translator_due.ar : task.translator_due.en}</span>
          </span>
        )}
        <Countdown iso={task.translator_due_iso} state="ok" label={t("المترجم", "Translator")} />
      </div>

      {reviewer && <AiNotesCard code={task.code} />}

      <div className="card" style={{ marginBottom: 14 }}>
        <div className="row row--between">
          <div>
            <h2 style={{ margin: 0 }}>
              {task.title} <OriginBadge origin={task.origin} />
            </h2>
            <div className="muted mono" style={{ fontSize: ".82rem" }}>
              {task.client} · {task.source_lang || "—"} → {task.target_lang || "—"}
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
        {/* The same material, a new job: another language, a second copy, a revised request. The operation's. */}
        {can.new_request && (
          <div className="row mt">
            <Link className="btn btn--sm" to={{ pathname: "/tasks/new", search: `?from=${encodeURIComponent(task.code)}` }}>
              <Icon name="plus" size="sm" />
              <span>{t("طلب جديد على نفس الملفات", "New request, same files")}</span>
            </Link>
          </div>
        )}
        {!task.watching && <Files task={task} />}
      </div>

      {task.waiting_for && (
        <div className="note note--warn" style={{ marginBottom: 14 }}>
          <Icon name="timer" />
          <div className="row row--tight">
            <strong>{task.waiting_for.name}</strong>
            <span>{t("لسه ماأكدش الاستلام — العداد شغال.", "has not confirmed yet — the timer is running.")}</span>
            <span className="badge badge--wait mono">{task.waiting_for.seconds_left}s</span>
          </div>
        </div>
      )}

      <div className="grid grid--main">
        <div>
          {(chat || clientChat) && (
            <div className="card">
              <div className="row row--tight" style={{ flexWrap: "wrap" }}>
                {chat && task.chat && (
                  <a className="btn" href={chat}>
                    <Icon name="message" size="sm" />
                    <span>{lang === "ar" ? task.chat.label_ar : task.chat.label_en}</span>
                  </a>
                )}
                {clientChat && (
                  <a className="btn" href={clientChat}>
                    <Icon name="phone" size="sm" />
                    <span>{t("المحادثة مع العميل", "The conversation with the client")}</span>
                  </a>
                )}
              </div>
            </div>
          )}
          <PartsCard task={task} />
          {!task.watching && <MessagesCard task={task} />}
        </div>

        <div className="sticky-side">
          {hasActions && (
            <div className="card">
              <div className="card__head">
                <Icon name="list-checks" />
                <h3>{t("الإجراءات", "Actions")}</h3>
              </div>
              {can.assign_lead && <AssignLeadBox task={task} />}
              {can.take_over && <TakeOverBox task={task} />}
              {can.deliver && <DeliverBox task={task} />}
              {can.set_deadline && <DeadlineBox task={task} />}
              <AddMemberBox task={task} />
              <CancelButton task={task} />
              <AssignTranslatorBox task={task} />
              <TranslatorDeadlineBox task={task} />
              <ExtensionBox task={task} />
              <PartWordsBox task={task} />
              <ReviewedFilesBox task={task} />
              <CloseTranslationButton task={task} />
              <ReviewButton task={task} />
            </div>
          )}
          {can.set_languages === true && <LanguagesCard task={task} />}
          {can.set_words && <WordCountCard task={task} />}
          {!task.watching && <RequirementsCard task={task} />}
          {!task.watching && <DeliveriesCard task={task} />}
          <HistoryCard task={task} />
        </div>
      </div>
    </>
  );
}

/** One task, as the operation reads it: what it is, where it stands, what can be done with it next. */
export function OperationTaskPage() {
  const { t } = usePreferences();
  const { code = "" } = useParams();
  const me = useMe();
  // The same people the server lets in (`api_role_required`: the operation, the team leader of the task, and the admin).
  const allowed =
    me.data !== undefined && (me.data.user.role === "operation" || me.data.user.role === "team_lead" || me.data.user.role === "support" || me.data.user.is_admin);
  const query = useOpsTask(code, allowed && code !== "");

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (query.data) return <Task task={query.data.task} />;

  const missing = query.error instanceof ApiError && query.error.status === 404;
  return (
    <>
      <div className="page-head">
        <h1 className="mono">{code}</h1>
        <div className="grow" />
        <Link className="btn btn--sm" to="/tasks">
          <Icon name="arrow-right" size="sm" />
          <span>{t("التاسكات", "Tasks")}</span>
        </Link>
      </div>
      <div className="card">
        {query.isError ? (
          <div className="empty" role="alert">
            <Icon name="alert" size="xl" />
            <span>{missing ? t("التاسك دي مش موجودة.", "This task does not exist.") : t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
          </div>
        ) : (
          <Loading className="empty" />
        )}
      </div>
    </>
  );
}
