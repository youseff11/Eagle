import { Loading } from "../components/Loading";
import { Link, Navigate } from "react-router";
import { useMe, useTeam } from "../api/queries";
import type { TeamResponse } from "../api/types";
import { Rating } from "../components/Badges";
import { Icon } from "../components/Icon";
import { Presence } from "../components/Presence";
import { usePreferences } from "../i18n/Preferences";

type Lead = TeamResponse["leads"][number];

function LeadCard({ lead }: { lead: Lead }) {
  const { t } = usePreferences();
  return (
    <div className="card" data-lead={lead.id}>
      <div className="card__head">
        <div className="avatar avatar--brand">{lead.initials}</div>
        <div>
          <h3 style={{ margin: 0 }}>{lead.name}</h3>
          <div className="row row--tight">
            <span className={`dot ${lead.online ? "dot--on" : "dot--off"}`} />
            <small>{lead.online ? t("نشط دلوقتي", "Online now") : t("أوفلاين", "Offline")}</small>
            <Rating value={lead.rating} />
          </div>
        </div>
        <div className="grow" />
        <span className="chip">
          {t("تاسكاته", "Tasks")} {lead.tasks}
        </span>
      </div>

      <div className="grid grid--3" style={{ marginBottom: 14 }}>
        <div className="kpi kpi--ok" style={{ padding: "11px 13px" }}>
          <div className="kpi__value">{lead.counts.free}</div>
          <div className="kpi__label">{t("فاضيين", "Free")}</div>
        </div>
        <div className="kpi kpi--warn" style={{ padding: "11px 13px" }}>
          <div className="kpi__value">{lead.counts.busy}</div>
          <div className="kpi__label">{t("مشغولين", "Busy")}</div>
        </div>
        <div className="kpi" style={{ padding: "11px 13px" }}>
          <div className="kpi__value">{lead.counts.offline}</div>
          <div className="kpi__label">{t("أوفلاين", "Offline")}</div>
        </div>
      </div>

      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>{t("المترجم", "Translator")}</th>
              <th>{t("الحالة", "State")}</th>
              <th>{t("التاسك الحالية", "Current task")}</th>
              <th>{t("التقييم", "Rating")}</th>
            </tr>
          </thead>
          <tbody>
            {lead.members.map((member) => (
              <tr key={member.id} data-member={member.id}>
                <td>
                  <div className="row row--tight">
                    <div className="avatar avatar--sm">{member.initials}</div>
                    <div>
                      <div>{member.name}</div>
                      <small className="muted mono">{member.languages}</small>
                    </div>
                  </div>
                </td>
                <td>
                  <Presence state={member.state} seen={member.seen} />
                </td>
                <td>
                  {member.tasks.map((code) => (
                    <Link key={code} className="badge badge--work mono" to={`/tasks/${encodeURIComponent(code)}`}>
                      {code}
                    </Link>
                  ))}
                  {member.tasks.length === 0 && <span className="muted">—</span>}
                </td>
                <td>
                  <Rating value={member.rating} />
                </td>
              </tr>
            ))}
            {lead.members.length === 0 && (
              <tr>
                <td colSpan={4} className="muted">
                  {t("مفيش مترجمين تحت التيم ليدر ده.", "No translators under this team leader.")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** The team leaders and their teams: who is free, who is busy, who is offline, and with what. */
export function TeamPage() {
  const { t } = usePreferences();
  const me = useMe();
  // The same people the server lets in (`api_role_required`: the operation, and the admin).
  const allowed = me.data !== undefined && (me.data.user.role === "operation" || me.data.user.is_admin);
  const query = useTeam(allowed);

  if (me.data && !allowed) return <Navigate to="/" replace />;

  const data = query.data;
  return (
    <>
      <div className="page-head">
        <h1>{t("حالة التيم ليدرز والفرق", "Team leaders & their teams")}</h1>
        <span className="page-head__sub">
          {t("الحالة محسوبة من الشيفتات المسجلة في بروفايل كل واحد.", "Presence is computed from each person's configured shifts.")}
        </span>
      </div>

      {data ? (
        <div className="grid grid--2">
          {data.leads.map((lead) => (
            <LeadCard key={lead.id} lead={lead} />
          ))}
          {data.leads.length === 0 && (
            <div className="card empty">
              <Icon name="users" size="xl" />
              <span>{t("مفيش تيم ليدرز مسجلين.", "No team leaders yet.")}</span>
            </div>
          )}
        </div>
      ) : (
        <div className="card">
          {query.isError ? (
            <div className="empty" role="alert">
              <Icon name="alert" size="xl" />
              <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
            </div>
          ) : (
            <Loading className="empty" />
          )}
        </div>
      )}
    </>
  );
}
