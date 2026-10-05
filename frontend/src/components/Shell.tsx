import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, NavLink, Outlet, matchPath, useLocation } from "react-router";
import { csrfToken } from "../api/client";
import { warmPages } from "../api/prefetch";
import { useMe } from "../api/queries";
import type { Role, ScreenKey } from "../api/types";
import { useNavSections } from "../hooks/useNavSections";
import { usePreferences } from "../i18n/Preferences";
import { landWhenDrawn } from "../lib/anchor";
import { useOutboxProblems } from "../lib/outbox";
import { useRealtimeStatus } from "../realtime/RealtimeProvider";
import { AssignmentModal } from "./AssignmentModal";
import { AttendanceGate } from "./AttendanceGate";
import { CallOverlay } from "./CallOverlay";
import { ErrorBoundary } from "./ErrorBoundary";
import { Icon } from "./Icon";
import { NavSearch } from "./NavSearch";
import { NotificationToasts } from "./NotificationToasts";
import { ProfileMenu } from "./ProfileMenu";
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
 * line in the menu (the payslip). A person has all of a screen or none of it.
 */
export interface ScreenEntry {
  path: string;
  icon: string;
  label: [string, string];
  /** The menu section the screen's first line is in; its other lines are in it too unless they say otherwise. */
  section: Section;
  /** Where the line stands among the others of its section (smaller first; lines with none keep the order they were listed in). */
  order?: number;
  /** What the first line answers to, for a person who was given only a capability of another role. */
  needs?: Need;
  also?: string[];
  /** The number the menu shows beside the line, from `/me/` (the mail not opened, the tasks nobody has). */
  badge?: Badge;
  extra?: {
    path: string;
    icon: string;
    label: [string, string];
    /** Addresses that are this line's own pages without a line of their own (an interview's page belongs to the candidates). */
    also?: string[];
    badge?: Badge;
    danger?: boolean;
    adminOnly?: boolean;
    needs?: Need;
    section?: Section;
    order?: number;
  }[];
}

/**
 * The menu is drawn in the classic menu's sections (`dashboard/nav.py`), in this order, each under a heading that folds: the
 * work itself first, then recruitment, the people and their attendance, the money, the places and rules that are set once,
 * the person's own things, and the two that delete for good last of all. A person has the lines of their screens, and a
 * section with none of their lines is not drawn: a translator's menu is three short sections, the admin's all of them.
 */
export type Section = "work" | "hiring" | "people" | "accounts" | "settings" | "mine" | "danger";

export const SECTIONS: { key: Section; label: [string, string] }[] = [
  { key: "work", label: ["الشغل", "Work"] },
  { key: "hiring", label: ["التوظيف", "Recruitment"] },
  { key: "people", label: ["الموظفين", "People"] },
  { key: "accounts", label: ["الحسابات", "Accounts"] },
  { key: "settings", label: ["الإعدادات", "Settings"] },
  { key: "mine", label: ["حسابي", "My account"] },
  { key: "danger", label: ["منطقة خطر", "Danger zone"] },
];

/** A line some people see only because of what they were given: the recruitment pages are HR's, the attendance pages are anybody's who manages it. */
type Need = "recruit" | "manage";

/** The counters `/me/` carries for the menu. */
type Badge = "mail_unseen" | "tasks_new" | "tasks_open" | "unread_notifications";

