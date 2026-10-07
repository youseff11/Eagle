import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRealtimeStatus } from "../realtime/RealtimeProvider";
import { ApiError, api } from "./client";
import { aiNotesPath } from "../lib/chatCode";
import type { Recorded } from "../lib/recorder";
import { qk } from "./keys";
import type {
  AccountsLine,
  AccountsOverview,
  AccountsRules,
  AccountsSalary,
  AccountsSheet,
  AccountsViolations,
  HrApprovals,
  HrBoard,
  HrCandidate,
  HrCandidates,
  HrComplaints,
  HrDay,
  HrDevices,
  HrEmployee,
  HrPenalties,
  HrHire,
  HrInterview,
  HrLeave,
  HrOffices,
  HrOvertime,
  HrPerformance,
  HrPerformanceBoard,
  HrProbation,
  HrQuestions,
  HrRecruitSettings,
  HrRecruitment,
  HrRegister,
  HrReport,
  HrSalaryPlans,
  HrSalaryRequests,
  HrSchedules,
  HrShifts,
  HrVacancies,
  HrVacancy,
  MyLeave,
  AdminAudit,
  AdminSettings,
  AdminSimulate,
  AdminClientForm,
  AdminClients,
  AdminOverview,
  AdminUser,
  AdminUserNew,
  AiCheckAnswer,
  AnnounceResponse,
  AttendanceCard,
  AttendanceGate,
  AssignmentResponse,
  ChatKind,
  ChatAiNotes,
  ChatListResponse,
  ClientResponse,
  ClientsResponse,
  FileTasksResponse,
  ForwardResponse,
  GroupCreated,
  HandedIn,
  LeadBoard,
  LeadHome,
  MailListResponse,
  MailThreadResponse,
  MeResponse,
  MembersAdded,
  MembersResponse,
  MovedResponse,
  NotificationsResponse,
  OpsTaskResponse,
  PayrollResponse,
  PeopleResponse,
  PendingAssignment,
  ReactResponse,
  ReadResponse,
  ReviewerQueue,
  ReviewerTest,
  SalesLine,
  SendResponse,
  ThreadResponse,
  TaskAiNotes,
  TaskSearchResponse,
  TasksResponse,
  TaskStartResponse,
  TeamResponse,
  TranslatorHomeResponse,
  TranslatorTaskResponse,
} from "./types";

/** How often to ask when the socket is not there to say something changed. */
export const FALLBACK_POLL_MS = 15000;
const PAGE = 20;

function useFallbackInterval(): number | false {
  return useRealtimeStatus() === "open" ? false : FALLBACK_POLL_MS;
}

/**
 * The key and the fetch of the pages a person opens most. A hook asks with them, and so does `prefetch.ts`, which asks
 * before the click so the page opens on data instead of on a loading screen. They have to be the same, key and all:
 * a warm-up under another key warms nothing.
 */
export const notificationsOptions = () => ({
  queryKey: qk.notifications,
  initialPageParam: null as number | null,
  queryFn: ({ pageParam }: { pageParam: number | null }) =>
    api<NotificationsResponse>(`/api/v1/notifications/?limit=${PAGE}${pageParam ? `&before=${pageParam}` : ""}`),
  getNextPageParam: (last: NotificationsResponse) => last.next_before,
});
export const translatorHomeOptions = () => ({
  queryKey: qk.translatorHome,
  queryFn: () => api<TranslatorHomeResponse>("/api/v1/translator/home/"),
});
export const tasksOptions = (status: string) => ({
  queryKey: qk.tasks(status),
  queryFn: () => api<TasksResponse>(`/api/v1/tasks/${status ? `?status=${encodeURIComponent(status)}` : ""}`),
});
export const teamOptions = () => ({ queryKey: qk.team, queryFn: () => api<TeamResponse>("/api/v1/team/") });
export const leadHomeOptions = () => ({ queryKey: qk.lead, queryFn: () => api<LeadHome>("/api/v1/lead/") });
export const leadBoardOptions = () => ({
  queryKey: qk.leadBoard,
  queryFn: () => api<LeadBoard>("/api/v1/lead/translators/"),
});
export const adminOverviewOptions = () => ({
  queryKey: qk.adminOverview,
  queryFn: () => api<AdminOverview>("/api/v1/admin/overview/"),
});
/** The register: `search` is `department=&status=`. The same key and fetch for the hook and for the warm-up before the click. */
export const hrRegisterOptions = (search: string) => ({
  queryKey: qk.hrRegister(search),
  queryFn: () => api<HrRegister>(`/api/v1/hr/employees/${search ? `?${search}` : ""}`),
});
export const mailThreadsOptions = (state: string, query: string) => {
  const params = new URLSearchParams();
  if (state) params.set("state", state);
  if (query) params.set("q", query);
  const text = params.toString();
  return {
    queryKey: qk.mail(state, query),
    queryFn: () => api<MailListResponse>(`/api/v1/mail/threads/${text ? `?${text}` : ""}`),
  };
};
export const chatListOptions = (kind: ChatKind, query: string) => ({
  queryKey: qk.chatList(kind, query),
  queryFn: () =>
    api<ChatListResponse>(`/api/v1/chats/?type=${kind}${query ? `&q=${encodeURIComponent(query)}` : ""}`),
});

export function useMe() {
  const refetchInterval = useFallbackInterval();
  return useQuery({
    queryKey: qk.me,
    queryFn: () => api<MeResponse>("/api/v1/me/"),
    refetchInterval,
  });
}

export function useNotifications() {
  const refetchInterval = useFallbackInterval();
  return useInfiniteQuery({ ...notificationsOptions(), refetchInterval });
}

/** How many of the newest notifications the toasts look at: more than can arrive between two looks. */
const LATEST = 10;

/** The newest notifications, for the toasts. Not the list page's own query: it is one page, and always there. */
export function useLatestNotifications() {
  const refetchInterval = useFallbackInterval();
  return useQuery({
    queryKey: qk.latestNotifications,
    queryFn: () => api<NotificationsResponse>(`/api/v1/notifications/?limit=${LATEST}`),
    refetchInterval,
  });
}

