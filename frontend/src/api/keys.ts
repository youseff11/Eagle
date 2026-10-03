/** Query keys. A doorbell from the server invalidates by these. */
export const qk = {
  me: ["me"] as const,
  notifications: ["notifications"] as const,
  /** The newest few, watched from every page for the toasts: under `notifications`, so a doorbell asks again. */
  latestNotifications: ["notifications", "latest"] as const,
  /** The prefix of everything the chats page shows: one doorbell refreshes the lists and the open thread. */
  chats: ["chats"] as const,
  chatList: (kind: string, query: string) => ["chats", "list", kind, query] as const,
  /** Every list, whatever the tab or the search: what a send refreshes. */
  chatLists: ["chats", "list"] as const,
  thread: (code: string) => ["chats", "thread", code] as const,
  /** Everybody a work group could be opened with: names and roles, asked for only when somebody opens the dialog. */
  people: ["people"] as const,
  /** Who is in a group (under `chats`, so a doorbell for the room asks again: somebody may have been added). */
  members: (room: number) => ["chats", "members", room] as const,
  /** The tasks a translator may hand files in to from one work group. */
  handinTasks: (room: number) => ["chats", "handin-tasks", room] as const,
  /** The tasks files sent in a conversation could be for. */
  fileTasks: (code: string) => ["chats", "file-tasks", code] as const,
  /** What this person wrote in a conversation and has not seen arrive: kept outside `chats`, so a doorbell never drops it. */
  outbox: (code: string) => ["outbox", code] as const,
  /** Everything a list page shows: one prefix, so a change on the boards refreshes them all. */
  boards: ["boards"] as const,
  translatorHome: ["boards", "translator-home"] as const,
  /** The payslip of one month (`""` is this month). */
  payroll: (period: string) => ["boards", "payroll", period] as const,
  /** One task as its translator reads it: it moves with the boards (a status, an answer to more time). */
  translatorTask: (code: string) => ["boards", "translator-task", code] as const,
  room: (id: number) => ["room", id] as const,
  /** The operation's task list (`""` is every task, `open`, or one status). */
  tasks: (status: string) => ["boards", "tasks", status] as const,
  /** What the new-task form starts from, by the address it was opened with (`""` is nothing). */
  taskStart: (search: string) => ["task-start", search] as const,
  /** One task as the operation reads it. */
  opsTask: (code: string) => ["boards", "ops-task", code] as const,
  /** Team leaders and who works under each. */
  team: ["boards", "team"] as const,
  /** The mailbox: the conversations (by the filter and the search), and one conversation. Under `boards`: a doorbell asks again. */
  mail: (state: string, query: string) => ["boards", "mail", "list", state, query] as const,
  mailLists: ["boards", "mail", "list"] as const,
  mailThread: (id: number) => ["boards", "mail", "thread", id] as const,
  /** The client codes (by the search), and one client: under `boards`, so a doorbell asks again. */
  clients: (query: string) => ["boards", "clients", "list", query] as const,
  client: (code: string) => ["boards", "clients", "one", code] as const,
  /** What the check-in screen asks right now, as the heartbeat last told it (written by `useHeartbeat`, never fetched). */
  gate: ["attendance-gate"] as const,
  /** The person's own attendance card: under `boards`, so a beat that says something moved asks again. */
  attendance: ["boards", "attendance"] as const,
  /** The hand-off waiting for an answer, as the heartbeat last told it (written by `useHeartbeat`, never fetched). */
  pending: ["pending-assignment"] as const,
  /** One hand-off read before it is taken. */
  assignment: (id: number) => ["boards", "assignment", id] as const,
};