export const SCREENS: Record<ScreenKey, ScreenEntry> = {
  // The admin's panel: the overview first (it opens the work), then the records in the work, the people and the settings in
  // theirs, and the log. The two that delete for good are last of all, in red, in a section of their own: out of the way of
  // everyday clicking.
  admin: {
    path: "/admin",
    icon: "chart",
    label: ["نظرة عامة", "Overview"],
    section: "work",
    order: 0,
    extra: [
      { path: "/admin/clients", icon: "contact", label: ["بيانات العملاء", "Client records"], order: 100 },
      { path: "/admin/settings", icon: "sliders", label: ["الإعدادات و AI", "Settings & AI"], section: "settings", order: 20 },
      { path: "/admin/simulate", icon: "beaker", label: ["محاكاة رسالة", "Simulate message"], section: "settings", order: 90 },
      { path: "/admin/audit", icon: "history", label: ["سجل النشاط", "Audit log"], section: "settings", order: 100 },
      { path: "/admin/reset-mail", icon: "trash", label: ["مسح الميلات", "Delete all mail"], danger: true, section: "danger" },
      { path: "/admin/reset-tasks", icon: "refresh", label: ["ريستارت التاسكات", "Reset all tasks"], danger: true, section: "danger" },
    ],
  },
  // The money screens: the month's sheet, the deductions, and (the admin's only) attendance and output; the payroll rules are
  // a setting. A payslip and a salary history open from the sheet.
  accounts: {
    path: "/accounts",
    icon: "calendar",
    label: ["كشف الشهر", "Monthly payroll"],
    section: "accounts",
    also: ["/accounts/lines", "/accounts/salary"],
    extra: [
      { path: "/accounts/attendance", icon: "timer", label: ["الحضور والإنتاج", "Attendance & output"], adminOnly: true },
      { path: "/accounts/violations", icon: "alert", label: ["المخالفات والخصومات", "Violations"] },
      { path: "/accounts/rules", icon: "list-checks", label: ["قواعد الحساب", "Payroll rules"], adminOnly: true, section: "settings", order: 30 },
    ],
  },
  // Human resources, in the classic menu's sections: recruitment (where HR starts), the people and their attendance, and the
  // places and rules HR sets once (under settings). The owner's own lines (the hiring decisions, the tests, the pay plans) are
  // drawn for the owner only. The lines that answer to a capability (`needs`) are also drawn for a person of another role who
  // was given it.
  hr: {
    path: "/hr/recruitment",
    icon: "chart",
    label: ["لوحة التوظيف", "Recruitment board"],
    section: "hiring",
    needs: "recruit",
    extra: [
      { path: "/hr/vacancies", icon: "building", label: ["الوظائف", "Vacancies"], needs: "recruit" },
      { path: "/hr/candidates", icon: "contact", label: ["المرشحين", "Candidates"], also: ["/hr/interviews"], needs: "recruit" },
      // The owner marks tests too, from the candidate's file: the reviewer's pages, under the owner's own line.
      { path: "/reviewer/tests", icon: "check-circle", label: ["اختبارات المرشحين", "Candidate tests"], adminOnly: true },
      // The owner decides a hire; HR does not see the queue (it is the owner's page).
      { path: "/hr/approvals", icon: "user-check", label: ["موافقات التعيين", "Hiring approvals"], adminOnly: true },
      { path: "/hr/employees", icon: "users", label: ["ملفات الموظفين", "Employee files"], needs: "recruit", section: "people" },
      { path: "/hr/attendance", icon: "users", label: ["لوحة الحضور", "Attendance board"], needs: "manage", section: "people" },
      { path: "/hr/schedules", icon: "calendar", label: ["جداول العمل", "Schedules"], needs: "manage", section: "people" },
      { path: "/hr/shifts", icon: "clock", label: ["الشيفتات", "Shifts"], needs: "manage", section: "people" },
      { path: "/hr/leave", icon: "hand", label: ["طلبات الإجازة", "Leave requests"], needs: "manage", section: "people" },
      { path: "/hr/overtime", icon: "clock", label: ["الأوفرتايم", "Overtime"], needs: "manage", section: "people" },
      { path: "/hr/report", icon: "chart", label: ["التقرير الشهري", "Monthly report"], needs: "manage", section: "people" },
      { path: "/hr/probation", icon: "eye", label: ["فترة الاختبار", "Probation"], needs: "recruit", section: "people" },
      { path: "/hr/performance", icon: "target", label: ["الأداء", "Performance"], needs: "recruit", section: "people" },
      { path: "/hr/complaints", icon: "thumbs-down", label: ["شكاوى العملاء", "Complaints"], needs: "recruit", section: "people" },
      { path: "/hr/salary-requests", icon: "refresh", label: ["طلبات تغيير الراتب", "Salary requests"], needs: "recruit", section: "people" },
      { path: "/hr/salary-plans", icon: "layers", label: ["خطط الرواتب", "Salary plans"], adminOnly: true, section: "settings", order: 40 },
      { path: "/hr/offices", icon: "map-pin", label: ["مواقع المكاتب", "Offices"], needs: "manage", section: "settings", order: 50 },
      { path: "/hr/devices", icon: "shield-check", label: ["أجهزة الحضور", "Devices"], needs: "manage", section: "settings", order: 60 },
      { path: "/hr/recruitment/settings", icon: "sliders", label: ["إعدادات التوظيف", "Recruitment settings"], needs: "recruit", section: "settings", order: 70 },
      { path: "/hr/questions", icon: "list-checks", label: ["بنك الأسئلة", "Question bank"], needs: "recruit", section: "settings", order: 80 },
    ],
  },
  // The reviewer has this one page and nothing else (section 24), under recruitment like the classic menu has it.
  reviewer: {
    path: "/reviewer/tests",
    icon: "check-circle",
    label: ["اختبارات المرشحين", "Candidate tests"],
    section: "hiring",
  },
  translator_home: {
    path: "/translator",
    icon: "pen",
    label: ["شغلي", "My work"],
    section: "work",
    order: 10,
    // The payslip in full is the translator's own too: it opens under the money screens' address.
    also: ["/tasks", "/accounts/lines"],
    extra: [{ path: "/payroll", icon: "folder", label: ["مستحقاتي", "My payroll"], section: "mine", order: 30 }],
  },
  // The operation's order: the mail first, then the chats, the tasks, the teams and the client codes.
  operation: {
    path: "/inbox",
    icon: "mail",
    label: ["ميلات واردة", "Incoming mail"],
    section: "work",
    order: 10,
    badge: "mail_unseen",
    extra: [
      { path: "/tasks", icon: "layers", label: ["التاسكات", "Tasks"], badge: "tasks_new", order: 30 },
      { path: "/team", icon: "users", label: ["حالة الفرق", "Team status"], order: 40 },
      { path: "/clients", icon: "tag", label: ["أكواد العملاء", "Client codes"], order: 90 },
    ],
  },
  // The team leader's own: their tasks (the badge is how many are being worked), who of their team is free, and the client
  // codes. The task page is theirs too (`/tasks/<code>`), titled by the screen they have.
  lead: {
    path: "/lead",
    icon: "target",
    label: ["تاسكاتي", "My tasks"],
    section: "work",
    order: 10,
    badge: "tasks_open",
    also: ["/tasks"],
    extra: [
      { path: "/lead/translators", icon: "users", label: ["حالة المترجمين", "Translator status"], order: 15 },
      { path: "/clients", icon: "tag", label: ["أكواد العملاء", "Client codes"], order: 90 },
      // A team leader marks the candidate tests assigned to them (and the ones nobody has taken): the reviewer's pages.
      { path: "/reviewer/tests", icon: "check-circle", label: ["اختبارات المرشحين", "Candidate tests"], section: "hiring" },
    ],
  },
  // A Sales person's own line: their mail, their number and address, the client codes.
  sales: {
    path: "/inbox",
    icon: "mail",
    label: ["ميلاتي", "My mail"],
    section: "work",
    order: 10,
    badge: "mail_unseen",
    extra: [
      { path: "/line", icon: "phone", label: ["رقمي وإيميلي", "My number & mail"], order: 30 },
      { path: "/clients", icon: "tag", label: ["أكواد العملاء", "Client codes"], order: 90 },
    ],
  },
  attendance: { path: "/attendance", icon: "timer", label: ["حضوري", "My attendance"], section: "mine", order: 10 },
  leave: { path: "/leave", icon: "calendar", label: ["إجازاتي", "My leave"], section: "mine", order: 20 },
  chats: { path: "/chats", icon: "message", label: ["الشات", "Chats"], section: "work", order: 20 },
  // The honour board is every employee's: who delivered the most this month. HR and the admin have the same address in their own
  // «people» section (the menu draws an address once, in the first section that has it), where it also opens a person's figures.
  performance: { path: "/hr/performance", icon: "target", label: ["الأداء", "Performance"], section: "mine", order: 15 },
};