/** Mark some notifications read, or all of them when no ids are given. */
export function useMarkRead() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (ids?: number[]) =>
      api<ReadResponse>("/api/v1/notifications/read/", { json: ids ? { ids } : { all: true } }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: qk.notifications });
      void client.invalidateQueries({ queryKey: qk.me });
    },
  });
}

/** The translator's own desk. Refreshed when the boards move (see `useHeartbeat`, `handleEvent`). */
export function useTranslatorHome(enabled = true) {
  const refetchInterval = useFallbackInterval();
  return useQuery({
    ...translatorHomeOptions(),
    refetchInterval,
    // Everybody else is refused, and every refusal is written to the audit log: a page left
    // open would write a row at every refresh.
    enabled,
  });
}

/** The operation's task list: `""` is the live ones (every task but the delivered and the cancelled), `open` the ones with people on them, or one status. */
export function useTasks(status: string, enabled = true) {
  const refetchInterval = useFallbackInterval();
  return useQuery({
    ...tasksOptions(status),
    refetchInterval,
    // Everybody else is refused, and every refusal is written to the audit log.
    enabled,
  });
}

/**
 * What the new-task form starts from: the address's own query (`?messages=1,2&files=3&from=TSK-00001`), passed on as it
 * is - the server looks every id up again against what this person may read. Asked for once: a form being typed in
 * must not be re-filled by a doorbell.
 */
export function useTaskStart(search: string, enabled = true) {
  return useQuery({
    queryKey: qk.taskStart(search),
    queryFn: () => api<TaskStartResponse>(`/api/v1/task-form/${search}`),
    enabled,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}

/** One task as the operation reads it. Moves with the boards (a leader took it, a file arrived). */
export function useOpsTask(code: string, enabled = true) {
  const refetchInterval = useFallbackInterval();
  return useQuery({
    queryKey: qk.opsTask(code),
    queryFn: () => api<OpsTaskResponse>(`/api/v1/tasks/${encodeURIComponent(code)}/`),
    refetchInterval,
    enabled,
  });
}

/** The team leaders and who works under each. Moves with the boards. */
export function useTeam(enabled = true) {
  const refetchInterval = useFallbackInterval();
  return useQuery({
    ...teamOptions(),
    refetchInterval,
    enabled,
  });
}

/** How many people a support announcement reaches, and the latest ones. Only for technical support (and the owner). */
export function useAnnounce(enabled = true) {
  return useQuery({
    queryKey: qk.announce,
    queryFn: () => api<AnnounceResponse>("/api/v1/announce/"),
    enabled,
  });
}

/** Tell everybody: a notification to each active employee. A refusal says why in its `code` (`repeat`, `empty`, `too_long`). */
export function useSendAnnouncement() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (values: { title: string; body: string; level: "info" | "warning"; sound: boolean }) =>
      api<{ ok: true; reached: number }>("/api/v1/announce/", { json: values }),
    onSuccess: () => void client.invalidateQueries({ queryKey: qk.announce }),
  });
}

/** How often the box asks again while a check is running: the page "updates itself when it is done". */
export const AI_RUNNING_POLL_MS = 5000;

/** The AI's notes on a task: for the admin and the task's own team leader (anybody else is refused, and logged). */
export function useTaskAiNotes(code: string, enabled = true) {
  const refetchInterval = useFallbackInterval();
  return useQuery({
    queryKey: qk.aiNotes(code),
    queryFn: () => api<TaskAiNotes>(`/api/v1/tasks/${encodeURIComponent(code)}/ai-notes/`),
    // A check that is running ends by itself, and nothing rings for it: ask on a clock until it has.
    refetchInterval: (query) => (query.state.data?.check?.status === "running" ? AI_RUNNING_POLL_MS : refetchInterval),
    retry: false,
    enabled,
  });
}

/** The panel beside a team leader's chat with one translator (`code` is `g<room>` or `u<person>`). */
export function useChatAiNotes(code: string, enabled = true) {
  const refetchInterval = useFallbackInterval();
  const path = aiNotesPath(code);
  return useQuery({
    queryKey: qk.chatAiNotes(code),
    queryFn: () => api<ChatAiNotes>(path ?? ""),
    refetchInterval,
    retry: false,
    // A client's conversation has no panel, and an address that is not a room is not asked about.
    enabled: enabled && path !== null,
  });
}

/** The team leader's own board: their tasks, their team, what was closed lately. */
export function useLeadHome(enabled = true) {
  const refetchInterval = useFallbackInterval();
  return useQuery({ ...leadHomeOptions(), refetchInterval, enabled });
}

/** Who of the leader's team is free and who is busy, and what the busy ones are doing. */
export function useLeadBoard(enabled = true) {
  const refetchInterval = useFallbackInterval();
  return useQuery({ ...leadBoardOptions(), refetchInterval, enabled });
}

/** The admin's overview: the numbers, the letters held back, hand-offs waiting, late tasks, the newest tasks. */
export function useAdminOverview(enabled = true) {
  const refetchInterval = useFallbackInterval();
  return useQuery({
    ...adminOverviewOptions(),
    refetchInterval,
    // Everybody else is refused, and every refusal is written to the audit log.
    enabled,
  });
}

/** The audit log (`only` is `security`, `denied` or empty for all). Read when opened, not watched; a tab never shows another tab's rows while it loads. */
export function useAdminAudit(only: string, enabled = true) {
  return useQuery({
    queryKey: qk.adminAudit(only),
    queryFn: () => api<AdminAudit>(`/api/v1/admin/audit/${only ? `?only=${encodeURIComponent(only)}` : ""}`),
    enabled,
  });
}

/**
 * The client records. Asked for when the page opens and when a search is sent - never on a clock, a doorbell or a return
 * to the window - because each answer is written to the audit log (it shows every client's identity).
 */
export function useAdminClients(q: string, show: string, enabled = true) {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (show) params.set("show", show);
  const text = params.toString();
  return useQuery({
    queryKey: qk.adminClients(q, show),
    queryFn: () => api<AdminClients>(`/api/v1/admin/clients/${text ? `?${text}` : ""}`),
    refetchOnWindowFocus: false,
    placeholderData: (previous) => previous,
    enabled,
  });
}

