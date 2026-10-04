import { Link, Navigate, useSearchParams } from "react-router";
import { useHrRegister } from "../api/queries";
import { Waiting } from "../components/accounts/shared";
import { useHrAllowed } from "../components/hr/shared";
import { LeaveStatusBadge, useLeaveWords } from "../components/leave/shared";
import { Icon } from "../components/Icon";
import { usePreferences } from "../i18n/Preferences";

const FILTERS = ["department", "status"] as const;

/** Everybody active, with their department, kind of work and status. The filters live in the address. */
export function HrEmployeesPage() {
  const { t } = usePreferences();
  const words = useLeaveWords();
  const { me, allowed } = useHrAllowed();
  const [params, setParams] = useSearchParams();
  const kept = new URLSearchParams();
  for (const name of FILTERS) {
    const value = params.get(name);
    if (value) kept.set(name, value);
  }
  const query = useHrRegister(kept.toString(), allowed);
  const data = query.data;

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!data) return <Waiting failed={query.isError} />;

  const set = (name: (typeof FILTERS)[number], value: string) => {
    const next = new URLSearchParams(kept);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next);
  };

  return (
    <>
      <div className="page-head">
        <h1>{t("الموظفين", "Employees")}</h1>
        <div className="grow" />
        <select className="input" aria-label={t("القسم", "Department")} value={kept.get("department") ?? ""} onChange={(event) => set("department", event.target.value)}>
          <option value="">{t("كل الأقسام", "All departments")}</option>
          {data.options.departments.map((one) => (
            <option key={one.id} value={one.id}>
              {one.label}
            </option>
          ))}
        </select>
        <select className="input" aria-label={t("الحالة", "Status")} value={kept.get("status") ?? ""} onChange={(event) => set("status", event.target.value)}>
          <option value="">{t("كل الحالات", "All statuses")}</option>
          {data.options.statuses.map((one) => (
            <option key={one.value} value={one.value}>
              {words(one)}
            </option>
          ))}
        </select>
      </div>

      <div className="card">
        <div className="card__head">
          <Icon name="users" />
          <h3>{t("السجل", "The register")}</h3>
        </div>
        <div className="table-wrap">
          <table className="table" data-table="register">
            <thead>
              <tr>
                <th>{t("الكود", "Code")}</th>
                <th>{t("الموظف", "Employee")}</th>
                <th>{t("الدور", "Role")}</th>
                <th>{t("القسم", "Department")}</th>
                <th>{t("نوع التوظيف", "Type")}</th>
                <th>{t("تاريخ الانضمام", "Joined")}</th>
                <th>{t("الحالة", "Status")}</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <tr key={row.id} data-person={row.id}>
                  <td className="mono">
                    <Link to={`/hr/employees/${row.id}`}>{row.code || "—"}</Link>
                  </td>
                  <td>{row.name}</td>
                  <td>
                    <span className="chip">{words(row.role)}</span>
                  </td>
                  <td className="muted">{row.department ?? "—"}</td>
                  <td>
                    <span className="chip">{words(row.employment)}</span>
                  </td>
                  <td className="mono muted">{row.joining_date ?? "—"}</td>
                  <td>
                    <LeaveStatusBadge status={row.status} />
                  </td>
                </tr>
              ))}
              {data.rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="empty">
                    {t("مفيش موظفين.", "Nobody yet.")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
