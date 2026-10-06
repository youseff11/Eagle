export type Lang = "ar" | "en";

/** A screen that has been ported to this app. The menu and the home page follow what the server lists. */
/** A moment the server wrote in both languages (Cairo, twelve hours) - the same shape as `Stamp`. */
type Both = { ar: string; en: string };

/**
 * What the check-in screen asks right now (`attendance.gate_for`): the check-in, which stays until it is done; the
 * reminder after the shift (check out, or press extra time); and the one while extra time runs.
 */
export type AttendanceGate =
  | {
      kind: "check_in";
      date: string;
      shift: string;
      start: Both;
      end: Both;
      grace_until: Both;
      grace: number;
      /** How many minutes late this person already is (the whole delay counts once past the grace). */
      late_now: number;
      needs_location: boolean;
      checkout_after: number;
    }
  | { kind: "check_out"; date: string; shift: string; end: Both; deadline: Both; needs_location: boolean }
  | { kind: "extra"; date: string; shift: string; end: Both; extra_since: Both; deadline: Both; needs_location: boolean };

export type PunchAction = "check_in" | "check_out" | "break_start" | "break_end" | "extra_start";

/** POST /api/attendance/punch/: a refusal is `ok: false` with its reason in both languages, not an HTTP error. */
export type PunchAnswer =
  | { ok: true; action: PunchAction; at: string; late_minutes: number; overtime_minutes: number }
  | { ok: false; error: string; ar?: string; en?: string };

/** GET /api/v1/attendance/: the person's own card. */
export interface AttendanceCard {
  ok: true;
  enabled: boolean;
  work_date: string;
  plan: {
    working: boolean;
    label: string;
    mode: Labelled | null;
    start: Both | null;
    end: Both | null;
  };
  needs_location: boolean;
  day: {
    state: "none" | "open" | "closed";
    check_in: Both | null;
    check_out: Both | null;
    extra_started_at: Both | null;
    extra_running: boolean;
    break_minutes: number;
    on_break: boolean;
    hours: string;
    late_minutes: number;
    needs_review: boolean;
    review_reason: string;
    checkout_missed: boolean;
    /** The end of the shift as a moment (ISO); `null` on a day nobody is rostered. */
    shift_end: string | null;
  };
  conf: { grace_minutes: number; missing_checkout_after_minutes: number };
  summary: {
    scheduled_days: number;
    present_days: number;
    office_days: number;
    remote_days: number;
    late_days: number;
    late_minutes: number;
    short_minutes: number;
    overtime_minutes: number;
  };
  recent: {
    date: string;
    mode: Labelled | null;
    schedule: string;
    check_in: Both | null;
    check_out: Both | null;
    hours: string;
    status: Labelled & { tone: string };
    late_minutes: number;
    overtime_minutes: number;
    checkout_missed: boolean;
  }[];
  devices: { label: string; status: "approved" | "pending" | "rejected" }[];
}

export type ScreenKey = "admin" | "accounts" | "hr" | "reviewer" | "leave" | "translator_home" | "operation" | "lead" | "sales" | "support" | "attendance" | "chats" | "performance";
export type Theme = "dark" | "light";

export type Role =
  | "admin"
  | "operation"
  | "team_lead"
  | "translator"
  | "hr"
  | "reviewer"
  | "accounting"
  | "sales"
  | "support";

/** GET /api/search/tasks/?q=: the tasks the menu's search found, each as this person may read it (the client by code unless they may know the name). */
export interface TaskSearchResponse {
  ok: true;
  items: {
    code: string;
    title: string;
    origin: string;
    status_ar: string;
    status_en: string;
    client: string;
    /** The classic address: the app builds its own from `code`. */
    href: string;
  }[];
}

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
    /** The person's own picture (a `/files/...` address), or null: the initials are drawn then. */
    avatar: string | null;
    role: Role;
    is_admin: boolean;
    lang: Lang;
    theme: Theme;
  };
  /** The lists this role has; and whether this person may open an internal work group. */
  chats: { types: string[]; can_create_group?: boolean };
  /** The longest message this person may write: to one client, to a client group (its prefix counts), inside. */
  limits: {
    to_client: number;
    to_client_group: number;
    inside: number;
    /** Files in one message: how many, how big each, how big all together (bytes). */
    files: { count: number; bytes: number; total_bytes: number };
    /** A voice note: the longest it may run (seconds) and the biggest it may be (bytes). */
    voice: { seconds: number; bytes: number };
  };
  /** The screens in this person's menu: their role's, or - the admin's - the ones the admin oversees (`dashboard/newui.py`). */
  screens: ScreenKey[];
  /** What the menu's lines answer to: a person of one role can be given a capability of another (the attendance pages of HR). */
  can: { manage_attendance: boolean; recruit: boolean; review_tests: boolean; approve_hiring: boolean };
  unread_notifications: number;
  /** Messages waiting in any chat tab (`services.unread_chat_total`). */
  unread_chats: number;
  /** Client conversations with something unread: the number on the clients tab (chats, not messages; `services.unread_chat_counts`). */
  unread_client_chats: number;
  /** The same for every tab: how many chats of it have something unread, for the number on its button (chats, not messages). */
  unread_chat_tabs: Record<"clients" | "groups" | "staff", number>;
  /** Mail conversations this person has not opened, and tasks nobody has been given yet (the operation's menu badges). */
  mail_unseen: number;
  tasks_new: number;
  /** A team leader's tasks that are being worked: their menu's one badge. */
  tasks_open: number;
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
  /** The person who wrote it (technical support's announcement), or `null` for the system's own. */
  sender?: { id: number; name: string; initials: string; avatar: string | null; role: Role } | null;
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
  attendance: AttendanceGate | null;
  /** An assignment waiting for an answer (the 60-second accept screen), or null. */
  pending: PendingAssignment | null;
  /** A call ringing for this person, or null. */
  call: CallInfo | null;
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
  /** `decision`: HR or the admin let the penalty go (`forgiven`: the stars were given back), applied it, or has not looked yet. */
  rating_events: { delta: string; reason_ar: string; reason_en: string; decision: "pending" | "confirmed" | "forgiven" }[];
}

/** A hand-off waiting for an answer, as `/api/heartbeat/` tells it (`api._pending_json`): what the popup draws. */
export interface PendingAssignment {
  id: number;
  task_code: string;
  task_title: string;
  /** The classic task page. */
  task_url: string;
  /** A client code, never a name. */
  client: string;
  role: Role;
  seconds_left: number;
  /** The whole window, in seconds. */
  window: number;
  assigned_by: string;
  files_url: string;
  open_url: string;
  priority: string;
  /** The date that governs this person, in English (`2026-10-02 5:30 PM`). */
  deadline: string;
  deadline_iso: string;
  /** The sender's note, with the client's name taken out. */
  note: string;
}

/** GET /api/v1/assignments/<id>/ : a hand-off read before it is taken. */
export interface AssignmentResponse {
  ok: true;
  assignment: {
    id: number;
    status: "pending" | "accepted" | "declined" | "expired" | "cancelled";
    /** Waiting for an answer and still inside the window: the one state with buttons. */
    pending: boolean;
    seconds_left: number;
    window: number;
    role: Role;
    note: string;
    from: string | null;
    mine: boolean;
  };
  task: {
    code: string;
    title: string;
    origin: (Labelled & { icon: string }) | null;
    client: string;
    source_lang: string;
    target_lang: string;
    due: Stamp | null;
    due_iso: string;
    description: string;
    files: TaskFile[];
  };
}

/** One row of the operation's task list (`api_ops.tasks`). */
export interface OpsTaskRow {
  code: string;
  title: string;
  origin: (Labelled & { icon: string }) | null;
  priority: Labelled;
  /** A code for the operation; the name only for the admin, who may know it. */
  client: string;
  status: Labelled & { tone: string };
  team_lead: string | null;
  translator: string | null;
  /** The client's date (the operation answers for the promise), as month-day and the time. */
  due: Stamp | null;
  due_state: "none" | "ok" | "soon" | "late" | "done";
}

