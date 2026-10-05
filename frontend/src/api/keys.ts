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
  /** A Sales person's own line (their number and address). */
  salesLine: ["sales-line"] as const,
  /** The AI's notes on a task (the box on its page): it moves with the boards, and while a check runs it asks on a clock. */
  aiNotes: (code: string) => ["boards", "ai-notes", code] as const,
  /** The panel beside a leader's chat (`g12`, `u5`): under `chats`, so the doorbell that brings a message asks again. */
  chatAiNotes: (code: string) => ["chats", "ai-notes", code] as const,
  /** The team leader's board and their translators' board: with the boards, so a beat that says something moved asks again. */
  lead: ["boards", "lead", "home"] as const,
  leadBoard: ["boards", "lead", "board"] as const,
  /** The admin's overview: with the boards, so a beat that says something moved asks again. */
  adminOverview: ["boards", "admin", "overview"] as const,
  /** The audit log, by filter: outside the boards on purpose, a log that moves under the eye is harder to read (it has a refresh button). */
  adminAudit: (only: string) => ["admin-audit", only] as const,
  /** The staff table: with the boards (who is here moves). A person's file and the new-person form are outside them, so a doorbell never refills a form being typed in. */
  adminUser: (id: number) => ["admin-user", id] as const,
  adminUserNew: ["admin-user-new"] as const,
  /** The client records (by search and filter) and one client's identity form: outside the boards, read when opened. */
  adminClients: (q: string, show: string) => ["admin-clients", q, show] as const,
  adminClientsAll: ["admin-clients"] as const,
  adminClient: (code: string) => ["admin-client", code] as const,
  adminClientNew: ["admin-client-new"] as const,
  /** The simulator's latest messages and the clear-outs' counts: read when opened (a count that moves under the eye is a count to doubt). */
  adminSimulate: ["admin-simulate"] as const,
  adminResetCounts: (kind: "tasks" | "mail") => ["admin-reset", kind] as const,
  /** The settings page: outside the boards, read when opened and after a save (a form being typed in is not refilled). */
  adminSettings: ["admin-settings"] as const,
  /** The money screens: read when opened and after a write, never on a clock (a number that moves under the eye is a number to doubt). */
  accounts: ["accounts"] as const,
  accountsOverview: (period: string) => ["accounts", "overview", period] as const,
  accountsLine: (id: number) => ["accounts", "line", id] as const,
  accountsSheet: (period: string, user: string) => ["accounts", "sheet", period, user] as const,
  accountsViolations: ["accounts", "violations"] as const,
  accountsSalary: (id: number) => ["accounts", "salary", id] as const,
  accountsRules: ["accounts", "rules"] as const,
  hr: ["hr"] as const,
  hrBoard: (search: string) => ["hr", "board", search] as const,
  hrDay: (id: number) => ["hr", "day", id] as const,
  hrReport: (period: string, user: string) => ["hr", "report", period, user] as const,
  hrSchedules: (user: string) => ["hr", "schedules", user] as const,
  hrShifts: (edit: string) => ["hr", "shifts", edit] as const,
  hrOffices: (edit: string) => ["hr", "offices", edit] as const,
  hrDevices: ["hr", "devices"] as const,
  // Under "boards": who is here changes while the list is open, and the socket rings that bell for every board.
  hrRegisterAll: ["boards", "hr-register"] as const,
  hrRegister: (search: string) => ["boards", "hr-register", search] as const,
  hrEmployee: (id: number) => ["hr", "employee", id] as const,
  hrProbation: (state: string) => ["hr", "probation", state] as const,
  hrPerformance: (period: string, user: string) => ["hr", "performance", period, user] as const,
  hrPerformanceBoard: (period: string) => ["hr", "performance", "board", period] as const,
  hrComplaints: (translator: string) => ["hr", "complaints", translator] as const,
  hrSalaryRequests: (user: string) => ["hr", "salary-requests", user] as const,
  hrSalaryPlans: (edit: string) => ["hr", "salary-plans", edit] as const,
  hrLeave: (search: string) => ["hr", "leave", search] as const,
  hrRecruitment: ["hr", "recruitment"] as const,
  hrVacancies: (status: string) => ["hr", "vacancies", status] as const,
  hrVacancy: (code: string) => ["hr", "vacancy", code] as const,
  hrQuestions: (department: string, edit: string) => ["hr", "questions", department, edit] as const,
  hrRecruitSettings: ["hr", "recruit-settings"] as const,
  hrCandidates: (search: string) => ["hr", "candidates", search] as const,
  hrCandidate: (code: string) => ["hr", "candidate", code] as const,
  hrInterview: (id: number) => ["hr", "interview", id] as const,
  hrHire: (code: string) => ["hr", "hire", code] as const,
  hrApprovals: ["hr", "approvals"] as const,
  reviewer: ["reviewer"] as const,
  reviewerQueue: ["reviewer", "queue"] as const,
  reviewerTest: (id: number) => ["reviewer", "test", id] as const,
  leave: ["leave"] as const,
  hrOvertime: ["hr", "overtime"] as const,
  /** The hand-off waiting for an answer, as the heartbeat last told it (written by `useHeartbeat`, never fetched). */
  pending: ["pending-assignment"] as const,
  /** One hand-off read before it is taken. */
  assignment: (id: number) => ["boards", "assignment", id] as const,
  /** The tasks the menu's search found for what was typed (outside `boards`: an answer to a question, not a board). */
  navTasks: (query: string) => ["nav-tasks", query] as const,
};
