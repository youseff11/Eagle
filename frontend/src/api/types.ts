export type Lang = "ar" | "en";

/** A screen that has been ported to this app. The menu and the home page follow what the server lists. */
export type ScreenKey = "translator_home" | "chats";
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
  /** The longest message this person may write: to one client, to a client group (its prefix counts), inside. */
  limits: { to_client: number; to_client_group: number; inside: number };
  /** The ported screens that are switched on for this person (`dashboard/newui.py`). */
  screens: ScreenKey[];
  unread_notifications: number;
  /** Messages waiting in any chat tab (`services.unread_chat_total`). */
  unread_chats: number;
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

/** The three lists of the chats page. A role gets only the ones `me.chats.types` names. */
export type ChatKind = "clients" | "groups" | "staff";

/** One row of `/api/v1/chats/`: a client, a group or a colleague (`api._conversation_json`, `_group_json`). */
export interface ChatRow {
  /** `CL-0001` for a client, `g12` for a group, `u5` for a colleague. */
  code: string;
  group: boolean;
  /** An internal work group: nothing in it reaches a client. */
  team?: boolean;
  staff?: boolean;
  /** What is typed here ends up on a client's phone. */
  reaches_client?: boolean;
  /** The room behind it (0: a colleague nobody has written to yet). */
  room?: number;
  /** The classic page of this conversation. */
  url: string;
  /** A client code, never a name, unless the person may know the name. */
  label: string;
  initials?: string;
  client_code?: string;
  text: string;
  outgoing: boolean;
  status: string;
  receipt: string;
  /** The time of day and the date, written by the server (Cairo, 12 hours). */
  time: string;
  date: string;
  channel: string;
  window_open: boolean;
  minutes_left: number;
  unread: number;
}

export interface ChatListResponse {
  ok: true;
  items: ChatRow[];
}

export interface ThreadFile {
  id: number;
  url: string;
  name: string;
  size: number;
  mime: string;
  voice: boolean;
  audio: boolean;
  length: string;
  image: boolean;
}

export interface Reaction {
  kind: string;
  count: number;
  mine: boolean;
  who: string[];
}

/** One bubble (`api._thread_entry_json`). `kind` is `in` (the client's) or `out` (ours). */
export interface ThreadEntry {
  uid: string;
  id: number;
  kind: "in" | "out";
  body: string;
  subject: string;
  channel: string;
  status: string;
  error: string;
  sender: string;
  /** Who wrote it, by id (0: the client, or nobody). A name is not unique. */
  sender_id: number;
  task_code: string;
  is_delivery: boolean;
  quote: string;
  quote_who: string;
  time: string;
  date: string;
  files: ThreadFile[];
  mine: boolean;
  receipt: string;
  seen_by: string[];
  forwarded: boolean;
  reactions: Reaction[];
}

/** GET /api/v1/{clients,groups,staff}/.../messages/ */
export interface ThreadResponse {
  ok: true;
  client: ChatRow;
  messages: ThreadEntry[];
}

/** POST .../send/: the message is in the thread; `delivered` says whether it also got where it was going. */
export interface SendResponse {
  ok: true;
  delivered: boolean;
  /** Why not, in Arabic, when `delivered` is false. */
  error: string;
  messages: ThreadEntry[];
  client: ChatRow;
}

/** POST .../read/ */
export interface MovedResponse {
  ok: true;
  /** Whether the read mark moved (it did not, if it was there already). */
  moved: boolean;
}