/** One client's identity form (`code` empty is the form for a new client). */
export function useAdminClient(code: string, enabled = true) {
  return useQuery({
    queryKey: code ? qk.adminClient(code) : qk.adminClientNew,
    queryFn: () => api<AdminClientForm>(code ? `/api/v1/admin/clients/${encodeURIComponent(code)}/` : "/api/v1/admin/clients/new/"),
    refetchOnWindowFocus: false,
    enabled,
  });
}

/** The simulator: its choices and the latest messages. */
export function useAdminSimulate(enabled = true) {
  return useQuery({
    queryKey: qk.adminSimulate,
    queryFn: () => api<AdminSimulate>("/api/v1/admin/simulate/"),
    refetchOnWindowFocus: false,
    enabled,
  });
}

/** What a clear-out would take (`kind` is `tasks`, `mail` or `staff`). Counted when the page opens, not on a clock. */
export function useResetCounts<T>(kind: "tasks" | "mail" | "staff", enabled = true) {
  return useQuery({
    queryKey: qk.adminResetCounts(kind),
    queryFn: () => api<{ ok: true; counts: T }>(`/api/v1/admin/reset/${kind}/`),
    refetchOnWindowFocus: false,
    gcTime: 0,
    enabled,
  });
}

/** The month's payroll sheet (`period` is `2026-09`, or empty for this month). */
export function useAccountsOverview(period: string, enabled = true) {
  return useQuery({
    queryKey: qk.accountsOverview(period),
    queryFn: () => api<AccountsOverview>(`/api/v1/accounts/overview/${period ? `?period=${encodeURIComponent(period)}` : ""}`),
    refetchOnWindowFocus: false,
    enabled,
  });
}

/** A payslip in full: the admin's, or a translator's own. */
export function useAccountsLine(id: number, enabled = true) {
  return useQuery({
    queryKey: qk.accountsLine(id),
    queryFn: () => api<AccountsLine>(`/api/v1/accounts/lines/${id}/`),
    refetchOnWindowFocus: false,
    enabled: enabled && Number.isInteger(id) && id > 0,
  });
}

/** One translator's month, day by day (`user` is an id, or empty for the first translator). */
export function useAccountsSheet(period: string, user: string, enabled = true) {
  const params = new URLSearchParams();
  if (period) params.set("period", period);
  if (user) params.set("user", user);
  const text = params.toString();
  return useQuery({
    queryKey: qk.accountsSheet(period, user),
    queryFn: () => api<AccountsSheet>(`/api/v1/accounts/attendance/${text ? `?${text}` : ""}`),
    refetchOnWindowFocus: false,
    placeholderData: (previous) => previous,
    enabled,
  });
}

export function useAccountsViolations(enabled = true) {
  return useQuery({
    queryKey: qk.accountsViolations,
    queryFn: () => api<AccountsViolations>("/api/v1/accounts/violations/"),
    refetchOnWindowFocus: false,
    enabled,
  });
}

export function useAccountsSalary(id: number, enabled = true) {
  return useQuery({
    queryKey: qk.accountsSalary(id),
    queryFn: () => api<AccountsSalary>(`/api/v1/accounts/salary/${id}/`),
    refetchOnWindowFocus: false,
    enabled: enabled && Number.isInteger(id) && id > 0,
  });
}

export function useAccountsRules(enabled = true) {
  return useQuery({
    queryKey: qk.accountsRules,
    queryFn: () => api<AccountsRules>("/api/v1/accounts/rules/"),
    refetchOnWindowFocus: false,
    enabled,
  });
}

/** HR's attendance board; `search` is the filters as a query string (`view=week&date=2026-09-16`). */
export function useHrBoard(search: string, enabled = true) {
  return useQuery({
    queryKey: qk.hrBoard(search),
    queryFn: () => api<HrBoard>(`/api/v1/hr/attendance/${search ? `?${search}` : ""}`),
    refetchOnWindowFocus: false,
    placeholderData: (previous) => previous,
    enabled,
  });
}

/** One day of one person: its punches, its trail, and the form that corrects it. */
export function useHrDay(id: number, enabled = true) {
  return useQuery({
    queryKey: qk.hrDay(id),
    queryFn: () => api<HrDay>(`/api/v1/hr/attendance/${id}/`),
    refetchOnWindowFocus: false,
    enabled: enabled && Number.isInteger(id) && id > 0,
  });
}

/** One person's month (`period` is `2026-9`, `user` an id; both may be empty). */
export function useHrReport(period: string, user: string, enabled = true) {
  const params = new URLSearchParams();
  if (period) params.set("period", period);
  if (user) params.set("user", user);
  const text = params.toString();
  return useQuery({
    queryKey: qk.hrReport(period, user),
    queryFn: () => api<HrReport>(`/api/v1/hr/report/${text ? `?${text}` : ""}`),
    refetchOnWindowFocus: false,
    placeholderData: (previous) => previous,
    enabled,
  });
}

/** A person's roster, the days that override it, the next fortnight, and the forms (`user` is an id; empty is the first person). */
export function useHrSchedules(user: string, enabled = true) {
  return useQuery({
    queryKey: qk.hrSchedules(user),
    queryFn: () => api<HrSchedules>(`/api/v1/hr/schedules/${user ? `?user=${encodeURIComponent(user)}` : ""}`),
    refetchOnWindowFocus: false,
    placeholderData: (previous) => previous,
    enabled,
  });
}

/** The company's shifts and the form (`edit` is the id of the one being changed, or empty). */
export function useHrShifts(edit: string, enabled = true) {
  return useQuery({
    queryKey: qk.hrShifts(edit),
    queryFn: () => api<HrShifts>(`/api/v1/hr/shifts/${edit ? `?edit=${encodeURIComponent(edit)}` : ""}`),
    refetchOnWindowFocus: false,
    enabled,
  });
}

export function useHrOffices(edit: string, enabled = true) {
  return useQuery({
    queryKey: qk.hrOffices(edit),
    queryFn: () => api<HrOffices>(`/api/v1/hr/offices/${edit ? `?edit=${encodeURIComponent(edit)}` : ""}`),
    refetchOnWindowFocus: false,
    enabled,
  });
}

export function useHrDevices(enabled = true) {
  return useQuery({
    queryKey: qk.hrDevices,
    queryFn: () => api<HrDevices>("/api/v1/hr/devices/"),
    refetchOnWindowFocus: false,
    enabled,
  });
}

