import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { csrfToken } from "../api/client";
import { useMe } from "../api/queries";
import type { Role } from "../api/types";
import { usePreferences } from "../i18n/Preferences";
import { useRealtimeStatus } from "../realtime/RealtimeProvider";
import { Icon } from "./Icon";

/** The same labels the classic pages show beside a name (`ROLE_MAP` in eagle_tags). */
const ROLE_LABELS: Record<Role, [string, string]> = {
  admin: ["أدمن", "Admin"],
  operation: ["أوبريشن", "Operation"],
  team_lead: ["تيم ليدر", "Team leader"],
  translator: ["مترجم", "Translator"],
  hr: ["موارد بشرية", "HR"],
  reviewer: ["مراجع", "Reviewer"],
  accounting: ["حسابات", "Accounting"],
  sales: ["مبيعات", "Sales"],
};

/** Signing out is a POST the classic way too: a form with the token, then the redirect. */
function logout(): void {
  const form = document.createElement("form");
  form.method = "post";
  form.action = "/logout/";
  const token = document.createElement("input");
  token.type = "hidden";
  token.name = "csrfmiddlewaretoken";
  token.value = csrfToken();
  form.appendChild(token);
  document.body.appendChild(form);
  form.submit();
}

export function Shell() {
  const { t, lang, setLang, theme, setTheme } = usePreferences();
  const me = useMe();
  const realtime = useRealtimeStatus();
  const location = useLocation();
  const [drawer, setDrawer] = useState(false);

  // A phone's menu is a drawer: it closes when you go somewhere, and on Escape.
  useEffect(() => setDrawer(false), [location.pathname]);
  useEffect(() => {
    if (!drawer) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDrawer(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawer]);

  const user = me.data?.user;
  const unread = me.data?.unread_notifications ?? 0;
  const title = location.pathname.startsWith("/notifications")
    ? t("التنبيهات", "Notifications")
    : t("الرئيسية", "Home");
  const realtimeLabel = {
    open: t("متصل لحظيًا", "Live"),
    connecting: t("بيتصل...", "Connecting..."),
    closed: t("مقطوع، بيحاول تاني", "Offline, retrying"),
    stopped: t("متوقف", "Stopped"),
  }[realtime];

  return (
    <div className="shell">
      <aside className={`sidebar${drawer ? " is-open" : ""}`} id="sidebar">
        <button
          className="icon-btn sidebar__close"
          type="button"
          aria-label={t("اقفل القايمة", "Close the menu")}
          title={t("اقفل القايمة", "Close the menu")}
          onClick={() => setDrawer(false)}
        >
          <Icon name="x" />
        </button>
        <a href="/app/" className="brand brand--img">
          <img src="/static/img/logo-removebg-preview.png" alt="Eagle Operation" />
        </a>
        <nav className="nav" id="sideNav">
          <div className="nav__items">
            <NavLink to="/" end className={({ isActive }) => `nav__item${isActive ? " is-active" : ""}`}>
              <Icon name="layers" />
              <span>{t("الرئيسية", "Home")}</span>
            </NavLink>
            <NavLink to="/notifications" className={({ isActive }) => `nav__item${isActive ? " is-active" : ""}`}>
              <Icon name="bell" />
              <span>{t("التنبيهات", "Notifications")}</span>
              {unread > 0 && <span className="nav__count is-hot">{unread}</span>}
            </NavLink>
            <a href="/" className="nav__item">
              <Icon name="arrow-right" />
              <span>{t("الواجهة الحالية", "Classic interface")}</span>
            </a>
          </div>
        </nav>
      </aside>
      <div className={`drawer-scrim${drawer ? " is-open" : ""}`} onClick={() => setDrawer(false)} />

      <div className="main">
        <header className="topbar">
          <button
            className="icon-btn menu-toggle"
            type="button"
            aria-label={t("القايمة", "Menu")}
            aria-controls="sidebar"
            aria-expanded={drawer}
            onClick={() => setDrawer(true)}
          >
            <Icon name="menu" />
          </button>
          <div className="topbar__title">{title}</div>
          <div className="topbar__spacer" />

          <span className="realtime-dot" data-state={realtime} title={realtimeLabel} aria-label={realtimeLabel} />
          <div className="seg">
            <button type="button" className={lang === "ar" ? "is-active" : ""} onClick={() => setLang("ar")}>
              عربي
            </button>
            <button type="button" className={lang === "en" ? "is-active" : ""} onClick={() => setLang("en")}>
              EN
            </button>
          </div>
          <button
            className="icon-btn"
            type="button"
            title={t("تبديل الوضع الليلي", "Toggle dark mode")}
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            <Icon name={theme === "dark" ? "moon" : "sun"} />
          </button>
          <NavLink className="icon-btn" to="/notifications" title={t("التنبيهات", "Notifications")}>
            <Icon name="bell" />
            {unread > 0 && <span className="icon-btn__dot">{unread}</span>}
          </NavLink>
          <div className="topbar__divider" />
          {user && (
            <div className="topbar__user" title={user.short_name}>
              <span className="avatar avatar--brand topbar__face">{user.initials}</span>
              <span className="topbar__who">
                <span className="topbar__who-name">{user.short_name}</span>
                <span className="chip">{ROLE_LABELS[user.role]?.[lang === "ar" ? 0 : 1] ?? user.role}</span>
              </span>
            </div>
          )}
          <button className="icon-btn" type="button" title={t("خروج", "Log out")} onClick={logout}>
            <Icon name="logout" />
          </button>
        </header>

        <div className="content">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
