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
  const { free, busy, offline } = lead.counts;
  const total = free + busy + offline;
  return (
    <div className="card team-card" data-lead={lead.id}>
      <div className="card__head team-card__head">
        <div className="avatar avatar--lg avatar--brand">{lead.initials}</div>
        <div className="team-card__who">
          <h3>{lead.name}</h3>
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

      <div className="grid grid--3 team-counts">
        <div className="kpi kpi--ok team-count">
          <div className="kpi__value">{free}</div>
          <div className="kpi__label">{t("فاضيين", "Free")}</div>
        </div>
        <div className="kpi kpi--warn team-count">
          <div className="kpi__value">{busy}</div>
          <div className="kpi__label">{t("مشغولين", "Busy")}</div>
        </div>
        <div className="kpi team-count">
          <div className="kpi__value">{offline}</div>
          <div className="kpi__label">{t("أوفلاين", "Offline")}</div>
        </div>
      </div>
      <div className="team-bar" aria-hidden="true">
        {total > 0 && (
          <>
            <span className="team-bar__free" style={{ flexGrow: free }} />
            <span className="team-bar__busy" style={{ flexGrow: busy }} />
            <span className="team-bar__off" style={{ flexGrow: offline }} />
          </>
        )}
      </div>

      {lead.members.length > 0 ? (
        <div className="team-members">
          <div className="team-members__head" aria-hidden="true">
            <span>{t("المترجم", "Translator")}</span>
            <span>{t("الحالة", "State")}</span>
            <span>{t("التاسك الحالية", "Current task")}</span>
            <span>{t("التقييم", "Rating")}</span>
          </div>
          <ul className="team-members__list">
            {lead.members.map((member) => (
              <li key={member.id} className="team-member" data-member={member.id}>
                <div className="team-member__who">
                  <div className="avatar avatar--sm">{member.initials}</div>
                  <div className="team-member__name">
                    <div>{member.name}</div>
                    <small className="muted mono">{member.languages}</small>
                  </div>
                </div>
                <div className="team-member__state">
                  <Presence state={member.state} seen={member.seen} />
                </div>
                <div className="team-member__tasks">
                  {member.tasks.map((code) => (
                    <Link key={code} className="badge badge--work mono" to={`/tasks/${encodeURIComponent(code)}`}>
                      {code}
                    </Link>
                  ))}
                  {member.tasks.length === 0 && <span className="muted">—</span>}
                </div>
                <div className="team-member__rating">
                  <Rating value={member.rating} />
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="muted team-empty">{t("مفيش مترجمين تحت التيم ليدر ده.", "No translators under this team leader.")}</p>
      )}
    </div>
  );
}

/** The totals across every team, above the cards: how many are free, busy and offline right now. */
function Summary({ leads }: { leads: Lead[] }) {
  const { t } = usePreferences();
  const sum = (pick: (lead: Lead) => number) => leads.reduce((all, lead) => all + pick(lead), 0);
  const items = [
    { tone: "", value: leads.length, label: t("تيم ليدرز", "Team leaders") },
    { tone: "ok", value: sum((l) => l.counts.free), label: t("فاضيين", "Free") },
    { tone: "warn", value: sum((l) => l.counts.busy), label: t("مشغولين", "Busy") },
    { tone: "off", value: sum((l) => l.counts.offline), label: t("أوفلاين", "Offline") },
  ];
  return (
    <div className="team-summary" data-summary>
      {items.map((item) => (
        <div key={item.label} className={`team-summary__item${item.tone ? ` team-summary__item--${item.tone}` : ""}`}>
          <span className="team-summary__value">{item.value}</span>
          <span className="team-summary__label">{item.label}</span>
        </div>
      ))}
    </div>
  );
}

/** The team leaders and their teams: who is free, who is busy, who is offline, and with what. */
export function TeamPage() {
  const { t } = usePreferences();
  const me = useMe();
  // The same people the server lets in (`api_role_required`: the operation, technical support, and the admin).
  const allowed = me.data !== undefined && (me.data.user.role === "operation" || me.data.user.role === "support" || me.data.user.is_admin);
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
        <>
          {data.leads.length > 0 && <Summary leads={data.leads} />}
          <div className="team-board">
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
        </>
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