export function useHrOvertime(enabled = true) {
  return useQuery({
    queryKey: qk.hrOvertime,
    queryFn: () => api<HrOvertime>("/api/v1/hr/overtime/"),
    refetchOnWindowFocus: false,
    enabled,
  });
}

/** Everybody on the staff, and whether they are here (`search` is `department=&status=`): the socket's bell asks again. */
export function useHrRegister(search: string, enabled = true) {
  const refetchInterval = useFallbackInterval();
  return useQuery({
    ...hrRegisterOptions(search),
    refetchInterval,
    refetchOnWindowFocus: false,
    placeholderData: (previous) => previous,
    enabled,
  });
}

/** One person's file: the key and the fetch, for the page and for the warm-up before the click (`intent.ts`). */
export const hrEmployeeOptions = (id: number) => ({
  queryKey: qk.hrEmployee(id),
  queryFn: () => api<HrEmployee>(`/api/v1/hr/employees/${id}/`),
});

/** One person's file. */
export function useHrEmployee(id: number, enabled = true) {
  return useQuery({
    ...hrEmployeeOptions(id),
    refetchOnWindowFocus: false,
    enabled: enabled && Number.isInteger(id) && id > 0,
  });
}

/** The star penalties waiting for HR or the admin to apply or forgive them. */
export function useHrPenalties(enabled = true) {
  const refetchInterval = useFallbackInterval();
  return useQuery({
    queryKey: qk.hrPenalties,
    queryFn: () => api<HrPenalties>("/api/v1/hr/penalties/"),
    refetchInterval,
    refetchOnWindowFocus: false,
    enabled,
  });
}

/** The probation reviews (`state` is `due`, `all`, or empty for the open ones). */
export function useHrProbation(state: string, enabled = true) {
  return useQuery({
    queryKey: qk.hrProbation(state),
    queryFn: () => api<HrProbation>(`/api/v1/hr/probation/${state ? `?state=${encodeURIComponent(state)}` : ""}`),
    refetchOnWindowFocus: false,
    placeholderData: (previous) => previous,
    enabled,
  });
}

/** One translator's month (`period` is `2026-9`, `user` an id; both may be empty). */
export function useHrPerformance(period: string, user: string, enabled = true) {
  const params = new URLSearchParams();
  if (period) params.set("period", period);
  if (user) params.set("user", user);
  const text = params.toString();
  return useQuery({
    queryKey: qk.hrPerformance(period, user),
    queryFn: () => api<HrPerformance>(`/api/v1/hr/performance/${text ? `?${text}` : ""}`),
    refetchOnWindowFocus: false,
    placeholderData: (previous) => previous,
    enabled,
  });
}

/** Who delivered the most in a month (`period` is `2026-9`, or empty for this month). */
export function useHrPerformanceBoard(period: string, enabled = true) {
  return useQuery({
    queryKey: qk.hrPerformanceBoard(period),
    queryFn: () => api<HrPerformanceBoard>(`/api/v1/hr/performance/board/${period ? `?period=${encodeURIComponent(period)}` : ""}`),
    refetchOnWindowFocus: false,
    placeholderData: (previous) => previous,
    enabled,
  });
}

export function useHrComplaints(translator: string, enabled = true) {
  return useQuery({
    queryKey: qk.hrComplaints(translator),
    queryFn: () => api<HrComplaints>(`/api/v1/hr/complaints/${translator ? `?translator=${encodeURIComponent(translator)}` : ""}`),
    refetchOnWindowFocus: false,
    placeholderData: (previous) => previous,
    enabled,
  });
}

export function useHrSalaryRequests(user: string, enabled = true) {
  return useQuery({
    queryKey: qk.hrSalaryRequests(user),
    queryFn: () => api<HrSalaryRequests>(`/api/v1/hr/salary-requests/${user ? `?user=${encodeURIComponent(user)}` : ""}`),
    refetchOnWindowFocus: false,
    placeholderData: (previous) => previous,
    enabled,
  });
}

export function useHrSalaryPlans(edit: string, enabled = true) {
  return useQuery({
    queryKey: qk.hrSalaryPlans(edit),
    queryFn: () => api<HrSalaryPlans>(`/api/v1/hr/salary-plans/${edit ? `?edit=${encodeURIComponent(edit)}` : ""}`),
    refetchOnWindowFocus: false,
    enabled,
  });
}

/** The recruitment board: the counts, the latest applicants, today's interviews, who waits for the owner. */
export function useHrRecruitment(enabled = true) {
  return useQuery({
    queryKey: qk.hrRecruitment,
    queryFn: () => api<HrRecruitment>("/api/v1/hr/recruitment/"),
    refetchOnWindowFocus: false,
    enabled,
  });
}

export function useHrVacancies(status: string, enabled = true) {
  return useQuery({
    queryKey: qk.hrVacancies(status),
    queryFn: () => api<HrVacancies>(`/api/v1/hr/vacancies/${status ? `?status=${encodeURIComponent(status)}` : ""}`),
    refetchOnWindowFocus: false,
    placeholderData: (previous) => previous,
    enabled,
  });
}

/** One vacancy by its code; a code that is not one comes back 404. */
export function useHrVacancy(code: string, enabled = true) {
  return useQuery({
    queryKey: qk.hrVacancy(code),
    queryFn: () => api<HrVacancy>(`/api/v1/hr/vacancies/${encodeURIComponent(code)}/`),
    refetchOnWindowFocus: false,
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
    enabled: enabled && code !== "",
  });
}

/** The question bank, narrowed by department, with the form for a new question (or the one `edit` names). */
export function useHrQuestions(department: string, edit: string, enabled = true) {
  const params = new URLSearchParams();
  if (department) params.set("department", department);
  if (edit) params.set("edit", edit);
  const text = params.toString();
  return useQuery({
    queryKey: qk.hrQuestions(department, edit),
    queryFn: () => api<HrQuestions>(`/api/v1/hr/questions/${text ? `?${text}` : ""}`),
    refetchOnWindowFocus: false,
    placeholderData: (previous) => previous,
    enabled,
  });
}

