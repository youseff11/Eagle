export type Lang = "ar" | "en";
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
}
