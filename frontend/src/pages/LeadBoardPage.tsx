import { Link, Navigate } from "react-router";
import { useLeadBoard, useMe } from "../api/queries";
import type { LeadBoard } from "../api/types";
import { deadlineClass, Rating } from "../components/Badges";
import { Icon } from "../components/Icon";
import { Presence } from "../components/Presence";
import { usePreferences } from "../i18n/Preferences";

type Row = LeadBoard["team"][number];

function Counters({ counters }: { counters: LeadBoard["counters"] }) {
  const { t } = usePreferences();
  return (
    <div className="grid grid--4" style={{ marginBottom: 18 }}>
      <div className="kpi kpi--ok">
        <div className="kpi__value">{counters.free}</div>
        <div className="kpi__label">{t("فاضيين دلوقتي", "Free now")}</div>
      </div>
      <div className="kpi kpi--warn">
        <div className="kpi__value">{counters.busy}</div>
        <div className="kpi__label">{t("مشغولين", "Busy")}</div>
      </div>
      <div className="kpi">
        <div className="kpi__value">{counters.shift}</div>
        <div className="kpi__label">{t("في الشيفت — مش فاتح", "On shift — not open")}</div>
      </div>
      <div className="kpi">
        <div className="kpi__value">{counters.offline}</div>
        <div className="kpi__label">{t("أوفلاين", "Offline")}</div>
      </div>
    </div>
  );
}

function Person({ row }: { row: Row }) {
  const { t, lang } = usePreferences();
  const due = row.next_due ? (lang === "ar" ? row.next_due.ar : row.next_due.en) : null;
  return (
    <tr className={`tstate tstate--${row.state}`} data-member={row.id}>
      <td>
        <div className="row row--tight">
          <div className="avatar avatar--sm">{row.initials}</div>
          <div>
            <div>{row.name}</div>
            <small className="muted mono">{row.languages || "—"}</small>
          </div>
        </div>
      </td>
      <td>
        <Presence state={row.state} />
        {row.awaiting_answer && (
          <div>
            <small className="muted">{t("مستني يرد على عرض تاسك", "An offer is awaiting their answer")}</small>
          </div>
        )}
      </td>
      <td>
        <div className="row row--tight">
          <span className="mono">{row.load}</span>
          <span className="load">
            <i className="load__fill" style={{ width: `${row.load_percent}%` }} />
          </span>
        </div>
        {row.words > 0 && (
          <small className="muted mono">
            {row.words} <span>{t("كلمة", "words")}</span>
          </small>
        )}
      </td>
      <td>
        {row.tasks.map((code) => (
          <Link key={code} className="badge badge--work mono" to={`/tasks/${encodeURIComponent(code)}`}>
            {code}
          </Link>
        ))}
        {row.tasks.length === 0 && <span className="muted">—</span>}
        {row.load > 3 && <span className="chip mono">+{row.load - 3}</span>}
      </td>
      <td className={`mono ${deadlineClass(row.next_due_state)}`}>{due ?? "—"}</td>
      <td>
        <Rating value={row.rating} />
      </td>
    </tr>
  );
}

/**
 * Who is free and who is busy: the leader's assignment board. It holds the evidence - what each is working on, the
 * nearest deadline, the load - and not only a coloured dot, because it is read before handing work out. "Free" means
 * Eagle is open now, with no running task and no offer awaiting an answer.
 */
export function LeadBoardPage() {
  const { t, lang } = usePreferences();
  const me = useMe();
  const allowed = me.data !== undefined && (me.data.user.role === "team_lead" || me.data.user.is_admin);
  const query = useLeadBoard(allowed);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  const data = query.data;

  return (
    <>
      <div className="page-head">
        <h1>{t("مين فاضي ومين مشغول", "Who is free, who is busy")}</h1>
        <span className="page-head__sub">
          {t(
            "«فاضي» يعني فاتح إيجل دلوقتي ومفيش تاسك شغّالة عنده ولا عرض مستني رده.",
            "“Free” means Eagle is open right now, with no running task and no offer awaiting an answer.",
          )}
        </span>
      </div>

      {data && <Counters counters={data.counters} />}

      {data && data.waiting.length > 0 && (
        <div className="note note--warn" style={{ marginBottom: 16 }}>
          <Icon name="target" />
          <div>
            <strong>{t("تاسكات مستنية توزيع", "Tasks waiting for a translator")}</strong>
            <div className="files" style={{ marginTop: 7 }}>
              {data.waiting.map((task) => (
                <Link key={task.code} className={`file-pill mono ${deadlineClass(task.due_state)}`} to={`/tasks/${encodeURIComponent(task.code)}`}>
                  <Icon name="arrow-right" size="sm" />
                  {task.code}
                  {task.due ? ` · ${lang === "ar" ? task.due.ar : task.due.en}` : ""}
                </Link>
              ))}
            </div>
          </div>
        </div>
      )}

      {data ? (
        <div className="card">
          <div className="card__head">
            <Icon name="users" />
            <h2>{t("فريقي", "My team")}</h2>
            <div className="grow" />
            <span className="chip mono">{data.team.length}</span>
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("المترجم", "Translator")}</th>
                  <th>{t("الحالة", "State")}</th>
                  <th>{t("الحِمل", "Load")}</th>
                  <th>{t("شغّال على", "Working on")}</th>
                  <th>{t("أقرب ديدلاين", "Next deadline")}</th>
                  <th>{t("التقييم", "Rating")}</th>
                </tr>
              </thead>
              <tbody>
                {data.team.map((row) => (
                  <Person key={row.id} row={row} />
                ))}
                {data.team.length === 0 && (
                  <tr>
                    <td colSpan={6} className="empty">
                      <Icon name="users" size="xl" />
                      <span>{t("مفيش مترجمين تحتك.", "No translators assigned to you.")}</span>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
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