export function useHrRecruitSettings(enabled = true) {
  return useQuery({
    queryKey: qk.hrRecruitSettings,
    queryFn: () => api<HrRecruitSettings>("/api/v1/hr/recruitment/settings/"),
    refetchOnWindowFocus: false,
    enabled,
  });
}

/** Everyone who applied (`search` is the filters as a query string: status, source, vacancy, q). */
export function useHrCandidates(search: string, enabled = true) {
  return useQuery({
    queryKey: qk.hrCandidates(search),
    queryFn: () => api<HrCandidates>(`/api/v1/hr/candidates/${search ? `?${search}` : ""}`),
    refetchOnWindowFocus: false,
    placeholderData: (previous) => previous,
    enabled,
  });
}

/** One candidate's whole file; a code that is not one comes back 404. */
export function useHrCandidate(code: string, enabled = true) {
  return useQuery({
    queryKey: qk.hrCandidate(code),
    queryFn: () => api<HrCandidate>(`/api/v1/hr/candidates/${encodeURIComponent(code)}/`),
    refetchOnWindowFocus: false,
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
    enabled: enabled && code !== "",
  });
}

export function useHrInterview(id: number, enabled = true) {
  return useQuery({
    queryKey: qk.hrInterview(id),
    queryFn: () => api<HrInterview>(`/api/v1/hr/interviews/${id}/`),
    refetchOnWindowFocus: false,
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
    enabled: enabled && Number.isInteger(id) && id > 0,
  });
}

/** What carries over from the application, and the contract form (none unless the candidate is approved). */
export function useHrHire(code: string, enabled = true) {
  return useQuery({
    queryKey: qk.hrHire(code),
    queryFn: () => api<HrHire>(`/api/v1/hr/candidates/${encodeURIComponent(code)}/hire/`),
    refetchOnWindowFocus: false,
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
    enabled: enabled && code !== "",
  });
}

/** The owner's queue of hiring decisions and the last ones made. */
export function useHrApprovals(enabled = true) {
  return useQuery({
    queryKey: qk.hrApprovals,
    queryFn: () => api<HrApprovals>("/api/v1/hr/approvals/"),
    refetchOnWindowFocus: false,
    enabled,
  });
}

/** The reviewer's queue of candidate tests: codes and the work, never a person. */
export function useReviewerQueue(enabled = true) {
  return useQuery({
    queryKey: qk.reviewerQueue,
    queryFn: () => api<ReviewerQueue>("/api/v1/reviewer/tests/"),
    refetchOnWindowFocus: false,
    enabled,
  });
}

export function useReviewerTest(id: number, enabled = true) {
  return useQuery({
    queryKey: qk.reviewerTest(id),
    queryFn: () => api<ReviewerTest>(`/api/v1/reviewer/tests/${id}/`),
    refetchOnWindowFocus: false,
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
    enabled: enabled && Number.isInteger(id) && id > 0,
  });
}

/** The person's own leave: the balance, the requests, and the form. */
export function useMyLeave(enabled = true) {
  return useQuery({
    queryKey: qk.leave,
    queryFn: () => api<MyLeave>("/api/v1/leave/"),
    refetchOnWindowFocus: false,
    enabled,
  });
}

/** HR's leave queue and record (`search` is the filters as a query string). */
export function useHrLeave(search: string, enabled = true) {
  return useQuery({
    queryKey: qk.hrLeave(search),
    queryFn: () => api<HrLeave>(`/api/v1/hr/leave/${search ? `?${search}` : ""}`),
    refetchOnWindowFocus: false,
    placeholderData: (previous) => previous,
    enabled,
  });
}

/** The settings page: the form's fields (a secret is only `saved`), the sections, the rollout rows and the Google state. */
export function useAdminSettings(enabled = true) {
  return useQuery({
    queryKey: qk.adminSettings,
    queryFn: () => api<AdminSettings>("/api/v1/admin/settings/"),
    refetchOnWindowFocus: false,
    enabled,
  });
}

/** The admin's half of a person's file: the key and the fetch (see `hrEmployeeOptions`). */
export const adminUserOptions = (id: number) => ({
  queryKey: qk.adminUser(id),
  queryFn: () => api<AdminUser>(`/api/v1/admin/users/${id}/`),
});

/** The admin's half of a person's file. Asked for when it opens and after a save, never on a clock or a doorbell: the form is being typed in. */
export function useAdminUser(id: number, enabled = true) {
  return useQuery({
    ...adminUserOptions(id),
    refetchOnWindowFocus: false,
    enabled: enabled && Number.isInteger(id) && id > 0,
  });
}

/** The fields of the form for a new person. */
export function useAdminUserNew(enabled = true) {
  return useQuery({
    queryKey: qk.adminUserNew,
    queryFn: () => api<AdminUserNew>("/api/v1/admin/users/new/"),
    refetchOnWindowFocus: false,
    enabled,
  });
}

/** A Sales person's own number and address (the admin may read the page, and sees it empty). */
export function useSalesLine(enabled = true) {
  return useQuery({
    queryKey: qk.salesLine,
    queryFn: () => api<SalesLine>("/api/v1/sales/line/"),
    enabled,
  });
}

/** The client codes, `query` narrowing them (the server leaves the identity fields out of what it matches for most people). */
export function useClients(query: string, enabled = true) {
  const refetchInterval = useFallbackInterval();
  return useQuery({
    queryKey: qk.clients(query),
    queryFn: () => api<ClientsResponse>(`/api/v1/clients/${query ? `?q=${encodeURIComponent(query)}` : ""}`),
    refetchInterval,
    placeholderData: (previous) => previous,
    enabled,
  });
}

/** One client. A code that is not there is a 404 the page says so about; it is not asked again. */
export function useClient(code: string, enabled = true) {
  const refetchInterval = useFallbackInterval();
  return useQuery({
    queryKey: qk.client(code),
    queryFn: () => api<ClientResponse>(`/api/v1/clients/${encodeURIComponent(code)}/`),
    refetchInterval,
    retry: false,
    enabled,
  });
}

/**
 * How often the mailbox asks again, whatever the socket says: a letter that arrives by e-mail rings no doorbell (the
 * classic page polled its feed for the same reason).
 */
export const MAIL_POLL_MS = 20000;

