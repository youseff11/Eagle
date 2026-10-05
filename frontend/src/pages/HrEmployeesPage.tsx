import { Link, Navigate, useSearchParams } from "react-router";
import { useHrRegister } from "../api/queries";
import { Waiting } from "../components/accounts/shared";
import { Avatar } from "../components/Avatar";
import { Rating } from "../components/Badges";
import { useHrAllowed } from "../components/hr/shared";
import { LeaveStatusBadge, useLeaveWords } from "../components/leave/shared";
import { Icon } from "../components/Icon";
import { Presence } from "../components/Presence";
import { usePreferences } from "../i18n/Preferences";

const FILTERS = ["department", "status"] as const;

/**
 * Everybody on the staff, in one list: HR's columns (role, department, kind of work, status) and the staff table's (leader, whether they
 * are here, shifts, rating). The file opens from the name. The admin also sees the switched-off, the address a person receives mail for,
 * and makes a new person from the button. The filters live in the address.
 */
export function HrEmployeesPage() {
  const { t } = usePreferences();
  const words = useLeaveWords();
  const { me, allowed } = useHrAllowed();
  const isAdmin = me.data?.user.is_admin === true;
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
  const columns = isAdmin ? 11 : 10;

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
        {isAdmin && (
          <Link className="btn btn--primary" to="/hr/employees/new">
            <Icon name="plus" size="sm" />
            <span>{t("موظف جديد", "New staff member")}</span>
          </Link>
        )}
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
                <th>{t("الموظف", "Employee")}</th>
                <th>{t("الدور", "Role")}</th>
                <th>{t("القسم", "Department")}</th>
                <th>{t("التيم ليدر", "Team leader")}</th>
                <th>{t("نوع التوظيف", "Type")}</th>
                <th>{t("تاريخ الانضمام", "Joined")}</th>
                <th>{t("الحالة", "Status")}</th>
                <th>{t("التواجد", "Presence")}</th>
                <th>{t("الشيفتات", "Shifts")}</th>
                <th>{t("التقييم", "Rating")}</th>
                {isAdmin && <th>{t("بيستقبل ميلات", "Receives mail for")}</th>}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <tr key={row.id} data-person={row.id}>
                  <td>
                    <div className="row row--tight">
                      <Avatar src={row.avatar} initials={row.initials} tone="" className="avatar--sm" />
                      <div>
                        <Link to={`/hr/employees/${row.id}`}>{row.name}</Link>
                        <div>
                          <small className="muted mono">{[row.code, row.username].filter(Boolean).join(" · ") || "—"}</small>
                        </div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <span className="chip">{words(row.role)}</span>
                  </td>
                  <td className="muted">{row.department ?? "—"}</td>
                  <td>{row.team_lead ?? "—"}</td>
                  <td>
                    <span className="chip">{words(row.employment)}</span>
                  </td>
                  <td className="mono muted">{row.joining_date ?? "—"}</td>
                  <td>
                    <LeaveStatusBadge status={row.status} />
                  </td>
                  <td>{row.state === "disabled" ? <span className="badge badge--dead">{t("موقوف", "Disabled")}</span> : <Presence state={row.state} seen={row.seen} />}</td>
                  <td className="mono">{row.shifts ?? "—"}</td>
                  <td>{row.rating === null ? "—" : <Rating value={row.rating} />}</td>
                  {isAdmin && (
                    <td className="mono" dir="ltr">
                      {row.mail_alias || "—"}
                    </td>
                  )}
                </tr>
              ))}
              {data.rows.length === 0 && (
                <tr>
                  <td colSpan={columns} className="empty">
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