/** GET /api/v1/tasks/?status= */
export interface TasksResponse {
  ok: true;
  status: string;
  counters: { new: number; open: number; review: number; ready: number };
  /** Every status, for the tabs. */
  statuses: (Labelled & { tone: string })[];
  tasks: OpsTaskRow[];
}

export type Channel = "whatsapp" | "email";

/** One task as the operation reads it (`api_ops.task`). */
export interface OpsTask {
  /** Technical support reads the task and nothing of the client's or the work's: the page leaves those cards out. */
  watching?: boolean;
  code: string;
  title: string;
  status: Labelled & { tone: string };
  priority: Labelled;
  origin: (Labelled & { icon: string }) | null;
  /** A code for the operation; the name beside it for the admin, who may know it. */
  client: string;
  client_code: string;
  source_lang: string;
  target_lang: string;
  /** The client's date, which the operation answers for. */
  due: Stamp | null;
  due_state: "none" | "ok" | "soon" | "late" | "done";
  /** What the translator was given (the leader keeps the difference to review in). */
  translator_due: Stamp | null;
  description: string;
  people: { operation: string | null; team_lead: string | null; translator: string | null };
  /** Who has been asked to take it and has not answered yet, and how long they have. */
  waiting_for: { name: string; seconds_left: number } | null;
  files: { original: TaskFile[]; translation: (TaskFile & { at: Stamp | null })[] };
  chat: { url: string; label_ar: string; label_en: string } | null;
  client_chat_url: string | null;
  can: {
    assign_lead: boolean;
    take_over: boolean;
    deliver: boolean;
    cancel: boolean;
    add_member: boolean;
    /** The same material, a new job: the operation's own. */
    new_request: boolean;
    /** The client's date, which the operation promises. */
    set_deadline: boolean;
    /** The word count: the operation, the admin and the task's own team leader. */
    set_words: boolean;
  };
  /** What the task's team leader (and the admin) may do on it; `null` for everybody else. */
  lead: LeadTools | null;
  leads: { id: number; name: string; online: boolean; tasks: number }[];
  handover: { by: string | null; at: Stamp | null } | null;
  deliver: {
    files: { id: number; name: string; size: string; sender: string | null; final: boolean }[];
    channel: Channel;
    reachable: boolean;
  } | null;
  group_candidates: { id: number; name: string; role: Role }[];
  words: { state: "empty" | "auto" | "confirmed" | string; value: number | null };
  requirements: { id: number; kind: Labelled; author: string | null; text: string }[];
  deliveries: { id: number; at: Stamp | null; channel: Channel; files: number; by: string | null; status: "sent" | "failed" | string; error: string }[];
  /** The client's own messages on this task that this person may read. */
  messages: { id: number; channel: Channel; at: Stamp | null; body: string; files: TaskFile[] }[];
  history: { id: number; name: string; initials: string; role: Role; at: Stamp | null; status: string }[];
}

/** GET /api/v1/tasks/<code>/ */
export interface OpsTaskResponse {
  ok: true;
  task: OpsTask;
}

/** GET /api/v1/task-form/ : what the new-task form starts from, and what it offers (`api_ops.task_start`). */
export interface TaskStartResponse {
  ok: true;
  from_task: { code: string; title: string } | null;
  client_code: string;
  /** The client's own messages the task is made from (only those this person may read). */
  messages: { id: number; channel: Channel; at: Stamp | null; subject: string; body: string; files: TaskFile[] }[];
  /** The files ticked on the way here; empty means "every file of the messages". */
  picked: TaskFile[];
  initial: { client: number | null; title: string; description: string; source_lang: string };
  requirements: { id: number; kind: Labelled; author: string | null; text: string }[];
  clients: { id: number; code: string; label: string }[];
  languages: { code: string; ar: string; en: string }[];
  quick_languages: string[];
  priorities: Labelled[];
}

export type PresenceState = "free" | "busy" | "shift" | "off";

export interface TeamMember {
  id: number;
  name: string;
  initials: string;
  languages: string;
  state: PresenceState;
  seen: Stamp;
  rating: number;
  /** At most two codes of the tasks they have open. */
  tasks: string[];
}

/** GET /api/v1/team/ */
export interface TeamResponse {
  ok: true;
  leads: {
    id: number;
    name: string;
    initials: string;
    online: boolean;
    rating: number;
    tasks: number;
    counts: { free: number; busy: number; offline: number };
    members: TeamMember[];
  }[];
}

/** GET /api/v1/announce/: what technical support may tell everybody, and what it already did. */
export interface AnnounceResponse {
  ok: true;
  /** How many people an announcement reaches (everybody active but the sender). */
  reach: number;
  limits: { title: number; body: number };
  recent: { id: number; title: string; body: string; reached: number; by: string | null; at: Stamp }[];
}

/** A moment the server wrote in both languages (Cairo, twelve hours). */
export interface Stamp {
  ar: string;
  en: string;
}

/** GET /api/v1/translator/payroll/ */
export interface PayrollResponse {
  ok: true;
  year: number;
  month: number;
  periods: { year: number; month: number }[];
  daily_target_words: number;
  /** Money is text, to the cent. `null` while the month has not been run. */
  line: {
    id: number;
    base_salary: string;
    production_bonus: string;
    deductions: string;
    net: string;
    pending_bonus: string;
    /** The classic page with the full breakdown. */
    url: string;
  } | null;
  days: { date: string; status: Labelled & { tone: string }; words: number }[];
  violations: { date: string; kind: Labelled; reason: string; status: "approved" | "pending" | "rejected" }[];
}

export interface TaskFile {
  id: number;
  url: string;
  name: string;
  size: string;
  image: boolean;
}

export interface AiIssue {
  location?: string;
  severity?: "high" | "medium" | "low";
  source_excerpt?: string;
  translation_excerpt?: string;
  issue_ar?: string;
  issue_en?: string;
  correct_meaning_ar?: string;
}

/** The task page as the translator reads it (`api_v1.translator_task`). */
export interface TranslatorTask {
  code: string;
  title: string;
  status: Labelled & { tone: string };
  priority: Labelled;
  origin: (Labelled & { icon: string }) | null;
  /** A client code. The translator is never given a name. */
  client: string;
  source_lang: string;
  target_lang: string;
  due: Stamp | null;
  due_state: "none" | "ok" | "soon" | "late" | "done";
  description: string;
  people: { operation: string | null; team_lead: string | null; translator: string | null };
  /** Whether this task is the person's own (the admin may look at any). */
  mine: boolean;
  files: { original: TaskFile[]; translation: (TaskFile & { at: Stamp | null })[] };
  can_upload: boolean;
  translation_missing: boolean;
  under_review: boolean;
  extension: {
    can_ask: boolean;
    pending: { minutes: number; reason: string } | null;
    last: { status: "approved" | "declined"; minutes: number; note: string; at: Stamp | null } | null;
  };
  /** Where "open the group" leads: a classic address (it hands on to the new chat when that is switched on). */
  chat: { url: string; label_ar: string; label_en: string } | null;
  requirements: { id: number; kind: Labelled; author: string | null; text: string }[];
  history: { id: number; name: string; initials: string; role: Role; at: Stamp | null; status: string }[];
  ai: {
    visible: boolean;
    enabled: boolean;
    checks: { id: number; status: "running" | "clean" | "issues" | "error"; count: number; automatic: boolean; summary: string; at: Stamp | null }[];
  };
}

/** GET /api/v1/translator/tasks/<code>/ */
export interface TranslatorTaskResponse {
  ok: true;
  task: TranslatorTask;
}

