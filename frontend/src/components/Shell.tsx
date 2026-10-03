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
import { AttendanceGate } from "./AttendanceGate";
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
  /** The number the menu shows beside the line, from `/me/` (the mail not opened, the tasks nobody has). */
  badge?: Badge;
  extra?: { path: string; icon: string; label: [string, string]; badge?: Badge }[];
}

/** The counters `/me/` carries for the menu. */
type Badge = "mail_unseen" | "tasks_new" | "tasks_open";

export const SCREENS: Record<ScreenKey, ScreenEntry> = {
  translator_home: {
    path: "/translator",
    icon: "pen",
    label: ["شغلي", "My work"],
    also: ["/tasks"],
    extra: [{ path: "/payroll", icon: "folder", label: ["مستحقاتي", "My payroll"] }],
  },
  // The classic menu's order for the operation: the mail first, then the tasks, the teams and the client codes.
  operation: {
    path: "/inbox",
    icon: "mail",
    label: ["ميلات واردة", "Incoming mail"],
    badge: "mail_unseen",
    extra: [
      { path: "/tasks", icon: "layers", label: ["التاسكات", "Tasks"], badge: "tasks_new" },
      { path: "/team", icon: "users", label: ["حالة الفرق", "Team status"] },
      { path: "/clients", icon: "tag", label: ["أكواد العملاء", "Client codes"] },
    ],
  },
  // The team leader's own: their tasks (the classic menu's badge is how many are being worked), who of their team is
  // free, and the client codes. The task page is theirs too (`/tasks/<code>`), titled by the screen they have.
  lead: {
    path: "/lead",
    icon: "target",
    label: ["تاسكاتي", "My tasks"],
    badge: "tasks_open",
    also: ["/tasks"],
    extra: [
      { path: "/lead/translators", icon: "users", label: ["حالة المترجمين", "Translator status"] },
      { path: "/clients", icon: "tag", label: ["أكواد العملاء", "Client codes"] },
    ],
  },
  // A Sales person's own line, in the classic menu's words: their mail, their number and address, the client codes.
  sales: {
    path: "/inbox",
    icon: "mail",
    label: ["ميلاتي", "My mail"],
    badge: "mail_unseen",
    extra: [
      { path: "/line", icon: "phone", label: ["رقمي وإيميلي", "My number & mail"] },
      { path: "/clients", icon: "tag", label: ["أكواد العملاء", "Client codes"] },
    ],
  },
  attendance: { path: "/attendance", icon: "timer", label: ["حضوري", "My attendance"] },
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
      {/* The check-in screen: over every page, and it cannot be put off until the person has checked in. */}
      <AttendanceGate />
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
  // The title follows the address, not the list: it is right before `me` has arrived too (every screen is looked at
  // until it has). Once it has, only the person's own screens are: the task page is "my work" to a translator and
  // "tasks" to the operation, and one address cannot be both.
  const startsWith = (prefix: string) => location.pathname === prefix || location.pathname.startsWith(`${prefix}/`);
  const looked = me.data ? screens : (Object.keys(SCREENS) as ScreenKey[]);
  const own = (key: ScreenKey) => [SCREENS[key].path, ...(SCREENS[key].extra ?? []).map((entry) => entry.path)].some(startsWith);
  // A screen's own pages first; the addresses it only shares (`also`) when no other screen of the person's owns them.
  const here = looked.find(own) ?? looked.find((key) => (SCREENS[key].also ?? []).some(startsWith));
  const extraHere = looked.flatMap((key) => SCREENS[key].extra ?? []).find((entry) => startsWith(entry.path));
  const sharedWith = (key: ScreenKey) => (SCREENS[key].also ?? []).some(startsWith) && !screens.some((other) => other !== key && own(other));
  // Before `me` has arrived an address two screens share is not named at all (not the wrong one for a moment).
  const claimants = looked.filter((key) => own(key) || (SCREENS[key].also ?? []).some(startsWith));
  const unsure = !me.data && claimants.length > 1;
  const count = (badge?: Badge) => (badge ? (me.data?.[badge] ?? 0) : 0);
  const title = startsWith("/notifications")
    ? t("التنبيهات", "Notifications")
    : unsure
      ? ""
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
                  // A screen whose other pages live under its own address (`/lead` and `/lead/translators`) must not
                  // light its first line on them as well: one line at a time.
                  end={(SCREENS[key].extra ?? []).some((entry) => entry.path.startsWith(`${SCREENS[key].path}/`))}
                  className={({ isActive }) => `nav__item${isActive || sharedWith(key) ? " is-active" : ""}`}
                >
                  <Icon name={SCREENS[key].icon} />
                  <span>{t(...SCREENS[key].label)}</span>
                  {count(SCREENS[key].badge) > 0 && <span className="nav__count is-hot">{count(SCREENS[key].badge)}</span>}
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
                    {count(entry.badge) > 0 && <span className="nav__count is-hot">{count(entry.badge)}</span>}
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
