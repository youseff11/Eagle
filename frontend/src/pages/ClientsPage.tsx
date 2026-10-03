import { useState, type FormEvent } from "react";
import { Link, Navigate, useSearchParams } from "react-router";
import { useClients, useMe } from "../api/queries";
import { Icon } from "../components/Icon";
import { usePreferences } from "../i18n/Preferences";

/** The search box. The address holds the search, so a reload and the way back from a client keep it. */
function Search({ query, onSearch }: { query: string; onSearch: (query: string) => void }) {
  const { t } = usePreferences();
  const [text, setText] = useState(query);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSearch(text.trim());
  };
  return (
    <form className="row" style={{ marginBottom: 14 }} onSubmit={submit} role="search">
      <div className="field-icon grow" style={{ margin: 0 }}>
        <Icon name="search" className="ic--lead" />
        <input
          className="input"
          name="q"
          value={text}
          maxLength={200}
          onChange={(event) => setText(event.target.value)}
          placeholder={t("ابحث بالكود…", "Search by code…")}
          aria-label={t("بحث", "Search")}
        />
      </div>
      <button className="btn" type="submit">
        {t("بحث", "Search")}
      </button>
    </form>
  );
}

/**
 * The client codes. The names and numbers beside them only for whoever the server says may know them
 * (`sees_identity`): for everybody else they are not in the answer at all.
 */
export function ClientsPage() {
  const { t } = usePreferences();
  const me = useMe();
  const [params, setParams] = useSearchParams();
  const asked = (params.get("q") ?? "").trim();
  // The address is the person's to type: a search of a sensible length goes to the server (it checks too).
  const query = asked.length <= 200 ? asked : "";
  // The same people the server lets in (`api_role_required`: the operation, and the admin).
  const allowed = me.data !== undefined && (me.data.user.role === "operation" || me.data.user.is_admin);
  const list = useClients(query, allowed);

  if (me.data && !allowed) return <Navigate to="/" replace />;

  const data = list.data;
  const sees = data?.sees_identity ?? false;

  return (
    <>
      <div className="page-head">
        <h1>{t("العملاء", "Clients")}</h1>
        <span className="page-head__sub">
          {t(
            "بيانات العميل الحقيقية بتظهر للأدمن ولمين الأدمن سمح له بس — الباقي بيشوف الكود. كل فتح بيتسجّل.",
            "Real client details are visible to the admin and to people the admin granted them to — everyone else sees the code. Every view is logged.",
          )}
        </span>
      </div>

      <div className="card">
        <Search key={query} query={query} onSearch={(next) => setParams(next ? { q: next } : {})} />

        {data ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("الكود", "Code")}</th>
                  {sees && <th>{t("الاسم", "Name")}</th>}
                  {sees && <th>{t("التليفون", "Phone")}</th>}
                  <th>{t("عدد التاسكات", "Tasks")}</th>
                  <th>{t("المتطلبات", "Requirements")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.clients.map((client) => (
                  <tr key={client.code} data-client={client.code}>
                    <td className="mono">
                      <strong>{client.code}</strong>
                    </td>
                    {sees && (
                      <td>
                        {client.name || "—"} <small className="muted">{client.company}</small>
                      </td>
                    )}
                    {sees && <td className="mono">{client.phone || "—"}</td>}
                    <td>{client.tasks}</td>
                    <td>{client.requirements}</td>
                    <td>
                      <Link className="btn btn--sm" to={`/clients/${encodeURIComponent(client.code)}`}>
                        {t("افتح", "Open")}
                      </Link>
                    </td>
                  </tr>
                ))}
                {data.clients.length === 0 && (
                  <tr>
                    <td colSpan={sees ? 6 : 4} className="empty">
                      <Icon name="tag" size="xl" />
                      <span>{t("مفيش عملاء.", "No clients.")}</span>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        ) : list.isError ? (
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
    </>
  );
}
