import { Navigate, NavLink } from "react-router";
import { useMe } from "../api/queries";
import { Icon } from "../components/Icon";
import { usePreferences } from "../i18n/Preferences";
import { CLASSIC_HOME } from "../lib/navigation";

export function HomePage() {
  const { t } = usePreferences();
  const me = useMe();
  const unread = me.data?.unread_notifications ?? 0;

  // A translator whose desk has been switched over starts there, as the classic `/` does for them.
  if (me.data?.user.role === "translator" && (me.data.screens ?? []).includes("translator_home")) {
    return <Navigate to="/translator" replace />;
  }
  // The admin whose panel was switched over starts on the overview, as the classic `/` does for them.
  if (me.data?.user.is_admin && (me.data.screens ?? []).includes("admin")) {
    return <Navigate to="/admin" replace />;
  }

  return (
    <>
      <div className="page-head">
        <h1>
          {t("أهلاً", "Welcome")} {me.data?.user.short_name ?? ""}
        </h1>
      </div>

      <div className="card">
        <div className="row row--between">
          <div className="row">
            <Icon name="bell" size="lg" />
            <div>
              <strong>{t("التنبيهات", "Notifications")}</strong>
              <div className="muted">
                {unread > 0
                  ? t(`عندك ${unread} تنبيه جديد`, `You have ${unread} unread`)
                  : t("مفيش تنبيهات جديدة", "Nothing new")}
              </div>
            </div>
          </div>
          <NavLink className="btn btn--sm" to="/notifications">
            {t("افتح", "Open")}
          </NavLink>
        </div>
      </div>

      <div className="card">
        <div className="row row--between">
          <div className="row">
            <Icon name="layers" size="lg" />
            <div>
              <strong>{t("الواجهة الجديدة تحت التجهيز", "The new interface is being built")}</strong>
              <div className="muted">
                {t(
                  "باقي الشاشات لسه في الواجهة الحالية، وبتتنقل هنا واحدة واحدة.",
                  "The other screens are still in the classic interface and move here one at a time.",
                )}
              </div>
            </div>
          </div>
          <a className="btn btn--sm" href={CLASSIC_HOME}>
            {t("افتح الواجهة الحالية", "Open the classic interface")}
          </a>
        </div>
      </div>
    </>
  );
}