/** One line of the menu: a screen's first line or one of its other pages, with the section it is drawn in. */
interface MenuLine {
  key: ScreenKey | "notifications";
  head: boolean;
  path: string;
  icon: string;
  label: [string, string];
  section: Section;
  order: number;
  badge?: Badge;
  danger?: boolean;
  also?: string[];
  /** Matches its address exactly, because another line of the same screen lives under it (`/lead` and `/lead/translators`). */
  end: boolean;
}

/** Where a line with no `order` of its own stands: the lines that have one are placed around it, the rest keep their listed order. */
const UNORDERED = 50;

/** The bell is every person's: the last line of «حسابي», with the count of what they have not read. */
const NOTIFICATIONS: MenuLine = {
  key: "notifications",
  head: false,
  path: "/notifications",
  icon: "bell",
  label: ["التنبيهات", "Notifications"],
  section: "mine",
  order: 40,
  badge: "unread_notifications",
  end: false,
};

/**
 * The lines this person has, each address once, in the classic menu's order: by section, and inside it by `order`
 * (lines that tie keep the order their screens are listed in).
 */
function menuLines(keys: ScreenKey[], isAdmin: boolean, can: { recruit: boolean; manage: boolean }): MenuLine[] {
  const allowed = (need?: Need) => !need || (need === "recruit" ? can.recruit : can.manage);
  const out: MenuLine[] = [];
  for (const key of keys) {
    const screen = SCREENS[key];
    const extras = (screen.extra ?? []).filter((entry) => (!entry.adminOnly || isAdmin) && allowed(entry.needs));
    if (allowed(screen.needs)) {
      out.push({
        key,
        head: true,
        path: screen.path,
        icon: screen.icon,
        label: screen.label,
        section: screen.section,
        order: screen.order ?? UNORDERED,
        badge: screen.badge,
        also: screen.also,
        end: extras.some((entry) => entry.path.startsWith(`${screen.path}/`)),
      });
    }
    for (const entry of extras) {
      out.push({
        key,
        head: false,
        path: entry.path,
        icon: entry.icon,
        label: entry.label,
        section: entry.section ?? screen.section,
        order: entry.order ?? UNORDERED,
        badge: entry.badge,
        danger: entry.danger,
        also: entry.also,
        end: extras.some((other) => other.path.startsWith(`${entry.path}/`)),
      });
    }
  }
  out.push(NOTIFICATIONS);
  const seen = new Set<string>();
  const sectionAt = (line: MenuLine) => SECTIONS.findIndex((section) => section.key === line.section);
  return out
    .filter((line) => !seen.has(line.path) && seen.add(line.path))
    .sort((a, b) => sectionAt(a) - sectionAt(b) || a.order - b.order);
}

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
      {/* A call from a colleague, ringing or in progress: on every page, because it can come in anywhere. */}
      <CallOverlay />
    </ToastProvider>
  );
}