/** The conversations, newest first: `state` is `""`, `unclaimed`, `mine` or `notask`, `query` a word or two. */
export function useMailThreads(state: string, query: string, enabled = true) {
  return useQuery({
    ...mailThreadsOptions(state, query),
    refetchInterval: MAIL_POLL_MS,
    // Keep the list on screen while a new search is on its way: a list that blinks away at every key is not a search.
    placeholderData: (previous) => previous,
    enabled,
  });
}

/**
 * One conversation, asked again on the mailbox's clock for the letters and replies that arrive while it is open. The
 * page keeps what the person opened and what was new; `unseen` is only true until the page has said it was read.
 */
export function useMailThread(id: number, enabled = true) {
  return useQuery({
    queryKey: qk.mailThread(id),
    queryFn: () => api<MailThreadResponse>(`/api/v1/mail/threads/${id}/`),
    refetchInterval: MAIL_POLL_MS,
    enabled,
  });
}

/** The person's own card: today, the last fortnight, the month, their devices. */
export function useAttendance() {
  const refetchInterval = useFallbackInterval();
  return useQuery({
    queryKey: qk.attendance,
    queryFn: () => api<AttendanceCard>("/api/v1/attendance/"),
    refetchInterval,
  });
}

/**
 * What the check-in screen asks right now, or `null`. It is not fetched: the page that carried the app wrote what it
 * asked at load (`main.tsx`) and `useHeartbeat` writes what each beat says, so the screen opens within a beat of the
 * shift starting and closes within a beat of the check-in - on the same poll that keeps the person "online".
 */
export function useGate(): AttendanceGate | null {
  return (
    useQuery<AttendanceGate | null>({
      queryKey: qk.gate,
      queryFn: () => null,
      enabled: false,
      initialData: null,
      staleTime: Infinity,
    }).data ?? null
  );
}

/**
 * The hand-off waiting for an answer, or `null`. It is not fetched: `useHeartbeat` writes what each beat says
 * (`App`), so the popup and the page agree with the one poll that already keeps the person "online".
 */
export function usePending(): PendingAssignment | null {
  return (
    useQuery<PendingAssignment | null>({
      queryKey: qk.pending,
      queryFn: () => null,
      enabled: false,
      initialData: null,
      staleTime: Infinity,
    }).data ?? null
  );
}

/** A hand-off read before it is taken (files, brief, time left). Not asked for with a bad id: a 404 is audited. */
export function useAssignment(id: number | null) {
  const refetchInterval = useFallbackInterval();
  return useQuery({
    queryKey: qk.assignment(id ?? 0),
    queryFn: () => api<AssignmentResponse>(`/api/v1/assignments/${id}/`),
    refetchInterval,
    enabled: id !== null,
  });
}

/** The translator's own payslip for one month (`period` is `2026-09`, or `""` for this month). */
export function usePayroll(period: string, enabled = true) {
  const refetchInterval = useFallbackInterval();
  return useQuery({
    queryKey: qk.payroll(period),
    queryFn: () => api<PayrollResponse>(`/api/v1/translator/payroll/${period ? `?period=${encodeURIComponent(period)}` : ""}`),
    refetchInterval,
    enabled,
  });
}

/** One task as its translator reads it. A task that is not theirs is a 404, which is not worth asking for again. */
export function useTranslatorTask(code: string, enabled = true) {
  const refetchInterval = useFallbackInterval();
  return useQuery({
    queryKey: qk.translatorTask(code),
    queryFn: () => api<TranslatorTaskResponse>(`/api/v1/translator/tasks/${encodeURIComponent(code)}/`),
    refetchInterval,
    enabled,
  });
}

/**
 * The translator's actions on a task are the classic endpoints, unchanged, with the checks they already make
 * (`api.task_action`, `upload_translation`, `request_extension`, `ai_check`). Two of them answer a refusal of the
 * service with `200` and `ok: false`, so that is turned into the same error as a `4xx`: one way to fail.
 */
function refused<T extends { ok: boolean }>(answer: T): T {
  if (!answer.ok) throw new ApiError(200, "refused", answer);
  return answer;
}

function useTaskAction<V, R extends { ok: boolean }>(code: string, run: (values: V) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (values: V) => refused(await run(values)),
    onSettled: () => {
      // Whatever happened, the page asks again: the answer may have moved the task (finished, a file arrived).
      void client.invalidateQueries({ queryKey: qk.translatorTask(code) });
      void client.invalidateQueries({ queryKey: qk.translatorHome });
    },
  });
}

/** «خلصت الترجمة»: the task goes to the leader's review. */
export function useFinishTask(code: string) {
  return useTaskAction<void, { ok: boolean }>(code, () =>
    api<{ ok: boolean }>(`/api/tasks/${encodeURIComponent(code)}/translated/`, { form: {} }),
  );
}

/** The translated file, into the group with the leader. */
export function useUploadTranslation(code: string) {
  return useTaskAction<File[], { ok: boolean }>(code, (files) => {
    const form = new FormData();
    for (const file of files) form.append("files", file);
    return api<{ ok: boolean }>(`/api/tasks/${encodeURIComponent(code)}/translation/`, { multipart: form });
  });
}

/** «اطلب وقت أطول»: the leader answers. */
export function useAskMoreTime(code: string) {
  return useTaskAction<{ days: number; hours: number; minutes: number; reason: string }, { ok: boolean }>(code, (values) =>
    api<{ ok: boolean }>(`/api/tasks/${encodeURIComponent(code)}/extension/`, {
      form: {
        days: String(values.days),
        hours: String(values.hours),
        minutes: String(values.minutes),
        reason: values.reason,
      },
    }),
  );
}

/** The AI check of the translation: blank boxes mean "read the files" (the server decides). Its answer is the result, not a refusal. */
export function useAiCheck(code: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (values: { source: string; translated: string }) =>
      api<AiCheckAnswer>(`/api/tasks/${encodeURIComponent(code)}/ai-check/`, {
        form: { source_text: values.source, translated_text: values.translated },
      }),
    onSettled: () => void client.invalidateQueries({ queryKey: qk.translatorTask(code) }),
  });
}

