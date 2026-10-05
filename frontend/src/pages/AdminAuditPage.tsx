import { Loading } from "../components/Loading";
import { useEffect, useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router";
import { useOlderAudit } from "../api/adminActions";
import { useAdminAudit, useMe } from "../api/queries";
import type { AdminAudit, AuditFilter } from "../api/types";
import { Icon } from "../components/Icon";
import { usePreferences } from "../i18n/Preferences";

const FILTERS: { value: AuditFilter; label: [string, string] }[] = [
  { value: "", label: ["الكل", "All"] },
  { value: "security", label: ["هوية العملاء والصلاحيات", "Client identity and access"] },
  { value: "denied", label: ["محاولات مرفوضة", "Refused attempts"] },
];

/** `?only=` as the address carries it: one of the two filters, else the whole log (as the classic page reads it). */
function filterOf(raw: string | null): AuditFilter {
  return raw === "security" || raw === "denied" ? raw : "";
}

/**
 * The audit log: who looked at a client's identity, who was refused something, who was given access, and the rest.
 * Newest first, two hundred a time, and a button for the older ones. It is read when the page opens and again on the refresh
 * button, which starts from the newest again.
 */
export function AdminAuditPage() {
  const { t, lang } = usePreferences();
  const me = useMe();
  const [params] = useSearchParams();
  const only = filterOf(params.get("only"));
  const allowed = me.data !== undefined && me.data.user.is_admin;
  const query = useAdminAudit(only, allowed);
  const olderPages = useOlderAudit(only);
  const [older, setOlder] = useState<{ rows: AdminAudit["rows"]; more: boolean } | null>(null);

  // Older pages hang under the first one: a new filter, or the first page read again, starts over.
  useEffect(() => setOlder(null), [only, query.dataUpdatedAt]);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  const data = query.data;
  const rows = data ? [...data.rows, ...(older?.rows ?? [])] : [];
  const more = older ? older.more : (data?.more ?? false);
  const last = rows[rows.length - 1];

  const loadOlder = () => {
    if (!last) return;
    olderPages.mutate(last.id, {
      onSuccess: (page) => setOlder((now) => ({ rows: [...(now?.rows ?? []), ...page.rows], more: page.more })),
    });
  };

  return (
    <>
      <div className="page-head">
        <h1>{t("سجل النشاط", "Audit log")}</h1>
        <div className="grow" />
        {FILTERS.map((filter) => (
          <Link
            key={filter.value}
            className={`btn btn--sm${only === filter.value ? " btn--primary" : ""}`}
            to={filter.value ? `/admin/audit?only=${filter.value}` : "/admin/audit"}
            aria-current={only === filter.value ? "true" : undefined}
          >
            {t(...filter.label)}
          </Link>
        ))}
        <button
          className="btn btn--sm"
          type="button"
          onClick={() => void query.refetch()}
          disabled={query.isFetching}
          title={t("حدّث", "Refresh")}
          aria-label={t("حدّث", "Refresh")}
        >
          <Icon name="refresh" size="sm" />
        </button>
      </div>

      <div className="card">
        {data ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("الوقت", "Time")}</th>
                  <th>{t("الشخص", "Actor")}</th>
                  <th>{t("الحدث", "Action")}</th>
                  <th>{t("الهدف", "Target")}</th>
                  <th>{t("تفاصيل", "Detail")}</th>
                  <th>{t("من فين", "From")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} data-entry={row.id}>
                    <td className="mono nowrap">{row.at ? (lang === "ar" ? row.at.ar : row.at.en) : ""}</td>
                    <td>{row.actor ?? "system"}</td>
                    <td className="mono">{row.action}</td>
                    <td className="mono">{row.target}</td>
                    <td className="muted" title={row.detail}>
                      {row.detail}
                    </td>
                    <td className="mono muted" dir="ltr">
                      {row.ip}
                      {row.path && <small> {row.path}</small>}
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={6} className="empty">
                      <Icon name="history" size="xl" />
                      <span>{t("السجل فاضي.", "Log is empty.")}</span>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            {olderPages.isError && (
              <div className="note note--high mt" role="alert">
                <Icon name="alert" />
                <div>{t("ماقدرناش نحمّل الأقدم.", "Could not load older entries.")}</div>
              </div>
            )}
            {more && (
              <div className="row mt">
                <button className="btn" type="button" data-older onClick={loadOlder} disabled={olderPages.isPending}>
                  <Icon name="history" size="sm" />
                  <span>{t("الأقدم", "Older")}</span>
                </button>
              </div>
            )}
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
