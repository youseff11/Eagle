import { NavLink } from "react-router";
import { Icon } from "../components/Icon";
import { usePreferences } from "../i18n/Preferences";

export function NotFound() {
  const { t } = usePreferences();
  return (
    <div className="card">
      <div className="empty">
        <Icon name="search" size="xl" />
        <span>{t("الصفحة دي مش موجودة.", "This page does not exist.")}</span>
        <div>
          <NavLink className="btn btn--sm" to="/">
            {t("الرئيسية", "Home")}
          </NavLink>
        </div>
      </div>
    </div>
  );
}
