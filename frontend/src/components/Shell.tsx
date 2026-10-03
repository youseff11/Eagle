import { Fragment, useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { csrfToken } from "../api/client";
import { useMe } from "../api/queries";
import type { Role, ScreenKey } from "../api/types";
import { usePreferences } from "../i18n/Preferences";
import { CLASSIC_HOME } from "../lib/navigation";
import { useOutboxProblems } from "../lib/outbox";
import { useRealtimeStatus } from "../realtime/RealtimeProvider";
import { AssignmentModal } from "./AssignmentModal";
import { ErrorBoundary } from "./ErrorBoundary";
import { Icon } from "./Icon";
import { NotificationToasts } from "./NotificationToasts";
import { ToastProvider } from "./Toasts";

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

/**
 * The screens that have been ported: where they live in this app, and what the menu calls them.
 *
 * A screen can be more than one page. `also` are other addresses that belong to it (the task page is "my work"),
 * so the menu and the title know where the person is; `extra` are the other pages of the screen that get their own
 * line in the menu (the payslip). One switch for all of them: a person never has half a screen.
 */
export interface ScreenEntry {
  path: string;
  icon: string;
  label: [string, string];
  also?: string[];
  extra?: { path: string; icon: string; label: [string, string] }[];
}

export const SCREENS: Record<ScreenKey, ScreenEntry> = {
  translator_home: {
    path: "/translator",
    icon: "pen",
    label: ["شغلي", "My work"],
    also: ["/tasks"],
    extra: [{ path: "/payroll", icon: "folder", label: ["مستحقاتي", "My payroll"] }],
  },
  chats: { path: "/chats", icon: "message", label: ["الشات", "Chats"] },
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

/** The frame of every page, and the toasts that can appear on top of any of them. */
export function Shell() {
  return (
    <ToastProvider>
      <NotificationToasts />
      <Frame />
      {/* On a clock, so over every page: a person who has not seen it loses the assignment. */}
      <AssignmentModal />
    </ToastProvider>
  );
}

function Frame() {
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
  const unreadChats = me.data?.unread_chats ?? 0;
  const unsent = useOutboxProblems().length;
  const screens = (me.data?.screens ?? []).filter((key) => Object.hasOwn(SCREENS, key));
  // The title follows the address, not the list: it is right before `me` has arrived too.
  const startsWith = (prefix: string) => location.pathname === prefix || location.pathname.startsWith(`${prefix}/`);
  const here = (Object.keys(SCREENS) as ScreenKey[]).find((key) =>
    [SCREENS[key].path, ...(SCREENS[key].also ?? [])].some(startsWith),
  );
  const extraHere = (Object.keys(SCREENS) as ScreenKey[])
    .flatMap((key) => SCREENS[key].extra ?? [])
    .find((entry) => startsWith(entry.path));
  const title = startsWith("/notifications")
    ? t("التنبيهات", "Notifications")
    : extraHere
      ? t(...extraHere.label)
      : here
        ? t(...SCREENS[here].label)
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
            {screens.map((key) => (
              <Fragment key={key}>
                <NavLink
                  to={SCREENS[key].path}
                  className={({ isActive }) =>
                    `nav__item${isActive || (SCREENS[key].also ?? []).some(startsWith) ? " is-active" : ""}`
                  }
                >
                  <Icon name={SCREENS[key].icon} />
                  <span>{t(...SCREENS[key].label)}</span>
                  {key === "chats" && unsent > 0 && (
                    <span className="nav__count is-hot" title={t("فيه رسالة ماتبعتتش", "A message did not go")}>
                      <Icon name="alert" size="sm" />
                    </span>
                  )}
                  {key === "chats" && unreadChats > 0 && <span className="nav__count is-hot">{unreadChats}</span>}
                </NavLink>
                {(SCREENS[key].extra ?? []).map((entry) => (
                  <NavLink
                    key={entry.path}
                    to={entry.path}
                    className={({ isActive }) => `nav__item${isActive ? " is-active" : ""}`}
                  >
                    <Icon name={entry.icon} />
                    <span>{t(...entry.label)}</span>
                  </NavLink>
                ))}
              </Fragment>
            ))}
            <NavLink to="/notifications" className={({ isActive }) => `nav__item${isActive ? " is-active" : ""}`}>
              <Icon name="bell" />
              <span>{t("التنبيهات", "Notifications")}</span>
              {unread > 0 && <span className="nav__count is-hot">{unread}</span>}
            </NavLink>
            <a href={CLASSIC_HOME} className="nav__item">
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
          <ErrorBoundary resetKey={location.pathname}>
            <Outlet />
          </ErrorBoundary>
        </div>
      </div>
    </div>
  );
}
