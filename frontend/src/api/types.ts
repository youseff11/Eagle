export type Lang = "ar" | "en";

/** A screen that has been ported to this app. The menu and the home page follow what the server lists. */
export type ScreenKey = "translator_home" | "operation" | "chats";
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
  /** The ported screens that are switched on for this person (`dashboard/newui.py`). */
  screens: ScreenKey[];
  unread_notifications: number;
  /** Messages waiting in any chat tab (`services.unread_chat_total`). */
  unread_chats: number;
  /** Mail conversations this person has not opened, and tasks nobody has been given yet (the operation's menu badges). */
  mail_unseen: number;
  tasks_new: number;
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
  pending: PendingAssignment | null;
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
  can: { assign_lead: boolean; take_over: boolean; deliver: boolean; cancel: boolean; add_member: boolean };
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