/** POST /api/tasks/<code>/ai-check/ - the classic endpoint, whose answer is `ok: false` when the check itself failed. */
export interface AiCheckAnswer {
  ok: boolean;
  status?: "clean" | "issues" | "error";
  summary?: string;
  issues?: AiIssue[];
  error?: string;
  count?: number;
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
  /** A colleague's role (a staff row only): technical support is tagged as such in the lists and the header. */
  role?: Role;
  /** What is typed here ends up on a client's phone. */
  reaches_client?: boolean;
  /** The room behind it (0: a colleague nobody has written to yet). */
  room?: number;
  /** The classic page of this conversation. */
  url: string;
  /** A client code, never a name, unless the person may know the name. */
  label: string;
  initials?: string;
  /** A colleague's own picture (`/files/...`), when they put one: a staff row only, never a client's or a group's. */
  avatar?: string | null;
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
  /** The picture of the colleague who wrote it, when they have one (never a client's). */
  sender_avatar?: string | null;
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
  /** The buttons under a client's message are for this person (the operation and the admin, on what a client wrote). */
  actions: boolean;
  /** The message carries a document (not only words or a voice note): "received" and "turn into a task" mean something. */
  has_docs: boolean;
  /** It is already the source of a task (`task_code` says which). */
  has_task: boolean;
  /** Who has said "received" for it, if anybody. */
  claimed_by: string;
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

/** POST /api/v1/chats/react/: the reactions of that one message as they are now (the same one again took it back). */
export interface ReactResponse {
  ok: true;
  uid: string;
  reactions: Reaction[];
}

/**
 * POST /api/v1/chats/forward/: the messages are in the other conversation (`code`); `delivered` is false when they
 * got there and then did not reach where they were going (a client's phone, a group's relay), with the reason in `message`.
 */
export interface ForwardResponse {
  ok: true;
  delivered: boolean;
  message: string;
  code: string;
}

/** A colleague as the work-group pickers show them: by id, never by anything a client could be known by. */
export interface Person {
  id: number;
  name: string;
  initials: string;
  avatar?: string | null;
  role: Role;
}

/** GET /api/v1/people/: everybody a work group could be opened with (only for those who may open one). */
export interface PeopleResponse {
  ok: true;
  people: Person[];
}

/** GET /api/v1/groups/<id>/members/: who is in a group, whether this person may add to it, and to whom. */
export interface MembersResponse {
  ok: true;
  members: Person[];
  can_add: boolean;
  addable: Person[];
}

/** POST /api/v1/groups/: the group that was opened (`code` is `g<room>`). */
export interface GroupCreated {
  ok: true;
  room: number;
  code: string;
}

/** POST /api/v1/groups/<id>/members/add/: somebody was added; `message` says who was left out and why. */
export interface MembersAdded {
  ok: true;
  message: string;
  added: string[];
}

/** POST /api/v1/tasks/<code>/hand-in/: the files are the task's translation and it went to review. */
export interface HandedIn {
  ok: true;
  code: string;
}

/** GET .../file-tasks/: the tasks files sent here could be for (several: the sender must choose). */
export interface FileTasksResponse {
  ok: true;
  tasks: { code: string; title: string }[];
}

/** POST .../read/ */
export interface MovedResponse {
  ok: true;
  /** Whether the read mark moved (it did not, if it was there already). */
  moved: boolean;
}

/** A file of a letter or of our reply (`api_mail._file_json`): `url` is a path on this site, never another one. */
export interface MailFile {
  id: number;
  url: string;
  name: string;
  size: string;
  image: boolean;
  audio: boolean;
  length: string;
}

/** One conversation in the list (`api_mail._row_json`). */
export interface MailRow {
  key: string;
  /** The letter the row opens: any letter's id opens the conversation it is in. */
  id: number;
  /** The client as this person may know it (a code for the operation); empty for an unknown sender. */
  from: string;
  code: string;
  count: number;
  at: Stamp | null;
  subject: string;
  snippet: string;
  unread: boolean;
  blocked: boolean;
  answered: boolean;
  tasks: string[];
  files: number;
  claimers: string[];
}

/** GET /api/v1/mail/threads/?state=&q= */
export interface MailListResponse {
  ok: true;
  state: string;
  q: string;
  threads: MailRow[];
  /** Conversations this person has not opened: the badge. */
  unseen: number;
  /** Conversations nobody has pressed "received" on. */
  unclaimed: number;
  /** Letters hidden from the operation by the rate rule: the admin only. */
  blocked: number;
  mail: { configured: boolean; last_fetch: Stamp | null; last_count: number; last_error: string };
}

/** A letter of the client's inside a conversation. */
export interface MailLetter {
  kind: "in";
  id: number;
  from: string;
  code: string;
  at: Stamp | null;
  snippet: string;
  body: string;
  /** Not opened by this person before now. */
  unseen: boolean;
  blocked: boolean;
  task: string | null;
  claimed_by: string | null;
  files: MailFile[];
  can_confirm: boolean;
  can_convert: boolean;
  /** The ids of the files that are documents (not voice notes): what a task can be made from. */
  documents: number[];
  /** The raw address, for the admin alone. */
  raw: string;
  open: boolean;
}

/** One of our own replies inside a conversation. */
export interface MailReply {
  kind: "out";
  id: number;
  by: string | null;
  at: Stamp | null;
  body: string;
  files: MailFile[];
  failed: boolean;
  /** Why it did not go, in words that do not quote the client's address. */
  error: string;
  open: boolean;
}

export type MailEntry = MailLetter | MailReply;

/** GET /api/v1/mail/threads/<id>/ */
export interface MailThreadResponse {
  ok: true;
  thread: {
    id: number;
    subject: string;
    count: number;
    client: string | null;
    can_reply: boolean;
    tasks: string[];
    blocked: boolean;
    entries: MailEntry[];
  };
}

/** POST /api/v1/mail/threads/<id>/seen/ */
export interface MailSeenResponse {
  ok: true;
  marked: number;
  unseen: number;
}

/** One row of the client list (`api_clients.clients`): the identity columns are there only for whoever may know the client. */
export interface ClientRow {
  code: string;
  tasks: number;
  requirements: number;
  name?: string;
  company?: string;
  phone?: string;
}

/** GET /api/v1/clients/?q= */
export interface ClientsResponse {
  ok: true;
  q: string;
  sees_identity: boolean;
  clients: ClientRow[];
}

/** A requirement as the client page shows it: the day it was written too. */
export interface ClientRequirement {
  id: number;
  kind: Labelled;
  author: string | null;
  text: string;
  at: Stamp | null;
}

/** GET /api/v1/clients/<code>/ */
export interface ClientResponse {
  ok: true;
  client: {
    code: string;
    /** Only for whoever may know the client. */
    name?: string;
    company?: string;
    phones?: string[];
    emails?: string[];
    admin_notes?: string;
  };
  sees_identity: boolean;
  may_edit: boolean;
  /** Counts and dates, for the admin. */
  activity: { total: number; active: number; delivered: number; last: Stamp | null } | null;
  requirements: ClientRequirement[];
  tasks: { code: string; title: string; origin: (Labelled & { icon: string }) | null; status: Labelled & { tone: string } }[];
  /** The classic form that writes the identity: for the admin alone. */
  edit_url?: string;
}

/** GET /api/v1/sales/line/ (and what a save answers with): a Sales person's own number, and the address the admin gave them. */
export interface SalesLine {
  ok: true;
  /** Each Sales person fills it in for themselves; anybody else may read what it asks for. */
  is_owner: boolean;
  values: { wa_phone_number_id: string; wa_display_number: string; mail_alias: string };
  /** The company mailbox the person's address has to deliver into. */
  company_mail: string;
}

/** One note of the AI on a translation (`api_ai._issue_json`): every free text is already read through the mask for this reader. */
export interface AiNote {
  /** The note's place in the check: what is sent back to say which notes the leader accepts (the list is shown most serious first). */
  id: number | null;
  severity: "high" | "medium" | "low";
  location: string;
  category: { ar: string; en: string } | null;
  /** What the client sent, and what the translator wrote: empty when the check did not quote them. */
  source: string;
  translation: string;
  /** Whether the check quoted the two texts (a check from before 28/09/2026 did not). */
  compared: boolean;
  text: { ar: string; en: string };
  /** What the source means, in Arabic. */
  meaning: string;
}

/** A copy of the translation with the accepted notes applied (`api_ai._revision_json`). `file` is there once it is done. */
export interface AiRevision {
  id: number;
  status: "running" | "done" | "error";
  /** The ids of the notes it applies. */
  accepted: number[];
  at: Stamp | null;
  error: string;
  file: { url: string; name: string; size: number } | null;
}

/** GET /api/v1/tasks/<code>/ai-notes/: the box at the top of a task page, for the admin and the task's own team leader. */
export interface TaskAiNotes {
  ok: true;
  task: { code: string; title: string };
  /** The switch is on, the key is there and no check is running. */
  can_recheck: boolean;
  /** There are notes to accept, the switch is on and no corrected copy is being made. */
  can_revise: boolean;
  /** The corrected copies of the latest check, newest first: the translator's own file is never one of them. */
  revisions: AiRevision[];
  /** `null` when no check has run yet. */
  check: {
    id: number;
    status: "running" | "clean" | "issues" | "error";
    count: number;
    at: Stamp | null;
    /** Nobody asked for it: it ran by itself when the translator handed the work over. */
    automatic: boolean;
    /** From before the side-by-side comparison: worth running again. */
    old: boolean;
    summary: string;
    error: string;
  } | null;
  issues: AiNote[];
}

/** GET /api/v1/groups/<id>/ai-notes/ and /api/v1/staff/<id>/ai-notes/: the panel beside the leader's chat, or `null`. */
export interface ChatAiNotes {
  ok: true;
  notes: { task: { code: string; title: string }; count: number; issues: AiNote[] } | null;
}

/** What a team leader may do on a task (`api_ops._lead_json`): every action is a classic endpoint that checks it again. */
export interface LeadTools {
  /** It waits for a translator: give it to one of `translators`. */
  can_assign: boolean;
  translators: { id: number; name: string; state: "free" | "busy" | "off"; rating: number }[];
  /** A translator has it: their date can be changed. */
  can_set_translator_deadline: boolean;
  /** It is under review: the review can be finished. */
  can_review: boolean;
  /** The client's date, to remind the leader of the review time they keep. */
  client_due: Stamp | null;
  /** The translator's request for more time, waiting for this person's yes or no. */
  extension: { id: number; length: string; reason: string; new_due: Stamp | null } | null;
}

/** One person of a team leader's team (`api_lead._person_json`) and whether they can take a job now. */
export interface LeadPerson {
  id: number;
  name: string;
  initials: string;
  languages: string;
  rating: number;
  state: PresenceState;
}

/** GET /api/v1/lead/: the leader's board. */
export interface LeadHome {
  ok: true;
  counters: { open: number; free: number; busy: number; offline: number };
  tasks: OpsTaskRow[];
  team: (LeadPerson & { seen: Stamp })[];
  closed: { code: string; status: Labelled & { tone: string } }[];
}

/** GET /api/v1/lead/translators/: who is free and who is busy, with the evidence. */
export interface LeadBoard {
  ok: true;
  counters: { free: number; busy: number; shift: number; offline: number; open: number };
  /** Tasks waiting for a translator. */
  waiting: { code: string; due: Stamp | null; due_state: OpsTaskRow["due_state"] }[];
  team: (LeadPerson & {
    awaiting_answer: boolean;
    load: number;
    load_percent: number;
    words: number;
    tasks: string[];
    next_due: Stamp | null;
    next_due_state: OpsTaskRow["due_state"];
  })[];
}

/** GET /api/v1/admin/overview/: the admin's board (`api_admin.overview`). */
export interface AdminOverview {
  ok: true;
  counters: { new: number; open: number; delivered: number; clients: number };
  /** Letters the rate rule hid from the operation: the sender's address is the admin's to read. */
  blocked: {
    id: number;
    code: string;
    channel: Channel;
    at: Stamp | null;
    body: string;
    sender: string;
    keyword: string;
    files: MailFile[];
  }[];
  /** Hand-offs waiting for an answer, with the seconds left when the board was read. */
  pending: { id: number; task: string; assignee: string; seconds_left: number }[];
  late: { code: string; translator: string | null; deadline: Stamp | null }[];
  recent: { code: string; title: string; origin: (Labelled & { icon: string }) | null; status: Labelled & { tone: string } }[];
}

export type AuditFilter = "" | "security" | "denied";

/** GET /api/v1/admin/audit/?only=: the log, newest first (`api_admin.audit`). */
export interface AdminAudit {
  ok: true;
  only: AuditFilter;
  /** Older rows exist: ask again with `before` set to the id of the last row shown. */
  more: boolean;
  rows: {
    id: number;
    at: Stamp | null;
    /** `null` is the system itself (a command, the worker). */
    actor: string | null;
    action: string;
    target: string;
    detail: string;
    ip: string;
    path: string;
  }[];
}

/** How a form field is drawn (`api_forms.kind_of`). */
export type FormFieldKind =
  | "checkbox" | "multi" | "select" | "password" | "number" | "email" | "time" | "date" | "datetime" | "textarea" | "text";

/** One field of a Django form, as the server describes it (`api_forms.describe`). A secret has `saved` and never a `value`. */
export interface FormField {
  name: string;
  label: string;
  kind: FormFieldKind;
  required: boolean;
  help: string;
  disabled: boolean;
  /** The value is an address, a number, a code: written left to right whatever the page's language. */
  ltr: boolean;
  value?: string | number | boolean | string[];
  /** A secret field: whether one is stored. The value is never sent. */
  saved?: boolean;
  /** An option, with its own words in both languages when the server wrote them (the day statuses, the roles). */
  choices?: { value: string; label: string; label_ar?: string; label_en?: string }[];
  /** Bilingual texts, when the classic page wrote its own beside the field (the settings). */
  label_ar?: string;
  label_en?: string;
  hint_ar?: string;
  hint_en?: string;
  maxlength?: number | string;
  min?: number | string;
  max?: number | string;
  step?: number | string;
  rows?: number | string;
  placeholder?: string;
}

/** What a form sends for a field: text, a box ticked or not, the ticked choices, or `null` (clear a stored secret). */
export type FormValue = string | boolean | string[] | null;

/** A form that did not validate: `{ field: [messages] }`, `__all__` for what belongs to no field. */
export type FormErrors = Record<string, string[]>;

/** A time of day in both languages (Cairo, twelve hours). */
export type AdminTime = Stamp;

export type StaffState = "disabled" | PresenceState;

/** GET /api/v1/admin/users/new/. */
export interface AdminUserNew {
  ok: true;
  form: FormField[];
}

/** GET /api/v1/admin/users/<id>/: the admin's half of a person's file (the other half is `HrEmployee`). */
export interface AdminUser {
  ok: true;
  user: { id: number; username: string; name: string; initials: string; avatar?: string | null; role: Labelled };
  form: FormField[];
  events: { delta: string; reason: string; at: Stamp | null }[];
}

/** The company's shifts to pick from and the days a person works: what the shift picker draws (`shiftpick.picker_json`). */
export interface ShiftPickerData {
  current: number | null;
  has_custom: boolean;
  templates: { id: number; label: string; start: AdminTime | null; end: AdminTime | null }[];
  days: { num: number; ar: string; en: string; checked: boolean }[];
}

/** GET /api/v1/admin/clients/: every client with the real details (`api_admin_clients.clients`). */
export interface AdminClients {
  ok: true;
  q: string;
  show: "" | "robots";
  /** How many match (the list shows at most 300). */
  shown: number;
  all_count: number;
  robots_count: number;
  clients: {
    id: number;
    code: string;
    name: string;
    company: string;
    phone: string;
    more_phones: number;
    email: string;
    more_emails: number;
    active: boolean;
  }[];
}

/** GET /api/v1/admin/clients/<code>/ and /new/: the identity form. */
export interface AdminClientForm {
  ok: true;
  code: string;
  form: FormField[];
}

export interface ClientPlanRow {
  id: number;
  code: string;
  name: string;
  contact: string;
  letters: number;
  files: number;
  replies: number;
  rooms: number;
  blocked: string;
}

/** POST /api/v1/admin/clients/delete-plan/: what deleting them would take, and which cannot go. Changes nothing. */
export interface ClientDeletePlan {
  ok: true;
  deletable: ClientPlanRow[];
  blocked: ClientPlanRow[];
}

/**
 * What deleting clients did, read off the headers of the backup the server answered with: how many went, how many stayed
 * because tasks stand on them, how many stored files went, and the name the backup was saved under.
 */
export interface ClientsDeleted {
  deleted: number;
  blocked: number;
  files: number;
  filename: string;
}

/** GET /api/v1/admin/simulate/: the choices of the simulator and the latest messages. */
export interface AdminSimulate {
  ok: true;
  channels: { value: string; label: string }[];
  recent: { id: number; code: string; body: string; blocked: boolean }[];
}

/** GET /api/v1/admin/reset/tasks/. */
export interface TaskResetCounts {
  tasks: number;
  open: number;
  assignments: number;
  deliveries: number;
  ai_checks: number;
  rooms: number;
}

/** GET /api/v1/admin/reset/mail/. */
export interface MailResetCounts {
  letters: number;
  sent: number;
  files: number;
  kept_letters: number;
  kept_sent: number;
}

/** GET /api/v1/admin/reset/staff/: what clearing the staff would take, and what is in the way (`line_blocked`). */
export interface StaffResetCounts {
  people: number;
  kept: number;
  shifts: number;
  work_days: number;
  leave: number;
  salary_records: number;
  payroll_lines: number;
  violations: number;
  rooms: number;
  line_letters: number;
  line_sent: number;
  line_blocked: number;
  /** Files a task still needs from an internal chat that would go with a person (a translator's deliverable). */
  task_files_blocked: number;
  /** People who have their own WhatsApp number or mail address: messages to them land on the company line once they are gone. */
  lines_released: number;
  tasks_touched: number;
}

/** GET /api/v1/admin/settings/: everything the settings page draws. A secret has `saved` and never a value. */
export interface AdminSettings {
  ok: true;
  fields: FormField[];
  sections: {
    key: string;
    icon: string;
    ar: string;
    en: string;
    note_ar?: string;
    note_en?: string;
    groups: { ar?: string; en?: string; note_ar?: string; note_en?: string; fields: string[] }[];
  }[];
  status: {
    whatsapp_saved: boolean;
    email_saved: boolean;
    google_configured: boolean;
    google_connected: boolean;
    google_sync_at: Stamp | null;
    google_sync_error: string;
    /** Whether the webhook can check Meta's signature (the App secret is saved) and the simple payload's shared secret. */
    webhook_signed: boolean;
    webhook_secret_set: boolean;
  };
  urls: { webhook: string; google_redirect: string; google_connect: string; is_local: boolean; is_https: boolean };
}

/** What a "save & test" button gets back (`whatsapp.check_connection`, `mailer.check_connection`). */
export interface ConnectionReport {
  ok: boolean;
  number?: string;
  name?: string;
  quality?: string;
  host?: string;
  user?: string;
  sent?: boolean;
  error_ar?: string;
  error_en?: string;
}

/** POST /api/v1/admin/settings/google/sync/. */
export interface GoogleSynced {
  ok: true;
  ran: boolean;
  error: string;
  added: string[];
  removed: string[];
  released: string[];
}

/** A payroll month's state (`PayrollPeriod.status`). */
export interface AccountsPeriod {
  id: number;
  label: string;
  status: { value: "draft" | "approved" | "locked"; ar: string; en: string };
}

/** One translator's line on the month's sheet (`api_accounts._line_row`). Money is text: a float would round it. */
export interface AccountsLineRow {
  id: number;
  user: { id: number; name: string; username: string; initials: string };
  base_salary: string;
  worked_days: number;
  working_days: number;
  leave_days: number;
  extra_leave_days: number;
  unexcused_days: number;
  total_words: number;
  below_alert: boolean;
  production_bonus: string;
  bonus_total: string;
  pending_bonus: string;
  deductions: string;
  net: string;
}

/** A deduction somebody proposed (`api_accounts._violation_json`). */
export interface AccountsViolation {
  id: number;
  user: string;
  date: string;
  kind: Labelled;
  task: string | null;
  reason: string;
  penalty_days: string;
  penalty_amount: string;
  escalated: boolean;
  status: "pending" | "approved" | "rejected" | string;
  decided_by: string | null;
}

/** GET /api/v1/accounts/overview/?period=: the month's sheet. */
export interface AccountsOverview {
  ok: true;
  year: number;
  month: number;
  periods: { year: number; month: number }[];
  period: AccountsPeriod | null;
  totals: { net: string; words: number; deductions: string; alerts: number } | null;
  lines: AccountsLineRow[];
  pending_violations: AccountsViolation[];
  missing_salary: { id: number; name: string; username: string; initials: string }[];
  unsettled_tasks: { code: string; translator: string | null }[];
  can: { line: boolean; task: boolean };
}

/** GET /api/v1/accounts/lines/<id>/: a payslip in full. */
export interface AccountsLine {
  ok: true;
  line: AccountsLineRow & {
    period: AccountsPeriod;
    label: string;
    day_value: string;
    target_words: number;
    under_target_days: number;
    overtime_bonus: string;
    overtime_minutes: number;
    discipline_bonus: string;
    discipline_bonus_earned: boolean;
    target_bonus: string;
    target_bonus_earned: boolean;
    bonuses_approved: boolean;
    gross: string;
    scheduled_days: number;
    office_days: number;
    remote_days: number;
    late_days: number;
    late_minutes: number;
    early_leave_minutes: number;
    short_minutes: number;
    work_minutes: number;
  };
  days: {
    date: string;
    status: Labelled & { tone: string };
    secondary: boolean;
    difficult: boolean;
    words: number;
    target: number;
    bonus: string;
  }[];
  deductions: { date: string; kind: Labelled; reason: string; days: string; amount: string; status: "applied" | "pending" }[];
  conf: { monthly_leave_allowance: number; discipline_bonus: string; target_bonus: string };
  can: { salary: boolean; release: boolean };
}

/** GET /api/v1/accounts/attendance/?period=&user=. */
export interface AccountsSheet {
  ok: true;
  year: number;
  month: number;
  periods: { year: number; month: number }[];
  people: { id: number; name: string }[];
  person: { id: number; name: string; username: string; initials: string } | null;
  days: {
    id: number;
    date: string;
    status: Labelled & { tone: string };
    check_in: Stamp | null;
    check_out: Stamp | null;
    late_minutes: number;
    words: number;
    under_floor: boolean;
    absence_reason: string;
    note: string;
  }[];
  words: number;
  leave_used: number;
  conf: { monthly_leave_allowance: number; monthly_target_words: number; daily_target_words: number };
  form: FormField[];
}

/** GET /api/v1/accounts/violations/. */
export interface AccountsViolations {
  ok: true;
  pending: AccountsViolation[];
  decided: AccountsViolation[];
  conf: Record<"quality_penalty_days" | "unexcused_penalty_days" | "low_output_penalty_days" | "extra_leave_penalty_days" | "target_miss_penalty", string>;
  form: FormField[];
}

/** GET /api/v1/accounts/salary/<id>/. */
export interface AccountsSalary {
  ok: true;
  person: { id: number; name: string; username: string; initials: string };
  records: { id: number; effective_from: string; amount: string; note: string; by: string | null }[];
  lines: { id: number; label: string; base_salary: string; words: number; net: string }[];
  can: { line: boolean; set: boolean };
  form: FormField[];
}

/** One band of the daily production bonus. */
export interface AccountsTier {
  id: number;
  min_words: number;
  max_words: number | null;
  bonus: string;
}

/** GET /api/v1/accounts/rules/: every number the payroll runs on. */
export interface AccountsRules {
  ok: true;
  fields: FormField[];
  sections: { key: string; icon: string; ar: string; en: string; note_ar?: string; note_en?: string; fields: string[] }[];
  tiers: { primary: AccountsTier[]; secondary: AccountsTier[] };
  tier_form: FormField[];
  check: { working_days: number; daily_target_words: number; monthly_target_words: number };
}

/** A call ringing for this person, as the heartbeat carries it (`services.incoming_call`). */
export interface CallInfo {
  id: number;
  video: boolean;
  from: string;
  initials: string;
  chat_url: string;
}

/** A call as either end reads it (`api._call_json`). */
export interface CallJson {
  id: number;
  status: "ringing" | "active" | "ended" | "declined" | "missed";
  video: boolean;
  caller: boolean;
  other: string;
  initials: string;
  /** When it was answered (ISO), or empty while it rings. */
  answered_at: string;
}

/** POST /api/calls/start/ and /api/calls/<id>/answer/: the call, and where the two browsers look for a path to each other. */
export interface CallStarted {
  ok: true;
  call: CallJson;
  ice?: RTCIceServer[];
}

/** GET /api/calls/<id>/signals/?after=: what the other end sent since, oldest first, and the call's state. */
export interface CallSignals {
  ok: boolean;
  call: CallJson;
  signals: { id: number; kind: string; payload: string }[];
}

// ---------------------------------------------------------------------------
// HR (api_hr.py)
// ---------------------------------------------------------------------------

export type DayStatusJson = Labelled & { tone: string };

/** One day of one person as the board and the report draw it. */
export interface HrBoardRow {
  id: number;
  user: { id: number; name: string };
  date: string;
  work_mode: Labelled | null;
  schedule: string;
  check_in: Stamp | null;
  check_out: Stamp | null;
  is_open: boolean;
  work_minutes: number;
  status: DayStatusJson;
  late_minutes: number;
  early_leave_minutes: number;
  short_minutes: number;
  overtime_minutes: number;
  off_site: boolean;
  extra_started_at: Stamp | null;
  checkout_missed: boolean;
  needs_review: boolean;
}

/** GET /api/v1/hr/attendance/?view=&date=&user=&role=&mode=&status=&day_mode=&shift=&flagged=. */
export interface HrBoard {
  ok: true;
  view: "day" | "week" | "month";
  date: string;
  first_day: string;
  last_day: string;
  flagged_count: number;
  totals: { present: number; late: number; off_site: number; open: number; minutes: number; overtime: number };
  /** More rows matched than the board draws (the first 600 are here). */
  truncated: boolean;
  rows: HrBoardRow[];
  missing: { user: { id: number; name: string }; schedule: string }[];
  options: {
    people: { id: number; name: string }[];
    roles: Labelled[];
    day_modes: Labelled[];
    statuses: DayStatusJson[];
    shifts: string[];
  };
}

/** GET /api/v1/hr/attendance/<id>/. */
export interface HrDay {
  ok: true;
  day: HrBoardRow & {
    review_reason: string;
    scheduled_start: Stamp | null;
    scheduled_end: Stamp | null;
    scheduled_minutes: number;
    grace_minutes: number;
  };
  events: {
    kind: Labelled;
    at: Stamp | null;
    within_geofence: boolean | null;
    distance_m: number | null;
    accuracy_m: number | null;
    office: string;
    device: string;
    ip: string;
  }[];
  edits: { actor: string | null; field: string; old: string; new: string; reason: string; at: Stamp | null }[];
  conf: { grace_minutes: number };
  form: FormField[];
}

/** GET /api/v1/hr/report/?period=&user=. */
export interface HrReport {
  ok: true;
  year: number;
  month: number;
  periods: { year: number; month: number }[];
  people: { id: number; name: string }[];
  person: { id: number; name: string } | null;
  summary:
    | (Record<
        | "scheduled_days"
        | "present_days"
        | "office_days"
        | "remote_days"
        | "leave_days"
        | "excused_days"
        | "absent_days"
        | "late_days"
        | "late_minutes"
        | "early_leave_minutes"
        | "short_minutes"
        | "work_minutes"
        | "break_minutes"
        | "overtime_minutes"
        | "needs_review",
        number
      > & {
        days: {
          date: string;
          status: DayStatusJson;
          work_mode: Labelled | null;
          check_in: Stamp | null;
          check_out: Stamp | null;
          break_minutes: number;
          work_minutes: number;
          late_minutes: number;
          short_minutes: number;
          overtime_minutes: number;
        }[];
      })
    | null;
}

/** One day of a person's standing roster (`api_hr._roster_json`); a row that is switched off counts for nothing. */
export interface HrRosterRow {
  id: number;
  weekday: { value: number; ar: string; en: string };
  template: string | null;
  start: Stamp | null;
  end: Stamp | null;
  crosses_midnight: boolean;
  minutes: number;
  work_mode: Labelled | null;
  is_active: boolean;
}

/** GET /api/v1/hr/schedules/?user=. */
export interface HrSchedules {
  ok: true;
  people: { id: number; name: string }[];
  person: { id: number; name: string; employment: Labelled; work_mode: Labelled | null; schedule_kind: string } | null;
  shifts: HrRosterRow[];
  overrides: { id: number; date: string; is_day_off: boolean; label: string; work_mode: Labelled | null; reason: string }[];
  preview: { date: string; working: boolean; label: string; start: Stamp | null; end: Stamp | null; mode: Labelled | null; source: string }[];
  templates: { id: number; label: string; is_active: boolean; start: Stamp | null; end: Stamp | null }[];
  shift_form: FormField[];
  override_form: FormField[];
  template_form: FormField[];
}

/** GET /api/v1/hr/shifts/?edit=. */
export interface HrShifts {
  ok: true;
  rows: {
    id: number;
    label: string;
    name: string;
    name_ar: string;
    is_active: boolean;
    start: Stamp | null;
    end: Stamp | null;
    crosses_midnight: boolean;
    hours: string;
    people: number;
    overrides: number;
    vacancies: number;
    in_use: boolean;
  }[];
  editing: number | null;
  form: FormField[];
}

/** GET /api/v1/hr/offices/?edit=. */
export interface HrOffices {
  ok: true;
  offices: { id: number; label: string; latitude: string; longitude: string; radius_meters: number; is_active: boolean }[];
  editing: number | null;
  form: FormField[];
  policy: "reject" | "flag";
}

export interface HrDevice {
  id: number;
  user: string;
  name: string;
  fingerprint: string;
  browser: string;
  status: "pending" | "approved" | "rejected";
  decided_by: string | null;
  first_seen: Stamp | null;
  last_seen: Stamp | null;
}

/** GET /api/v1/hr/devices/. */
export interface HrDevices {
  ok: true;
  pending: HrDevice[];
  decided: HrDevice[];
}

export interface HrClaim {
  id: number;
  user: string;
  date: string;
  hours: string;
  hourly_rate: string;
  amount: string;
  status: "pending" | "approved" | "rejected";
  decided_by: string | null;
}

/** GET /api/v1/hr/overtime/. */
export interface HrOvertime {
  ok: true;
  pending: HrClaim[];
  decided: HrClaim[];
}

// ---------------------------------------------------------------------------
// Leave (api_leave.py)
// ---------------------------------------------------------------------------

/** One request as the lists draw it. A permission has a window inside one day and no end date. */
export interface LeaveRequestJson {
  id: number;
  kind: Labelled;
  is_permission: boolean;
  start_date: string;
  end_date: string | null;
  days: number;
  minutes: number;
  start_time: Stamp | null;
  end_time: Stamp | null;
  status: DayStatusJson;
  is_open: boolean;
  reason: string;
  decision_note: string;
}

/** GET /api/v1/leave/. */
export interface MyLeave {
  ok: true;
  balance: { allowance: number; taken: number; pending: number; left: number; over: number };
  rows: LeaveRequestJson[];
  form: FormField[];
  needs_manager: boolean;
}

/** GET /api/v1/hr/leave/?user=&status=. */
export interface HrLeave {
  ok: true;
  waiting: (LeaveRequestJson & { user: { id: number; name: string }; manager: string | null; can_decide: boolean })[];
  rows: (LeaveRequestJson & { user: { id: number; name: string }; decided_by: string | null; applied: boolean })[];
  options: { people: { id: number; name: string }[]; statuses: DayStatusJson[] };
}

// ---------------------------------------------------------------------------
// HR: the people already hired (api_people.py)
// ---------------------------------------------------------------------------

/**
 * GET /api/v1/hr/employees/?department=&status=: one row a person. HR gets the people who work here; the admin gets everybody and
 * alone is told the sign-in name and the address a person receives mail for.
 */
export interface HrRegister {
  ok: true;
  rows: {
    id: number;
    code: string;
    name: string;
    initials: string;
    avatar?: string | null;
    role: Labelled;
    department: string | null;
    team_lead: string | null;
    employment: Labelled;
    joining_date: string | null;
    status: DayStatusJson;
    state: StaffState;
    seen: Stamp;
    /** `null` for the owner: they have no roster and no rating, which is not a nought. */
    shifts: number | null;
    rating: number | null;
    /** Stars that came off and wait for HR or the admin to apply or forgive them. */
    penalties_waiting: number;
    username?: string;
    mail_alias?: string;
  }[];
  options: { departments: { id: number; label: string }[]; statuses: DayStatusJson[] };
}

/** GET /api/v1/hr/employees/<id>/. */
export interface HrEmployee {
  ok: true;
  person: {
    id: number;
    name: string;
    /** The owner: their file is who they are and none of the company's rules (no attendance, roster, leave, probation or pay). */
    exempt: boolean;
    /** Why the company's rules are not this person's: the owner, or technical support. */
    exempt_why?: "owner" | "support" | "";
    initials: string;
    avatar?: string | null;
    role: Labelled;
    status: DayStatusJson;
    code: string;
    job_title: string;
    department: string | null;
    manager: string | null;
    languages: string;
    joining_date: string | null;
    employment: Labelled;
    work_mode: Labelled | null;
    probation_start: string | null;
    probation_end: string | null;
    phone: string;
    attendance_enabled: boolean;
  };
  summary: Record<"scheduled_days" | "present_days" | "office_days" | "remote_days" | "leave_days" | "absent_days" | "late_days" | "work_minutes" | "overtime_minutes", number> | null;
  shifts: HrRosterRow[];
  picker: ShiftPickerData | null;
  work_mode_card: {
    work_mode: Labelled | null;
    is_hybrid: boolean;
    offices: { label: string; radius_meters: number }[];
    pinned_days: number;
    policy_reject: boolean;
  } | null;
  probation: { stage: Labelled; due_date: string; outcome: DayStatusJson }[];
  leave: LeaveRequestJson[];
  plan: { current: { id: number; name: string; overrides: string[] } | null; options: { id: number; name: string }[] };
  application: { code: string; applied_on: string } | null;
  salary: { effective_from: string; amount: string }[];
  /** The stars that came off this person, newest first, and what HR or the admin did with each. */
  penalties: HrPenalty[];
  can: { edit: boolean; shift: boolean; plan: boolean; decide_penalties: boolean };
}

/** One star penalty (`api_people._penalty_json`): who, how many stars, why, and whether it stands. */
export interface HrPenalty {
  id: number;
  user: { id: number; name: string };
  /** Stars taken off, as text: `0.125`. */
  amount: string;
  reason: { ar: string; en: string };
  /** The task it was for, by code. */
  task: string | null;
  at: Stamp | null;
  decision: DayStatusJson & { value: "pending" | "confirmed" | "forgiven" };
  decided_by: string | null;
  decided_at: Stamp | null;
  note: string;
}

/** GET /api/v1/hr/penalties/: the penalties waiting for a decision (`?status=all` adds the decided). */
export interface HrPenalties {
  ok: true;
  rows: HrPenalty[];
  waiting: number;
}

/** GET /api/v1/hr/probation/?state=. */
export interface HrProbation {
  ok: true;
  state: "open" | "due" | "all";
  rows: {
    id: number;
    user: { id: number; name: string };
    stage: Labelled;
    due_date: string;
    overdue: boolean;
    outcome: DayStatusJson;
    score: number | null;
    decided: boolean;
    reviewer: string | null;
  }[];
  form: FormField[];
  on_probation: { id: number; name: string; department: string | null; probation_end: string | null; has_reviews: boolean }[];
  due_count: number;
}

/** One performance indicator: its score, its band, the figures that explain it, and why there is no score when there is none. */
export interface HrPart {
  score: number | null;
  band: DayStatusJson;
  reason?: { ar: string; en: string };
  words?: number;
  target?: number;
  reviewer_avg?: number | null;
  reviewed?: number;
  complaints?: number;
  violations?: number;
  late?: number;
  total?: number;
  present?: number;
  scheduled?: number;
  late_days?: number;
}

/** One translator on the performance board (`api_people._board_row`): `rank` is null for somebody who delivered nothing, `score` null when there is no target to measure against. */
export interface HrRankRow {
  rank: number | null;
  id: number;
  name: string;
  initials: string;
  avatar: string | null;
  words: number;
  /** The pay plan's target: only HR and the admin are told it (null for everybody else). */
  target: number | null;
  score: number | null;
  band: DayStatusJson;
  projects: number;
}

/** GET /api/v1/hr/performance/board/?period=: the best three apart, then everybody else (the ranked first). */
export interface HrPerformanceBoard {
  ok: true;
  year: number;
  month: number;
  periods: { year: number; month: number }[];
  podium: HrRankRow[];
  rest: HrRankRow[];
}

/** One month of a person's productivity record. */
export interface HrHistoryRow {
  year: number;
  month: number;
  words: number;
  target: number;
  score: number | null;
  band: DayStatusJson;
  projects: number;
}

/** GET /api/v1/hr/performance/?period=&user=. */
export interface HrPerformance {
  ok: true;
  year: number;
  month: number;
  periods: { year: number; month: number }[];
  people: { id: number; name: string }[];
  person: { id: number; name: string } | null;
  report: {
    weights: Record<"productivity" | "quality" | "deadline" | "attendance", number>;
    parts: Record<"productivity" | "quality" | "deadline" | "attendance", HrPart>;
    overall: number | null;
    band: DayStatusJson;
    projects: number;
    returned_projects: number;
    revision_rate: number | null;
  } | null;
  /** The person's last six months, newest first, the month asked for at the top. */
  history: HrHistoryRow[];
}

/** GET /api/v1/hr/complaints/?translator=. */
export interface HrComplaints {
  ok: true;
  rows: {
    id: number;
    date: string | null;
    summary: string;
    detail: string;
    translator: string | null;
    task: string | null;
    severity: DayStatusJson;
    resolved: boolean;
  }[];
  people: { id: number; name: string }[];
  form: FormField[];
}

export interface HrSalaryRequest {
  id: number;
  user: { id: number; name: string };
  current_amount: string;
  new_amount: string;
  delta: string;
  effective_from: string;
  reason: string;
  status: "pending" | "approved" | "rejected";
  requested_by: string | null;
  decided_by: string | null;
}

/** GET /api/v1/hr/salary-requests/?user=. */
export interface HrSalaryRequests {
  ok: true;
  people: { id: number; name: string }[];
  person: { id: number; name: string } | null;
  current: string | null;
  form: FormField[];
  pending: HrSalaryRequest[];
  decided: HrSalaryRequest[];
  can: { decide: boolean };
}

/** GET /api/v1/hr/salary-plans/?edit=. */
export interface HrSalaryPlans {
  ok: true;
  rows: {
    id: number;
    name: string;
    note: string;
    is_active: boolean;
    overrides: string[];
    extra_word_rate: string | null;
    fixed_allowance: string;
    members: number;
  }[];
  editing: number | null;
  form: FormField[];
  unassigned: number;
}

/** A candidate as the recruitment lists draw one: the code opens the file; the phone is HR's to see, nothing else of the person. */
export interface HrCandidateRow {
  code: string;
  name: string;
  vacancy: string | null;
  vacancy_code: string | null;
  phone: string;
  source: Labelled;
  status: DayStatusJson;
  applied_on: string;
  anonymous: boolean;
  shift: string;
}

/** GET /api/v1/hr/recruitment/. */
export interface HrRecruitment {
  ok: true;
  counts: Record<
    "open_vacancies" | "total_applicants" | "screening" | "pending_owner" | "interviews_today" | "pending_tests" | "hired" | "on_probation",
    number
  >;
  recent: HrCandidateRow[];
  today_interviews: { candidate: { code: string; name: string }; kind: Labelled; at: Stamp | null }[];
  waiting_owner: HrCandidateRow[];
  privacy_armed: boolean;
  bot_enabled: boolean;
  recruit_number: string;
  can: { approve: boolean };
}

/** GET /api/v1/hr/vacancies/?status=. */
export interface HrVacancies {
  ok: true;
  rows: { code: string; title: string; department: string | null; work_mode: Labelled; applicants: number; status: DayStatusJson }[];
  statuses: DayStatusJson[];
  form: FormField[];
}

/** GET /api/v1/hr/vacancies/<code>/. */
export interface HrVacancy {
  ok: true;
  vacancy: { code: string; title: string; status: DayStatusJson; applicants: number; deadline: string | null };
  form: FormField[];
  links: { id: number; order: number; required: boolean; question: { id: number; text: string; kind: Labelled; maps_to: Labelled | null } }[];
  pool: { id: number; department: string | null; text: string }[];
  candidates: HrCandidateRow[];
}

/** GET /api/v1/hr/questions/?department=&edit=. */
export interface HrQuestions {
  ok: true;
  rows: { id: number; text: string; options: string[]; department: string | null; kind: Labelled; maps_to: Labelled | null; is_active: boolean }[];
  editing: number | null;
  form: FormField[];
  departments: { id: number; label: string; questions: number }[];
  department_form: FormField[];
}

/** GET /api/v1/hr/recruitment/settings/. */
export interface HrRecruitSettings {
  ok: true;
  form: FormField[];
  /** `redact` is whether the signed-in person may change the words that hide the company from a candidate: the owner only. */
  can: { redact: boolean };
  privacy_armed: boolean;
  sample: string;
  line: { number: string; phone_number_id: boolean };
}

/** A stored file as a page links it: the protected address (`/files/...`) and the name to show. */
export interface HrFileLink {
  url: string;
  name: string;
}

/** GET /api/v1/hr/candidates/?status=&source=&vacancy=&q=. */
export interface HrCandidates {
  ok: true;
  rows: HrCandidateRow[];
  total: number;
  limit: number;
  counts: Record<string, number>;
  statuses: DayStatusJson[];
  sources: Labelled[];
  vacancies: { code: string; title: string }[];
}

/** An interview and its five marks (`marks` are out of ten, `null` is not marked). */
export interface HrInterviewJson {
  id: number;
  at: Stamp | null;
  kind: Labelled;
  interviewer: string | null;
  meeting_link: string;
  location: string;
  notes: string;
  evaluated: boolean;
  marks: Record<string, number | null>;
  total: number;
  max: number;
  comments: string;
}

/** A candidate's test as HR reads it. */
export interface HrExam {
  id: number;
  title: string;
  department: string | null;
  brief: string;
  language_pair: string;
  word_count: number;
  assignment: HrFileLink | null;
  submission: HrFileLink | null;
  submitted_at: Stamp | null;
  deadline: Stamp | null;
  overdue: boolean;
  reviewer: string | null;
  marked: boolean;
  marks: Record<string, number | null>;
  total: number;
  max: number;
  comments: string;
}

/** GET /api/v1/hr/candidates/<code>/. */
export interface HrCandidate {
  ok: true;
  candidate: HrCandidateRow & {
    email: string;
    department: string | null;
    experience_years: string;
    languages: string;
    skills: string;
    expected_salary: string;
    hr_notes: string;
    hr_recommendation: string;
    rejection_reason: string;
    cv: HrFileLink | null;
    identity: { revealed: boolean; at: Stamp | null; by: string | null };
    owner_decision: { at: Stamp | null; by: string | null } | null;
    hired_user: number | null;
  };
  form: FormField[];
  answers: { order: number; question: string; value: string; file: HrFileLink | null; at: Stamp | null }[];
  interviews: HrInterviewJson[];
  tests: HrExam[];
  next_statuses: DayStatusJson[];
  privacy_armed: boolean;
  /** Whether a message can go out: with no recruitment line set it would leave on the client's number. */
  line_ready: boolean;
  interview_form: FormField[];
  test_form: FormField[];
  can: { hire: boolean; mark: boolean };
}

/** GET /api/v1/hr/interviews/<id>/. */
export interface HrInterview {
  ok: true;
  interview: HrInterviewJson;
  candidate: { code: string; name: string };
  form: FormField[];
}

/** GET /api/v1/hr/candidates/<code>/hire/. */
export interface HrHire {
  ok: true;
  candidate: {
    code: string;
    name: string;
    phone: string;
    email: string;
    languages: string;
    department: string | null;
    shift: string;
    cv: HrFileLink | null;
    status: DayStatusJson;
    hired_user: number | null;
  };
  hireable: boolean;
  probation_days: number;
  form: FormField[];
}

/** A score as the owner reads it: out of fifty, or nothing when it was never given. */
export type HrScore = { total: number; max: number } | null;

/** GET /api/v1/hr/approvals/. */
export interface HrApprovals {
  ok: true;
  waiting: (HrCandidateRow & {
    interview_score: HrScore;
    test_score: HrScore;
    expected_salary: string;
    hr_recommendation: string;
    hr_notes: string;
    cv: HrFileLink | null;
    department: string | null;
  })[];
  decided: (HrCandidateRow & { decided_at: Stamp | null; can_hire: boolean })[];
}

/** One line of the reviewer's queue: a code, never a person. */
export interface ReviewerRow {
  id: number;
  candidate: string;
  title: string;
  department: string | null;
  overdue: boolean;
  submitted: boolean;
  submitted_at: Stamp | null;
  marked_at: Stamp | null;
  total: number | null;
  max: number;
}

/** GET /api/v1/reviewer/tests/. */
export interface ReviewerQueue {
  ok: true;
  pending: ReviewerRow[];
  done: ReviewerRow[];
}

/** A guide of the help assistant as a button: what it is called, and the page it starts on ("" when it is not one page). */
export interface HelpGuide {
  id: string;
  title: string;
  path: string;
}

/** GET /api/v1/help/. `orders` is true for the owner alone, and only while they have switched orders on. */
export interface HelpHome {
  ok: true;
  /** Who to write to for technical support (nobody when there is no such account, or when this person is the support). */
  support: { id: number; name: string } | null;
  ai: boolean;
  orders: boolean;
  starters: HelpGuide[];
}

/** An order the owner gave, prepared and waiting for their yes: what it will do is in words the server wrote. */
export interface HelpOrder {
  id: number;
  title: string;
  summary: string;
  danger: boolean;
  /** Seconds it still waits before it is withdrawn. */
  expires_in: number;
}

/** POST /api/v1/help/ask/. */
export interface HelpAnswer {
  ok: true;
  answer: string;
  answered: boolean;
  source: "ai" | "guide" | "none" | "action";
  open: HelpGuide | null;
  related: HelpGuide[];
  order: HelpOrder | null;
  /** False for an answer that names people (an order that did not hold): it is not sent back as part of the conversation. */
  keep: boolean;
}

/** POST /api/v1/help/orders/<id>/run/. `done` is false when the door refused: `message` says why. */
export interface HelpOrderResult {
  ok: true;
  done: boolean;
  status: string;
  message: string;
}

/** GET /api/v1/reviewer/tests/<id>/. `candidate.name` is the owner's to read: a reviewer is blind. */
export interface ReviewerTest {
  ok: true;
  blind: boolean;
  candidate: { code: string; name?: string };
  test: {
    id: number;
    title: string;
    brief: string;
    department: string | null;
    language_pair: string;
    word_count: number;
    deadline: Stamp | null;
    assignment: HrFileLink | null;
    submission: HrFileLink | null;
    submitted_at: Stamp | null;
    marked: boolean;
    total: number;
    max: number;
  };
  form: FormField[];
}
