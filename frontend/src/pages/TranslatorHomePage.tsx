import { Link, Navigate } from "react-router";
import { useMe, useTranslatorHome } from "../api/queries";
import type { DeskTask, TranslatorHomeResponse } from "../api/types";
import { deadlineClass, OriginBadge, PriorityBadge, Rating, StatusBadge } from "../components/Badges";
import { Icon } from "../components/Icon";
import { usePreferences } from "../i18n/Preferences";

function TaskRow({ task }: { task: DeskTask }) {
  const { t, lang } = usePreferences();
  // The task page is a route of this app, made from the code: nothing the server wrote goes into the address.
  const to = `/tasks/${encodeURIComponent(task.code)}`;
  const due = task.due ? (lang === "ar" ? task.due.ar : task.due.en) : null;

  return (
    <div className="msg-item" data-task={task.code}>
      <div className="avatar avatar--brand">
        <Icon name="file" size="sm" />
      </div>
      <div className="msg-item__body">
        <div className="row row--between">
          <div className="row row--tight">
            <strong className="mono">{task.code}</strong>
            <StatusBadge status={task.status} />
            <PriorityBadge priority={task.priority} />
          </div>
          {/* The translator's own date, which their team leader set and which is often earlier than the
              client's. Never the client's: the server decides which one this is. */}
          <span className={`row row--tight mono ${deadlineClass(task.due_state)}`}>
            <Icon name="clock" size="sm" />
            {due ?? t("من غير ديدلاين", "No deadline")}
          </span>
        </div>
        <div>
          {task.title}{" "}
          <OriginBadge origin={task.origin} />
        </div>
        <small className="muted mono">
          {task.client} · {task.source_lang} → {task.target_lang}
        </small>
        <div className="row desk-actions">
          <Link className="btn btn--sm btn--primary" to={to}>
            <Icon name="arrow-right" size="sm" />
            <span>{t("افتح التاسك", "Open the task")}</span>
          </Link>
          {task.can_ask_more_time && (
            <Link className="btn btn--sm" to={{ pathname: to, hash: "#more-time" }}>
              <Icon name="clock" size="sm" />
              <span>{t("اطلب وقت أطول", "Ask for more time")}</span>
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}

function Desk({ data }: { data: TranslatorHomeResponse }) {
  const { t, lang } = usePreferences();
  return (
    <div className="grid grid--main">
      <div className="card">
        <div className="card__head">
          <Icon name="pen" />
          <h2>{t("التاسكات الحالية", "Current tasks")}</h2>
        </div>
        {data.open.map((task) => (
          <TaskRow key={task.code} task={task} />
        ))}
        {data.open.length === 0 && (
          <div className="empty">
            <Icon name="check-circle" size="xl" />
            <span>{t("مفيش شغل عليك دلوقتي.", "Nothing on your desk right now.")}</span>
          </div>
        )}
      </div>

      <div className="sticky-side">
        <div className="card">
          <div className="card__head">
            <Icon name="star" />
            <h3>{t("سجل التقييم", "Rating history")}</h3>
          </div>
          <ul className="timeline">
            {data.rating_events.map((event, index) => (
              <li key={index}>
                <span className="badge badge--dead mono">{event.delta}</span>
                <span>{lang === "ar" ? event.reason_ar : event.reason_en || event.reason_ar}</span>
              </li>
            ))}
            {data.rating_events.length === 0 && (
              <li className="muted">{t("تقييمك كامل ومفيش خصومات.", "Full rating, no penalties.")}</li>
            )}
          </ul>
        </div>

        <div className="card">
          <div className="card__head">
            <Icon name="history" />
            <h3>{t("اتقفلت مؤخرًا", "Recently closed")}</h3>
          </div>
          <ul className="timeline">
            {data.done.map((task) => (
              <li key={task.code}>
                <Link className="mono grow" to={`/tasks/${encodeURIComponent(task.code)}`}>
                  {task.code}
                </Link>
                <StatusBadge status={task.status} />
              </li>
            ))}
            {data.done.length === 0 && <li className="muted">{t("لسه مفيش.", "Nothing yet.")}</li>}
          </ul>
        </div>
      </div>
    </div>
  );
}

export function TranslatorHomePage() {
  const { t } = usePreferences();
  const me = useMe();
  // The same people the server lets in (`api_role_required`: translators, and the admin).
  const allowed = me.data !== undefined && (me.data.user.role === "translator" || me.data.user.is_admin);
  const query = useTranslatorHome(allowed);

  if (me.data && !allowed) return <Navigate to="/" replace />;

  return (
    <>
      <div className="page-head">
        <h1>{t("شغلي", "My work")}</h1>
        <div className="grow" />
        {query.data && <Rating value={query.data.rating} />}
      </div>

      {query.data ? (
        <Desk data={query.data} />
      ) : (
        <div className="card">
          {query.isError ? (
            <div className="empty" role="alert">
              <Icon name="alert" size="xl" />
              <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
            </div>
          ) : (
            <div className="empty">
              <Icon name="refresh" size="xl" />
              <span>{t("بيحمّل...", "Loading...")}</span>
            </div>
          )}
        </div>
      )}
    </>
  );
}
