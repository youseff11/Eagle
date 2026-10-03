import { Link, Navigate, useParams } from "react-router";
import { ApiError } from "../api/client";
import { useAddClientRequirement } from "../api/opsActions";
import { useClient, useMe } from "../api/queries";
import type { ClientResponse } from "../api/types";
import { OriginBadge, StatusBadge } from "../components/Badges";
import { Icon } from "../components/Icon";
import { Requirements } from "../components/ops/Requirements";
import { usePreferences } from "../i18n/Preferences";
import { safeInternalPath } from "../lib/safeUrl";

function Lines({ values }: { values: string[] }) {
  if (values.length === 0) return <>—</>;
  return (
    <>
      {values.map((value, index) => (
        <span key={value}>
          {index > 0 && <br />}
          {value}
        </span>
      ))}
    </>
  );
}

/** Who the client is. Drawn only when the server sent it: it sends it to the people who may know (and logs that it did). */
function IdentityCard({ client }: { client: ClientResponse["client"] }) {
  const { t } = usePreferences();
  return (
    <div className="card">
      <div className="card__head">
        <Icon name="building" />
        <h3>{t("بيانات العميل", "Client identity")}</h3>
      </div>
      <div className="kv">
        <span>{t("الاسم", "Name")}</span>
        <strong>{client.name || "—"}</strong>
      </div>
      <div className="kv">
        <span>{t("الشركة", "Company")}</span>
        <strong>{client.company || "—"}</strong>
      </div>
      <div className="kv">
        <span>{t("التليفون", "Phone")}</span>
        <strong className="mono" dir="ltr">
          <Lines values={client.phones ?? []} />
        </strong>
      </div>
      <div className="kv">
        <span>{t("الإيميل", "Email")}</span>
        <strong className="mono" dir="ltr">
          <Lines values={client.emails ?? []} />
        </strong>
      </div>
      {/* What the admin wrote for the admin alone: the server sends it to nobody else. */}
      {client.admin_notes && <div className="mt muted">{client.admin_notes}</div>}
    </div>
  );
}

function Activity({ activity }: { activity: NonNullable<ClientResponse["activity"]> }) {
  const { t, lang } = usePreferences();
  return (
    <div className="card">
      <div className="card__head">
        <Icon name="chart" />
        <h3>{t("متابعة العميل", "Client activity")}</h3>
      </div>
      <p className="muted" style={{ fontSize: ".8rem" }}>
        {t("متابعة بس - التنفيذ مع الأوبريشن والفلوس مع الحسابات.", "Follow-up only - delivery belongs to Operations, money to Accounting.")}
      </p>
      <div className="kv">
        <span>{t("شغالة دلوقتي", "In progress")}</span>
        <strong className="mono">{activity.active}</strong>
      </div>
      <div className="kv">
        <span>{t("اتسلّمت", "Delivered")}</span>
        <strong className="mono">{activity.delivered}</strong>
      </div>
      <div className="kv">
        <span>{t("إجمالي المشاريع", "All projects")}</span>
        <strong className="mono">{activity.total}</strong>
      </div>
      <div className="kv">
        <span>{t("آخر مشروع", "Latest project")}</span>
        <strong className="mono">{activity.last ? (lang === "ar" ? activity.last.ar : activity.last.en) : "-"}</strong>
      </div>
    </div>
  );
}

/**
 * One client: the requirements (and the form that adds one), who the client is for whoever may know, and the newest tasks.
 * The server decides what is in the answer; this draws what is there.
 */
export function ClientPage() {
  const { t } = usePreferences();
  const me = useMe();
  const { code = "" } = useParams();
  const allowed = me.data !== undefined && (me.data.user.role === "operation" || me.data.user.role === "sales" || me.data.user.is_admin);
  const query = useClient(code, allowed);
  const add = useAddClientRequirement(code);

  if (me.data && !allowed) return <Navigate to="/" replace />;

  const data = query.data;
  const notFound = query.error instanceof ApiError && query.error.status === 404;
  // An address the server wrote: followed only if it is a path on this site.
  const edit = data?.edit_url ? safeInternalPath(data.edit_url) : null;

  return (
    <>
      <div className="page-head">
        <Link className="btn btn--sm" to="/clients" title={t("رجوع للعملاء", "Back to the clients")}>
          <Icon name="arrow-right" size="sm" />
          <span>{t("العملاء", "Clients")}</span>
        </Link>
        <h1 className="mono">{code}</h1>
        {data &&
          (data.sees_identity ? (
            <span className="badge badge--new">
              {data.client.name} {data.client.company}
            </span>
          ) : (
            <span className="badge">
              <Icon name="shield" size="sm" />
              <span>{t("بيانات العميل مخفية", "Client identity hidden")}</span>
            </span>
          ))}
        <div className="grow" />
        {edit && (
          <a className="btn btn--sm" href={edit}>
            {t("تعديل البيانات", "Edit details")}
          </a>
        )}
      </div>

      {data ? (
        <div className="grid grid--main">
          <div className="card">
            <div className="card__head">
              <Icon name="list-checks" />
              <h3>{t("المتطلبات والملاحظات", "Requirements & notes")}</h3>
            </div>
            <Requirements requirements={data.requirements} add={data.may_edit ? add : null} />
          </div>

          <div className="sticky-side">
            {data.sees_identity && <IdentityCard client={data.client} />}
            {data.activity && <Activity activity={data.activity} />}
            <div className="card">
              <div className="card__head">
                <Icon name="layers" />
                <h3>{t("تاسكات العميل", "Client tasks")}</h3>
              </div>
              <ul className="timeline">
                {data.tasks.map((task) => (
                  <li key={task.code}>
                    {data.may_edit ? (
                      <Link className="mono" to={`/tasks/${encodeURIComponent(task.code)}`}>
                        {task.code}
                      </Link>
                    ) : (
                      <span className="mono">{task.code}</span>
                    )}
                    <span className="grow">
                      {task.title.length > 26 ? `${task.title.slice(0, 26)}…` : task.title} <OriginBadge origin={task.origin} />
                    </span>
                    <StatusBadge status={task.status} />
                  </li>
                ))}
                {data.tasks.length === 0 && <li className="muted">{t("مفيش تاسكات.", "No tasks.")}</li>}
              </ul>
            </div>
          </div>
        </div>
      ) : notFound ? (
        <div className="card empty" role="alert">
          <Icon name="tag" size="xl" />
          <span>{t("العميل ده مش موجود.", "That client does not exist.")}</span>
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