/** One of the three chat lists, optionally narrowed by a search. */
export function useChatList(kind: ChatKind, query: string, enabled = true) {
  const refetchInterval = useFallbackInterval();
  return useQuery({
    ...chatListOptions(kind, query),
    refetchInterval,
    // A role has only some of the lists: asking for another is refused, and every refusal is written to the audit log.
    enabled,
  });
}

/** Where the messages of a conversation are, from the code its row carries; `null` for a code that is none. */
export function threadPath(code: string): string | null {
  if (/^g\d+$/.test(code)) return `/api/v1/groups/${code.slice(1)}/messages/`;
  if (/^u\d+$/.test(code)) return `/api/v1/staff/${code.slice(1)}/messages/`;
  if (/^[A-Za-z0-9-]{1,40}$/.test(code)) return `/api/v1/clients/${code}/messages/`;
  return null;
}

/** Where to say "I have read this" for a conversation, or `null` where there is no room yet. */
export function readPath(code: string, room: number | undefined): string | null {
  if (/^g\d+$/.test(code)) return `/api/v1/groups/${code.slice(1)}/read/`;
  if (/^u\d+$/.test(code)) return room ? `/api/v1/groups/${room}/read/` : null;
  return /^[A-Za-z0-9-]{1,40}$/.test(code) ? `/api/v1/clients/${code}/read/` : null;
}

/** Where to write in a conversation: a client, a group, or a colleague (the room is found, or opened, from the pair). */
export function sendPath(code: string): string | null {
  if (/^g\d+$/.test(code)) return `/api/v1/groups/${code.slice(1)}/send/`;
  if (/^u\d+$/.test(code)) return `/api/v1/staff/${code.slice(1)}/send/`;
  return /^[A-Za-z0-9-]{1,40}$/.test(code) ? `/api/v1/clients/${code}/send/` : null;
}

/** One look at a conversation, outside a hook: the thread query's own function. */
export function fetchThread(code: string): Promise<ThreadResponse> {
  const path = threadPath(code);
  return path ? api<ThreadResponse>(path) : Promise.reject(new Error("not a conversation"));
}

/** What one message carries: its words, the message it answers, files, and which task they are for. */
export interface Draft {
  body: string;
  replyUid?: string;
  files?: File[];
  /** A task code, `none` (the files are not for a task), or nothing (the server decides). */
  task?: string;
  /** A voice note the page recorded. */
  voice?: Recorded;
  /** The colleagues picked from the list after an "@" (a work group's only): the server pings those still named in the words. */
  mentions?: number[];
}

/**
 * Write one message and return what the server says. The answer carries the whole thread as this person sees
 * it now, which replaces the cached one: a delivery that failed is on screen at once, as the server recorded
 * it. Cut off after a time limit - longer when there are files to upload: a send that is neither answered nor
 * refused is "not sure", never "waiting for ever" (see `lib/outbox`).
 */
export const SEND_TIMEOUT_MS = 40000;
export const SEND_TIMEOUT_FILES_MS = 120000;

export async function postMessage(code: string, draft: Draft): Promise<SendResponse> {
  const path = sendPath(code);
  if (!path) throw new Error("not a conversation");
  const files = draft.files ?? [];
  const uploads = files.length > 0 || draft.voice !== undefined;
  const abort = new AbortController();
  const timer = window.setTimeout(() => abort.abort(), uploads ? SEND_TIMEOUT_FILES_MS : SEND_TIMEOUT_MS);
  try {
    const mentions = (draft.mentions ?? []).join(",");
    if (!uploads) {
      return await api<SendResponse>(path, {
        form: { body: draft.body, ...(draft.replyUid ? { reply_uid: draft.replyUid } : {}), ...(mentions ? { mentions } : {}) },
        signal: abort.signal,
      });
    }
    const multipart = new FormData();
    multipart.append("body", draft.body);
    if (draft.replyUid) multipart.append("reply_uid", draft.replyUid);
    if (mentions) multipart.append("mentions", mentions);
    if (draft.task) multipart.append("task", draft.task);
    for (const file of files) multipart.append("files", file, file.name);
    if (draft.voice) {
      multipart.append("voice", draft.voice.blob, `voice${draft.voice.extension}`);
      multipart.append("seconds", String(draft.voice.seconds));
    }
    return await api<SendResponse>(path, { multipart, signal: abort.signal });
  } finally {
    window.clearTimeout(timer);
  }
}

/**
 * Give one of the reactions to a message, change it, or take it back (the same one again): the server answers
 * with that message's reactions as they are now, and they replace the ones in the cached thread. Nothing is
 * sent to anyone by this: a reaction is a mark between colleagues.
 */
export function useReact(code: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ uid, kind }: { uid: string; kind: string }) =>
      api<ReactResponse>("/api/v1/chats/react/", { json: { source: code, uid, kind } }),
    onSuccess: (answer) => {
      client.setQueryData<ThreadResponse>(qk.thread(code), (old) =>
        old
          ? { ...old, messages: old.messages.map((entry) => (entry.uid === answer.uid ? { ...entry, reactions: answer.reactions } : entry)) }
          : old,
      );
    },
  });
}

/**
 * Mute a conversation for yourself, or un-mute it (`/api/v1/chats/mute/`). The list rows, the open thread's own row and
 * the sidebar badge (`me`) all change with it, so all three are asked for again.
 */
export function useMuteChat(code: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (muted: boolean) => api<{ ok: true; muted: boolean }>("/api/v1/chats/mute/", { json: { source: code, muted } }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.chatLists });
      void client.invalidateQueries({ queryKey: qk.thread(code) });
      void client.invalidateQueries({ queryKey: qk.me });
    },
  });
}

/**
 * Take back a message you sent (`/api/v1/chats/unsend/`). Whatever the answer, the thread and the lists are asked for
 * again: a refusal changed nothing, but a dropped connection may have done either.
 */
export function useUnsend(code: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (uid: string) => api<{ ok: true; uid: string }>("/api/v1/chats/unsend/", { json: { source: code, uid } }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.thread(code) });
      void client.invalidateQueries({ queryKey: qk.chatLists });
    },
  });
}

/** What a forward carries: the conversation it comes from and goes to (their codes), the messages, and a word to go with them. */
export interface ForwardDraft {
  source: string;
  target: string;
  uids: string[];
  /** Files of a client's messages (ticked in "select files"), by id: forwarded on their own, without the words. */
  files?: number[];
  note: string;
}