/** After the page the person is on has had its turn. */
const WARM_DELAY_MS = 400;

function Frame() {
  const { t, lang, setLang, theme, setTheme } = usePreferences();
  const me = useMe();
  const queryClient = useQueryClient();
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

  // An address that ends in `#section` (the menu's search sends you to one) lands on that part once the page has drawn it.
  useEffect(() => {
    if (!location.hash) return;
    return landWhenDrawn(location.hash.slice(1));
  }, [location.pathname, location.hash, location.key]);

  const user = me.data?.user;
  const unread = me.data?.unread_notifications ?? 0;
  const unreadChats = me.data?.unread_chats ?? 0;
  const unsent = useOutboxProblems().length;
  const screens = (me.data?.screens ?? []).filter((key) => Object.hasOwn(SCREENS, key));
  const isAdmin = Boolean(user?.is_admin);
  const canRecruit = me.data?.can.recruit ?? false;
  const canManage = me.data?.can.manage_attendance ?? false;
  const screensKey = screens.join(",");
  // The lines are rebuilt only when the person's screens change: the search indexes them. Until the server has said who this is
  // there is no menu at all (not the bell alone): a menu that settles on its first look must not settle on half of itself.
  const known = Boolean(me.data);
  const lines = useMemo(
    () => (known ? menuLines(screens, isAdmin, { recruit: canRecruit, manage: canManage }) : []),
    [known, screensKey, isAdmin, canRecruit, canManage],
  );
  // The pages in the person's own menu are asked for in the background, so the first click on each opens on data and
  // not on a loading screen (see `api/prefetch.ts` for which, and why only these).
  const menuPaths = lines.map((line) => line.path).join(",");
  const personId = me.data?.user.id;
  useEffect(() => {
    const account = me.data;
    if (!account || !menuPaths) return;
    let stopped = false;
    const timer = window.setTimeout(
      () => void warmPages(queryClient, menuPaths.split(","), account, () => stopped),
      WARM_DELAY_MS,
    );
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
    // Once per person and per menu: `me` itself is asked again on every doorbell, so it is not a dependency.
  }, [personId, menuPaths, queryClient]);
  const searchLines = useMemo(
    () =>
      lines.map((line) => ({
        path: line.path,
        icon: line.icon,
        label: line.label,
        where: SECTIONS.find((section) => section.key === line.section)!.label,
      })),
    [lines],
  );
  // The title follows the address, not the list: it is right before `me` has arrived too (every screen is looked at
  // until it has). Once it has, only the person's own screens are: the task page is "my work" to a translator and
  // "tasks" to the operation, and one address cannot be both.
  const startsWith = (prefix: string) => location.pathname === prefix || location.pathname.startsWith(`${prefix}/`);
  const looked = me.data ? screens : (Object.keys(SCREENS) as ScreenKey[]);
  const own = (key: ScreenKey) =>
    [SCREENS[key].path, ...(SCREENS[key].extra ?? []).flatMap((entry) => [entry.path, ...(entry.also ?? [])])].some(startsWith);
  // A screen's own pages first; the addresses it only shares (`also`) when no other screen of the person's owns them.
  const here = looked.find(own) ?? looked.find((key) => (SCREENS[key].also ?? []).some(startsWith));
  // The longest address wins: `/hr/recruitment/settings` is its own page, not the board's.
  const extraHere = looked
    .flatMap((key) => SCREENS[key].extra ?? [])
    .filter((entry) => startsWith(entry.path) || (entry.also ?? []).some(startsWith))
    .sort((a, b) => b.path.length - a.path.length)[0];
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

  // Which line is lit: the one whose address the page is under (a line with a sibling under its own address matches exactly,
  // so only one of them is lit), or the one whose screen shares the address with nobody else the person has.
  const lit = (line: MenuLine) =>
    Boolean(matchPath({ path: line.path, end: line.end }, location.pathname)) ||
    (line.head ? line.key !== "notifications" && sharedWith(line.key) : (line.also ?? []).some(startsWith));
  const groups = SECTIONS.map((section) => ({ ...section, lines: lines.filter((line) => line.section === section.key) })).filter(
    (group) => group.lines.length > 0,
  );
  const standingIn = groups.find((group) => group.lines.some(lit))?.key ?? null;
  const nav = useNavSections(
    groups.map((group) => group.key),
    standingIn,
  );
  // A shut section still says what is waiting in it: the mail badge is the whole reason anyone looks at the menu.
  const waiting = (group: (typeof groups)[number]) =>
    group.lines.reduce(
      (sum, line) => sum + count(line.badge) + (line.key === "chats" ? unreadChats + (unsent > 0 ? 1 : 0) : 0),
      0,
    );
  const openMenu = useCallback(() => setDrawer(true), []);

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

        <NavSearch lines={searchLines} onShortcut={openMenu} />

        {groups.length > 0 && (
          <div className="nav-tools">
            <button
              type="button"
              className={`nav-tools__btn${nav.anyOpen ? "" : " is-folded"}`}
              id="navFoldAll"
              aria-controls="sideNav"
              aria-expanded={nav.anyOpen}
              onClick={nav.foldAll}
            >
              <Icon name="chevron-down" size="sm" className="nav-tools__ic" />
              <span>{nav.anyOpen ? t("اقفل كل القوايم", "Collapse all") : t("افتح كل القوايم", "Expand all")}</span>
            </button>
          </div>
        )}

        <nav className="nav" id="sideNav">
          {groups.map((group) => {
            const opened = nav.isOpen(group.key);
            const rolled = waiting(group);
            return (
              <div className={`nav__group${opened ? " is-open" : ""}`} data-nav-group={group.key} key={group.key}>
                <button
                  type="button"
                  className="nav__label nav__head"
                  data-section={group.key}
                  aria-expanded={opened}
                  aria-controls={`nav-items-${group.key}`}
                  onClick={() => nav.toggle(group.key)}
                >
                  <span>{t(...group.label)}</span>
                  {!opened && rolled > 0 && <span className="nav__count nav__roll is-hot">{rolled}</span>}
                  <Icon name="chevron-down" size="sm" className="nav__chev" />
                </button>
                <div className="nav__items" id={`nav-items-${group.key}`} hidden={!opened}>
                  {group.lines.map((line) => {
                    const here = lit(line);
                    return (
                      <Link
                        key={line.path}
                        to={line.path}
                        aria-current={here ? "page" : undefined}
                        className={`nav__item${here ? " is-active" : ""}${line.danger ? " nav__item--danger" : ""}`}
                      >
                        <Icon name={line.icon} />
                        <span>{t(...line.label)}</span>
                        {count(line.badge) > 0 && <span className="nav__count is-hot">{count(line.badge)}</span>}
                        {line.key === "chats" && unsent > 0 && (
                          <span className="nav__count is-hot" title={t("فيه رسالة ماتبعتتش", "A message did not go")}>
                            <Icon name="alert" size="sm" />
                          </span>
                        )}
                        {line.key === "chats" && unreadChats > 0 && <span className="nav__count is-hot">{unreadChats}</span>}
                      </Link>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </nav>

        {/* The three public pages the WhatsApp and Facebook reviews ask for: reachable, and read about once, so small. */}
        <div className="side-foot">
          <div className="side-legal">
            <a href="/privacy/">{t("الخصوصية", "Privacy")}</a>
            <a href="/terms/">{t("الشروط", "Terms")}</a>
            <a href="/data-deletion/">{t("حذف البيانات", "Data deletion")}</a>
          </div>
        </div>
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
          {user && <ProfileMenu user={user} roleLabel={ROLE_LABELS[user.role]?.[lang === "ar" ? 0 : 1] ?? user.role} />}
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
