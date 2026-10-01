export type Lang = "ar" | "en";

/** A screen that has been ported to this app. The menu and the home page follow what the server lists. */
export type ScreenKey = "translator_home";
export type Theme = "dark" | "light";

export type Role =
  | "admin"
  | "operation"
  | "team_lead"
  | "translator"
  | "hr"
  | "reviewer"
  | "accounting"
  | "sales";

/** GET /api/v1/me/ */
export interface MeResponse {
  ok: true;
  version: number;
  user: {
    id: number;
    username: string;
    name: string;
    short_name: string;
    initials: string;
    role: Role;
    is_admin: boolean;
    lang: Lang;
    theme: Theme;
  };
  chats: { types: string[] };
  /** The ported screens that are switched on for this person (`dashboard/newui.py`). */
  screens: ScreenKey[];
  unread_notifications: number;
  realtime: { path: string; ping_seconds: number };
  server_time: string;
}

export type NotificationLevel = "info" | "success" | "warning" | "danger";

export interface NotificationItem {
  id: number;
  level: NotificationLevel;
  title_ar: string;
  title_en: string;
  body_ar: string;
  body_en: string;
  url: string;
  sound: boolean;
  /** The time of day, already formatted by the server (Cairo, 12 hours). */
  created: string;
  /** The date, formatted by the server. */
  date: string;
  read: boolean;
}

/** GET /api/v1/notifications/ */
export interface NotificationsResponse {
  ok: true;
  items: NotificationItem[];
  next_before: number | null;
  unread: number;
}

/** POST /api/v1/notifications/read/ */
export interface ReadResponse {
  ok: true;
  updated: number;
  unread: number;
}

/** The part of /api/heartbeat/ this app reads. */
export interface HeartbeatResponse {
  ok: true;
  /** The attendance screen that is due, or null: `{ kind: "check_in" | "check_out" | "extra", ... }`. */
  attendance: { kind?: string } | null;
  /** An assignment waiting for an answer (the 60-second accept screen), or null. */
  pending: unknown;
  /** A call ringing for this person, or null. */
  call: unknown;
  /** Moves whenever anything on the boards moves; says *that*, never what or for whom. */
  live?: string;
}

/** A word in both languages, written by the server (`{ value, ar, en }`). */
export interface Labelled {
  value: string;
  ar: string;
  en: string;
}

export interface DeskTask {
  code: string;
  title: string;
  status: Labelled & { tone: string };
  priority: Labelled;
  origin: (Labelled & { icon: string }) | null;
  /** A client code. The translator is never given a name. */
  client: string;
  source_lang: string;
  target_lang: string;
  /** The translator's own date, formatted by the server in both languages; null when there is none. */
  due: { ar: string; en: string } | null;
  due_state: "none" | "ok" | "soon" | "late" | "done";
  can_ask_more_time: boolean;
  /** The classic task page, which is not ported yet. */
  url: string;
}

/** GET /api/v1/translator/home/ */
export interface TranslatorHomeResponse {
  ok: true;
  rating: number;
  open: DeskTask[];
  done: { code: string; status: Labelled & { tone: string }; url: string }[];
  rating_events: { delta: string; reason_ar: string; reason_en: string }[];
}
