import { Navigate } from "react-router";
import { useMe, useTranslatorHome } from "../api/queries";
import type { DeskTask, Labelled, TranslatorHomeResponse } from "../api/types";
import { Icon } from "../components/Icon";
import { usePreferences } from "../i18n/Preferences";
import { safeInternalPath } from "../lib/safeUrl";

/** The badge looks `static/css/app.css` has. The server names one; anything else is drawn plain. */
const TONES = new Set(["new", "wait", "info", "work", "review", "ok", "done", "dead"]);
const PRIORITIES = new Set(["low", "normal", "high", "urgent"]);
const DEADLINE_STATES = new Set(["none", "ok", "soon", "late", "done"]);

function StatusBadge({ status }: { status: Labelled & { tone: string } }) {
  const { lang } = usePreferences();
  const tone = TONES.has(status.tone) ? status.tone : "new";
  return (
    <span className={`badge badge--${tone}`}>
      <i className="badge__dot" />
      <span>{lang === "ar" ? status.ar : status.en}</span>
    </span>
  );
}

function Rating({ value }: { value: number }) {
  return (
    <span className="rating" title={`${value.toFixed(3)} / 5`}>
      <Icon name="star" size="sm" filled />
      <b>{value.toFixed(2)}</b>
      <i>/5</i>
    </span>
  );
}

function TaskRow({ task }: { task: DeskTask }) {
  const { t, lang } = usePreferences();
  // The server wrote the address; it is drawn only if it is a path on this site.
  const href = safeInternalPath(task.url);
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
            {PRIORITIES.has(task.priority.value) && (
              <span className={`badge badge--prio-${task.priority.value}`}>
                {lang === "ar" ? task.priority.ar : task.priority.en}
              </span>
            )}
          </div>
          {/* The translator's own date, which their team leader set and which is often earlier than the
              client's. Never the client's: the server decides which one this is. */}
          <span className={`row row--tight mono deadline--${DEADLINE_STATES.has(task.due_state) ? task.due_state : "none"}`}>
            <Icon name="clock" size="sm" />
            {due ?? t("من غير ديدلاين", "No deadline")}
          </span>
        </div>
        <div>
          {task.title}{" "}
          {task.origin && (
            <span className={`badge badge--origin badge--${task.origin.value === "email" ? "mail" : "wa"}`}>
              <Icon name={task.origin.icon} size="sm" />
              <span>{lang === "ar" ? task.origin.ar : task.origin.en}</span>
            </span>
          )}
        </div>
        <small className="muted mono">
          {task.client} · {task.source_lang} → {task.target_lang}
        </small>
        {href && (
          <div className="row desk-actions">
            <a className="btn btn--sm btn--primary" href={href}>
              <Icon name="arrow-right" size="sm" />
              <span>{t("افتح التاسك والشات", "Open task & chat")}</span>
            </a>
            {task.can_ask_more_time && (
              <a className="btn btn--sm" href={`${href}#more-time`}>
                <Icon name="clock" size="sm" />
                <span>{t("اطلب وقت أطول", "Ask for more time")}</span>
              </a>
            )}
          </div>
        )}
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
            {data.done.map((task) => {
              const href = safeInternalPath(task.url);
              return (
                <li key={task.code}>
                  {href ? (
                    <a className="mono grow" href={href}>
                      {task.code}
                    </a>
                  ) : (
                    <span className="mono grow">{task.code}</span>
                  )}
                  <StatusBadge status={task.status} />
                </li>
              );
            })}
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
