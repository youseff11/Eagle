import { Link, Navigate } from "react-router";
import { useLeadHome, useMe } from "../api/queries";
import type { LeadHome, OpsTaskRow } from "../api/types";
import { deadlineClass, OriginBadge, Rating, StatusBadge } from "../components/Badges";
import { Icon } from "../components/Icon";
import { Presence } from "../components/Presence";
import { usePreferences } from "../i18n/Preferences";

function Counters({ counters }: { counters: LeadHome["counters"] }) {
  const { t } = usePreferences();
  return (
    <div className="grid grid--4" style={{ marginBottom: 18 }}>
      <div className="kpi">
        <div className="kpi__value">{counters.open}</div>
        <div className="kpi__label">{t("تاسكات مفتوحة", "Open tasks")}</div>
      </div>
      <div className="kpi kpi--ok">
        <div className="kpi__value">{counters.free}</div>
        <div className="kpi__label">{t("مترجمين فاضيين", "Free translators")}</div>
      </div>
      <div className="kpi kpi--warn">
        <div className="kpi__value">{counters.busy}</div>
        <div className="kpi__label">{t("مشغولين", "Busy")}</div>
      </div>
      <div className="kpi">
        <div className="kpi__value">{counters.offline}</div>
        <div className="kpi__label">{t("أوفلاين", "Offline")}</div>
      </div>
    </div>
  );
}

/** What the leader does with a task, said on its button: hand it out, review it, or just open it. */
function Row({ task }: { task: OpsTaskRow }) {
  const { t, lang } = usePreferences();
  const status = task.status.value;
  const primary = status === "lead_accepted" || status === "under_review";
  const due = task.due ? (lang === "ar" ? task.due.ar : task.due.en) : null;
  return (
    <tr data-task={task.code}>
      <td>
        <span className="mono">{task.code}</span> <OriginBadge origin={task.origin} />
      </td>
      <td className="mono">{task.client}</td>
      <td>
        <StatusBadge status={task.status} />
      </td>
      <td>{task.translator ?? "—"}</td>
      <td className={`mono ${deadlineClass(task.due_state)}`}>{due ?? "—"}</td>
      <td>
        <Link className={`btn btn--sm${primary ? " btn--primary" : ""}`} to={`/tasks/${encodeURIComponent(task.code)}`}>
          {status === "lead_accepted" ? t("وزّع على مترجم", "Assign a translator") : status === "under_review" ? t("راجع الترجمة", "Review") : t("افتح", "Open")}
        </Link>
      </td>
    </tr>
  );
}

/**
 * The team leader's board: the four numbers, their open tasks (each with the one thing to do next), their team and who
 * is free, and what was closed lately. Everything is theirs: their tasks, their team. The client is a code.
 */
export function LeadHomePage() {
  const { t } = usePreferences();
  const me = useMe();
  // The same people the server lets in (`api_role_required`: the team leader).
  const allowed = me.data !== undefined && (me.data.user.role === "team_lead" || me.data.user.is_admin);
  const query = useLeadHome(allowed);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  const data = query.data;

  return (
    <>
      <div className="page-head">
        <h1>{t("لوحة التيم ليدر", "Team leader board")}</h1>
      </div>

      {data && <Counters counters={data.counters} />}

      {data ? (
        <div className="grid grid--main">
          <div className="card">
            <div className="card__head">
              <Icon name="target" />
              <h2>{t("التاسكات اللي عندي", "My tasks")}</h2>
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("الكود", "Code")}</th>
                    <th>{t("العميل", "Client")}</th>
                    <th>{t("الحالة", "Status")}</th>
                    <th>{t("المترجم", "Translator")}</th>
                    <th>{t("الديدلاين", "Deadline")}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.tasks.map((task) => (
                    <Row key={task.code} task={task} />
                  ))}
                  {data.tasks.length === 0 && (
                    <tr>
                      <td colSpan={6} className="empty">
                        <Icon name="target" size="xl" />
                        <span>{t("مفيش تاسكات مفتوحة.", "No open tasks.")}</span>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="sticky-side">
            <div className="card">
              <div className="card__head">
                <Icon name="users" />
                <h3>{t("فريقي", "My team")}</h3>
                <div className="grow" />
                <Link className="btn btn--sm" to="/lead/translators">
                  {t("اللوحة الكاملة", "Full board")}
                </Link>
              </div>
              <ul className="timeline">
                {data.team.map((member) => (
                  <li key={member.id} data-member={member.id}>
                    <div className="avatar avatar--sm">{member.initials}</div>
                    <div className="grow">
                      <div>{member.name}</div>
                      <small className="muted mono">{member.languages}</small>
                    </div>
                    <Rating value={member.rating} />
                    <Presence state={member.state} seen={member.seen} />
                  </li>
                ))}
                {data.team.length === 0 && <li className="muted">{t("مفيش مترجمين تحتك.", "No translators assigned to you.")}</li>}
              </ul>
            </div>

            <div className="card">
              <div className="card__head">
                <Icon name="history" />
                <h3>{t("اتقفلت مؤخرًا", "Recently closed")}</h3>
              </div>
              <ul className="timeline">
                {data.closed.map((task) => (
                  <li key={task.code}>
                    <Link className="mono grow" to={`/tasks/${encodeURIComponent(task.code)}`}>
                      {task.code}
                    </Link>
                    <StatusBadge status={task.status} />
                  </li>
                ))}
                {data.closed.length === 0 && <li className="muted">{t("لسه مفيش.", "Nothing yet.")}</li>}
              </ul>
            </div>
          </div>
        </div>
      ) : query.isError ? (
        <div className="card empty" role="alert">
          <Icon name="alert" size="xl" />
          <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
        </div>
      ) : (
        <div className="card empty">
          <Icon name="refresh" size="xl" />
          <span>{t("بيحمّل...", "Loading...")}</span>
        </div>
      )}
    </>
  );
}