/**
 * Forward messages of one conversation to another. Whatever the answer, the lists and both threads are asked for
 * again: a refusal wrote nothing, but a failed delivery has put the messages in the other conversation, and a
 * dropped connection may have done either.
 */
export function useForward() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (draft: ForwardDraft) => api<ForwardResponse>("/api/v1/chats/forward/", { json: draft }),
    onSettled: (_answer, _error, draft) => {
      void client.invalidateQueries({ queryKey: qk.chatLists });
      void client.invalidateQueries({ queryKey: qk.thread(draft.target) });
      void client.invalidateQueries({ queryKey: qk.thread(draft.source) });
    },
  });
}

/** The tasks this translator could hand files in to from this work group. Asked for only where it can mean something. */
export function useHandInTasks(room: number | undefined, enabled: boolean) {
  return useQuery({
    queryKey: qk.handinTasks(room ?? 0),
    queryFn: () => api<FileTasksResponse>(`/api/v1/groups/${room}/handin-tasks/`),
    enabled: enabled && room !== undefined && room > 0,
  });
}

/**
 * "Task done": these files are the translation of this task and it goes to review. Whatever the answer, what the
 * screen shows is asked for again: a hand-in tags the messages with the task and moves the task, so the group's
 * thread, the tasks on offer and the translator's own desk have all changed.
 */
export function useHandIn(room: number, code: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ task, files }: { task: string; files: number[] }) =>
      api<HandedIn>(`/api/v1/tasks/${encodeURIComponent(task)}/hand-in/`, { json: { files } }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.thread(code) });
      void client.invalidateQueries({ queryKey: qk.handinTasks(room) });
      void client.invalidateQueries({ queryKey: qk.boards });
    },
  });
}

/** Everybody a work group could be opened with. Asked for when the dialog opens, and afresh each time. */
export function usePeople(enabled: boolean) {
  return useQuery({
    queryKey: qk.people,
    queryFn: () => api<PeopleResponse>("/api/v1/people/"),
    enabled,
    staleTime: 0,
  });
}

/** Who is in a group, and - if this person may add to it - who they could add. A room that does not exist yet has none. */
export function useGroupMembers(room: number | undefined, enabled = true) {
  const refetchInterval = useFallbackInterval();
  return useQuery({
    queryKey: qk.members(room ?? 0),
    queryFn: () => api<MembersResponse>(`/api/v1/groups/${room}/members/`),
    enabled: enabled && room !== undefined && room > 0,
    refetchInterval,
  });
}

/** Open an internal work group. Nothing is sent to anyone outside by this. */
export function useCreateGroup() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (draft: { title: string; members: number[] }) => api<GroupCreated>("/api/v1/groups/", { json: draft }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.chatLists });
    },
  });
}

/** Add people to a group. The room says so in its own thread ("added to the group"), so that is asked for again too. */
export function useAddMembers(room: number, code: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (members: number[]) => api<MembersAdded>(`/api/v1/groups/${room}/members/add/`, { json: { members } }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.members(room) });
      void client.invalidateQueries({ queryKey: qk.thread(code) });
    },
  });
}

/**
 * «استلمت» under a client's message: the client is told their message arrived (on the channel it came in on) and it
 * is marked claimed. The thread - which now has our receipt in it, and the name of whoever claimed - and the lists are
 * asked for again whatever the answer: a refused one wrote nothing, but a dropped connection may have done either.
 */
export function useConfirmReceipt(code: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (messageId: number) => api<{ ok: true; message: string; claimed_by: string }>(`/api/v1/messages/${messageId}/confirm/`, { json: {} }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.thread(code) });
      void client.invalidateQueries({ queryKey: qk.chatLists });
    },
  });
}

/** Where to ask which tasks files sent in a conversation could be for: a work group or a colleague, nothing else. */
export function fileTasksPath(code: string): string | null {
  if (/^g\d+$/.test(code)) return `/api/v1/groups/${code.slice(1)}/file-tasks/`;
  if (/^u\d+$/.test(code)) return `/api/v1/staff/${code.slice(1)}/file-tasks/`;
  return null;
}

/** The tasks the files about to be sent could be for. Asked only once there are files, and afresh each time. */
export function useFileTasks(code: string, enabled: boolean) {
  const path = fileTasksPath(code);
  return useQuery({
    queryKey: qk.fileTasks(code),
    queryFn: () => api<FileTasksResponse>(path!),
    enabled: enabled && path !== null,
    staleTime: 0,
  });
}

/**
 * The messages of one conversation. Refetched when the chats' doorbell rings, or by polling without the
 * socket - and always when the conversation is opened: what the cache holds may be minutes old, and what is
 * on screen is what "read" is about (see `Conversation`).
 */
export function useThread(code: string | undefined) {
  const refetchInterval = useFallbackInterval();
  const path = code ? threadPath(code) : null;
  return useQuery({
    queryKey: qk.thread(code ?? ""),
    queryFn: () => fetchThread(code!),
    enabled: path !== null,
    refetchInterval,
    refetchOnMount: "always",
  });
}

/**
 * This person has the conversation on screen and has read it up to message `upto`, the newest the screen
 * shows (a POST, never a GET). Naming it matters: what the client wrote after the page last asked has been
 * on nobody's screen, and for a client "read" is also the blue ticks on their phone.
 */
export function useMarkChatRead() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ path, upto }: { path: string; upto: number }) => api<MovedResponse>(path, { json: { upto } }),
    onSuccess: (answer) => {
      if (answer.moved) {
        void client.invalidateQueries({ queryKey: qk.chats });
        void client.invalidateQueries({ queryKey: qk.me });
      }
    },
  });
}

/**
 * The tasks half of the menu's search: the tasks this person may open that the typing finds (the server decides, by the
 * same rules as the task page). Asked only once there are two letters, and the answer to an older typing is never shown.
 */
export function useNavTaskSearch(query: string) {
  const text = query.trim();
  return useQuery({
    queryKey: qk.navTasks(text),
    queryFn: () => api<TaskSearchResponse>(`/api/search/tasks/?q=${encodeURIComponent(text)}`),
    enabled: text.replace(/\s/g, "").length >= 2,
    staleTime: 15000,
  });
}
