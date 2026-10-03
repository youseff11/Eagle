import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRealtimeStatus } from "../realtime/RealtimeProvider";
import { ApiError, api } from "./client";
import type { Recorded } from "../lib/recorder";
import { qk } from "./keys";
import type {
  AiCheckAnswer,
  AssignmentResponse,
  ChatKind,
  ChatListResponse,
  ClientResponse,
  ClientsResponse,
  FileTasksResponse,
  ForwardResponse,
  GroupCreated,
  HandedIn,
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
  SendResponse,
  ThreadResponse,
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
  return useInfiniteQuery({
    queryKey: qk.notifications,
    initialPageParam: null as number | null,
    queryFn: ({ pageParam }) =>
      api<NotificationsResponse>(
        `/api/v1/notifications/?limit=${PAGE}${pageParam ? `&before=${pageParam}` : ""}`,
      ),
    getNextPageParam: (last) => last.next_before,
    refetchInterval,
  });
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
    queryKey: qk.translatorHome,
    queryFn: () => api<TranslatorHomeResponse>("/api/v1/translator/home/"),
    refetchInterval,
    // Everybody else is refused, and every refusal is written to the audit log: a page left
    // open would write a row at every refresh.
    enabled,
  });
}

/** The operation's task list: `""` is every task, `open` the ones being worked, or one status. */
export function useTasks(status: string, enabled = true) {
  const refetchInterval = useFallbackInterval();
  return useQuery({
    queryKey: qk.tasks(status),
    queryFn: () => api<TasksResponse>(`/api/v1/tasks/${status ? `?status=${encodeURIComponent(status)}` : ""}`),
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
    queryKey: qk.team,
    queryFn: () => api<TeamResponse>("/api/v1/team/"),
    refetchInterval,
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
  const params = new URLSearchParams();
  if (state) params.set("state", state);
  if (query) params.set("q", query);
  const text = params.toString();
  return useQuery({
    queryKey: qk.mail(state, query),
    queryFn: () => api<MailListResponse>(`/api/v1/mail/threads/${text ? `?${text}` : ""}`),
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
    queryKey: qk.chatList(kind, query),
    queryFn: () =>
      api<ChatListResponse>(`/api/v1/chats/?type=${kind}${query ? `&q=${encodeURIComponent(query)}` : ""}`),
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
    if (!uploads) {
      return await api<SendResponse>(path, {
        form: { body: draft.body, ...(draft.replyUid ? { reply_uid: draft.replyUid } : {}) },
        signal: abort.signal,
      });
    }
    const multipart = new FormData();
    multipart.append("body", draft.body);
    if (draft.replyUid) multipart.append("reply_uid", draft.replyUid);
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
