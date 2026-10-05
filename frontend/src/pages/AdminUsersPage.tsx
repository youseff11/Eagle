import { Link, Navigate } from "react-router";
import { useAdminUsers, useMe } from "../api/queries";
import { Avatar } from "../components/Avatar";
import { Icon } from "../components/Icon";
import { Presence } from "../components/Presence";
import { Rating } from "../components/Badges";
import { usePreferences } from "../i18n/Preferences";

/**
 * Staff and shifts: everybody, with their role, leader, the mail address they receive for, whether they are here, how
 * many shifts they have and their rating. A person's file opens from the row; a new person from the button.
 */
export function AdminUsersPage() {
  const { t, lang } = usePreferences();
  const me = useMe();
  const allowed = me.data !== undefined && me.data.user.is_admin;
  const query = useAdminUsers(allowed);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  const data = query.data;

  return (
    <>
      <div className="page-head">
        <h1>{t("الموظفين والشيفتات", "Staff & shifts")}</h1>
        <div className="grow" />
        <Link className="btn btn--primary" to="/admin/users/new">
          <Icon name="plus" size="sm" />
          <span>{t("موظف جديد", "New staff member")}</span>
        </Link>
      </div>

      <div className="card">
        {data ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("الموظف", "Person")}</th>
                  <th>{t("الدور", "Role")}</th>
                  <th>{t("التيم ليدر", "Team leader")}</th>
                  <th>{t("بيستقبل ميلات", "Receives mail for")}</th>
                  <th>{t("الحالة", "Presence")}</th>
                  <th>{t("الشيفتات", "Shifts")}</th>
                  <th>{t("التقييم", "Rating")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.users.map((person) => (
                  <tr key={person.id} data-user={person.id}>
                    <td>
                      <div className="row row--tight">
                        <Avatar src={person.avatar} initials={person.initials} tone="" className="avatar--sm" />
                        <div>
                          <div>{person.name}</div>
                          <small className="muted mono">{person.username}</small>
                        </div>
                      </div>
                    </td>
                    <td>
                      <span className="chip">{lang === "ar" ? person.role.ar : person.role.en}</span>
                    </td>
                    <td>{person.team_lead ?? "—"}</td>
                    <td className="mono" dir="ltr">
                      {person.mail_alias || "—"}
                    </td>
                    <td>
                      {person.state === "disabled" ? (
                        <span className="badge badge--dead">{t("موقوف", "Disabled")}</span>
                      ) : (
                        <Presence state={person.state} seen={person.seen} />
                      )}
                    </td>
                    <td className="mono">{person.shifts}</td>
                    <td>
                      <Rating value={person.rating} />
                    </td>
                    <td>
                      <Link className="btn btn--sm" to={`/admin/users/${person.id}`}>
                        {t("تعديل", "Edit")}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : query.isError ? (
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
