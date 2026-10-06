import { Loading } from "../components/Loading";
import type { ReactNode } from "react";
import { Link, Navigate, useSearchParams } from "react-router";
import { useMe, useTasks } from "../api/queries";
import type { OpsTaskRow, TasksResponse } from "../api/types";
import { deadlineClass, OriginBadge, PriorityBadge, StatusBadge } from "../components/Badges";
import { Icon } from "../components/Icon";
import { usePreferences } from "../i18n/Preferences";

function Counters({ counters }: { counters: TasksResponse["counters"] }) {
  const { t } = usePreferences();
  return (
    <div className="grid grid--4" style={{ marginBottom: 18 }}>
      <div className="kpi">
        <div className="kpi__value">{counters.new}</div>
        <div className="kpi__label">{t("جديدة — محتاجة توزيع", "New — need assigning")}</div>
      </div>
      <div className="kpi kpi--warn">
        <div className="kpi__value">{counters.open}</div>
        <div className="kpi__label">{t("شغالة دلوقتي", "Currently open")}</div>
      </div>
      <div className="kpi">
        <div className="kpi__value">{counters.review}</div>
        <div className="kpi__label">{t("تحت المراجعة", "Under review")}</div>
      </div>
      <div className="kpi kpi--ok">
        <div className="kpi__value">{counters.ready}</div>
        <div className="kpi__label">{t("جاهزة للتسليم", "Ready to deliver")}</div>
      </div>
    </div>
  );
}

function Row({ task }: { task: OpsTaskRow }) {
  const { t, lang } = usePreferences();
  const due = task.due ? (lang === "ar" ? task.due.ar : task.due.en) : null;
  return (
    <tr data-task={task.code}>
      <td className="mono">{task.code}</td>
      <td>
        {task.title} <OriginBadge origin={task.origin} /> <PriorityBadge priority={task.priority} />
      </td>
      <td className="mono">{task.client}</td>
      <td>
        <StatusBadge status={task.status} />
      </td>
      <td>{task.team_lead ?? "—"}</td>
      <td>{task.translator ?? "—"}</td>
      <td className={`mono ${deadlineClass(task.due_state)}`}>{due ?? "—"}</td>
      <td>
        <Link className="btn btn--sm" to={`/tasks/${encodeURIComponent(task.code)}`}>
          {t("افتح", "Open")}
        </Link>
      </td>
    </tr>
  );
}

/** The operation's task list: the four numbers, a tab for every status, and the newest two hundred tasks. */
export function TasksPage() {
  const { t } = usePreferences();
  const me = useMe();
  const [params, setParams] = useSearchParams();
  // The address is the person's to type: it goes to the server only if it is a status we know of (the server checks too).
  const asked = params.get("status") ?? "";
  const status = /^[a-z_]{1,30}$/.test(asked) ? asked : "";
  // The same people the server lets in (`api_role_required`: the operation, technical support, and the admin).
  const allowed = me.data !== undefined && (me.data.user.role === "operation" || me.data.user.role === "support" || me.data.user.is_admin);
  // Making a task is the operation's: technical support only looks.
  const canCreate = me.data?.user.role === "operation" || me.data?.user.is_admin === true;
  const query = useTasks(status, allowed);

  if (me.data && !allowed) return <Navigate to="/" replace />;

  const data = query.data;
  const tab = (value: string, label: ReactNode) => (
    <button
      key={value}
      type="button"
      role="tab"
      aria-selected={status === value}
      className={`tab${status === value ? " is-active" : ""}`}
      onClick={() => setParams(value ? { status: value } : {})}
    >
      {label}
    </button>
  );

  return (
    <>
      <div className="page-head">
        <h1>{t("التاسكات", "Tasks")}</h1>
        <div className="grow" />
        {canCreate && (
          <Link className="btn btn--primary" to="/tasks/new">
            <Icon name="plus" size="sm" />
            <span>{t("تاسك جديدة", "New task")}</span>
          </Link>
        )}
      </div>

      {data && <Counters counters={data.counters} />}

      <div className="tabs" role="tablist">
        {tab("", t("الكل", "All"))}
        {tab("open", t("المفتوحة", "Open"))}
        {(data?.statuses ?? []).map((one) => tab(one.value, <StatusBadge status={one} />))}
      </div>

      <div className="card">
        {data ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("الكود", "Code")}</th>
                  <th>{t("العنوان", "Title")}</th>
                  <th>{t("العميل", "Client")}</th>
                  <th>{t("الحالة", "Status")}</th>
                  <th>{t("التيم ليدر", "Team leader")}</th>
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
                    <td colSpan={8} className="empty">
                      <Icon name="layers" size="xl" />
                      <span>{t("مفيش تاسكات.", "No tasks.")}</span>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        ) : query.isError ? (
          <div className="empty" role="alert">
            <Icon name="alert" size="xl" />
            <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
          </div>
        ) : (
          <Loading className="empty" />
        )}
      </div>
    </>
  );
}
