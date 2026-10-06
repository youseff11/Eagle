import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "./client";
import { qk } from "./keys";
import type { SalesLine } from "./types";

/**
 * What the operation does on a task: the classic endpoints, unchanged, with the checks they already make
 * (`api.assign_lead`, `task_action`, `deliver`, `set_deadline`) - and the two doors that were redirects with a
 * flash message on the classic page (the word count, a requirement), which answer in JSON here.
 *
 * Two of the classic ones refuse with a `200` and `ok: false`; that is turned into the same error as a `4xx`, so
 * there is one way to fail. Whatever happened, the page asks again afterwards: the answer may have moved the task
 * (it went to a leader, it was sent), and a doorbell that rang meanwhile is not a reason to guess.
 */
function refused<T extends { ok: boolean }>(answer: T): T {
  if (!answer.ok) throw new ApiError(200, "refused", answer);
  return answer;
}

function useOpsAction<V, R extends { ok: boolean }>(code: string, run: (values: V) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (values: V) => refused(await run(values)),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.opsTask(code) });
      // The lists and the board show the same task: a leader was given it, it was sent.
      void client.invalidateQueries({ queryKey: qk.boards });
    },
  });
}

const base = (code: string) => `/api/tasks/${encodeURIComponent(code)}`;

/** «ابعتها للتيم ليدر»: a new task goes to one leader, who has a minute to say yes. */
export function useAssignLead(code: string) {
  return useOpsAction<number, { ok: boolean }>(code, (leader) =>
    api<{ ok: boolean }>(`${base(code)}/assign-lead/`, { form: { user: String(leader) } }),
  );
}

/** «استلمت التاسك»: somebody is on record as having it before anything leaves for the client. */
export function useTakeOver(code: string) {
  return useOpsAction<void, { ok: boolean }>(code, () => api<{ ok: boolean }>(`${base(code)}/ack/`, { form: {} }));
}

export function useCancelTask(code: string) {
  return useOpsAction<void, { ok: boolean }>(code, () => api<{ ok: boolean }>(`${base(code)}/cancel/`, { form: {} }));
}

/** The admin puts somebody into the task group (an admin who took the client's message opens it with no operation in). */
export function useAddMember(code: string) {
  return useOpsAction<number, { ok: boolean }>(code, (person) =>
    api<{ ok: boolean }>(`${base(code)}/add-member/`, { form: { user: String(person) } }),
  );
}

/** What was sent to the client, and over which channel (`api.deliver`). */
export interface Delivered {
  ok: boolean;
  status: string;
  channel: string;
  files: number;
}

/**
 * Send the ticked files and a note to the client and close the task (`send`), or close it without sending anything.
 * Repeated `attachments` fields, so it goes as a form with parts, never as JSON.
 */
export function useDeliver(code: string) {
  return useOpsAction<{ files: number[]; note: string; send: boolean }, Delivered>(code, (values) => {
    const form = new FormData();
    for (const id of values.files) form.append("attachments", String(id));
    form.append("note", values.note);
    form.append("send", values.send ? "1" : "0");
    return api<Delivered>(`${base(code)}/deliver/`, { multipart: form });
  });
}

/**
 * Days, hours and minutes from now. A box left empty is "leave it as it is"; zeros are "no deadline" - the
 * classic rule, kept by the server (`forms.DeadlineField`). Only the boxes the person typed in are sent.
 */
export function useSaveDeadline(code: string) {
  return useOpsAction<{ days: string; hours: string; minutes: string }, { ok: boolean }>(code, (values) =>
    api<{ ok: boolean }>(`${base(code)}/deadline/`, {
      form: { deadline_days: values.days, deadline_hours: values.hours, deadline_minutes: values.minutes },
    }),
  );
}

/** What the new-task form sends: its boxes, and what the task is made from. */
export interface NewTask {
  client: number;
  title: string;
  description: string;
  source_lang: string;
  target_lang: string;
  priority: string;
  deadline: { days: string; hours: string; minutes: string };
  word_count: number | null;
  is_difficult: boolean;
  is_secondary_language: boolean;
  messages: number[];
  files: number[];
  from: string;
}

/**
 * Make a task. A refusal names the boxes that were wrong (`ApiError.payload.fields`), in the words of the form, and
 * nothing is made. The lists and the board are asked again: there is one more task on them.
 */
export function useCreateTask() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (values: NewTask) => refused(await api<{ ok: boolean; code: string }>("/api/v1/task-form/create/", { json: values })),
    onSuccess: () => void client.invalidateQueries({ queryKey: qk.boards }),
  });
}

export function useSaveWords(code: string) {
  return useOpsAction<number, { ok: boolean }>(code, (words) =>
    api<{ ok: boolean }>(`/api/v1/tasks/${encodeURIComponent(code)}/words/`, { json: { words } }),
  );
}

export function useAddRequirement(code: string) {
  return useOpsAction<{ kind: string; text: string }, { ok: boolean }>(code, (values) =>
    api<{ ok: boolean }>(`/api/v1/tasks/${encodeURIComponent(code)}/requirements/`, { json: values }),
  );
}

/** A requirement added to a client from the client's own page: the answer is the row. */
export function useAddClientRequirement(code: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (values: { kind: string; text: string }) =>
      refused(await api<{ ok: boolean }>(`/api/v1/clients/${encodeURIComponent(code)}/requirements/`, { json: values })),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.client(code) });
      // The list counts them.
      void client.invalidateQueries({ queryKey: ["boards", "clients", "list"] });
    },
  });
}

/**
 * Save a Sales person's own WhatsApp number. A refusal names the box and says why in the classic page's words
 * (`ApiError.payload.fields`), and nothing is saved; the answer is the line as it is now.
 */
export function useSaveLine() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (values: { wa_phone_number_id: string; wa_display_number: string }) =>
      api<SalesLine>("/api/v1/sales/line/save/", { json: values }),
    onSuccess: (line) => client.setQueryData(qk.salesLine, line),
  });
}

/**
 * «أعد الفحص»: ask for the check again (the classic endpoint, for the task's own leader and the admin). It runs in the
 * background and the box follows it; a refusal comes back as a sentence of its own (the switch is off, one is running).
 */
export function useAiRecheck(code: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => refused(await api<{ ok: boolean }>(`/api/tasks/${encodeURIComponent(code)}/ai-recheck/`, { form: {} })),
    onSettled: () => void client.invalidateQueries({ queryKey: qk.aiNotes(code) }),
  });
}

/**
 * The team leader accepts notes - some, or all: each one takes stars off the translator (and HR or the admin may apply or forgive
 * it). A refusal comes back as a code (`already`, `stale_check`, `no_translator` ...).
 */
export function useAiAccept(code: string) {
  const client = useQueryClient();
  return useMutation({
    // `check` is the check the box showed: the ids are places in it, and a newer check has other notes under the same places.
    mutationFn: (body: ({ issues: number[] } | { all: true }) & { check: number }) =>
      api<{ ok: true; taken: string }>(`/api/v1/tasks/${encodeURIComponent(code)}/ai-notes/accept/`, { json: body }),
    onSettled: () => void client.invalidateQueries({ queryKey: qk.aiNotes(code) }),
  });
}

/** The team leader's own date for the translator, or the translator's date changed: days, hours, minutes from now. */
export interface TranslatorDate {
  days: string;
  hours: string;
  minutes: string;
}

const dateForm = (date: TranslatorDate) => ({
  tdeadline_days: date.days,
  tdeadline_hours: date.hours,
  tdeadline_minutes: date.minutes,
});

/**
 * «ابعتها للمترجم»: the task goes to one translator, who has a minute to say yes, and the leader's own date goes with it
 * (shorter than the client's on purpose: the difference is the time the leader keeps to review). Boxes left empty are the
 * client's own date. The classic endpoint keeps its checks (the team, the status, a date past the client's).
 */
export function useAssignTranslator(code: string) {
  return useOpsAction<{ translator: number; date: TranslatorDate }, { ok: boolean }>(code, ({ translator, date }) =>
    api<{ ok: boolean }>(`${base(code)}/assign-translator/`, { form: { user: String(translator), ...dateForm(date) } }),
  );
}

/** «حفظ ديدلاين المترجم»: only the boxes that were typed in are sent; zeros clear it (the translator works to the client's date). */
export function useSaveTranslatorDeadline(code: string) {
  return useOpsAction<TranslatorDate, { ok: boolean }>(code, (date) =>
    api<{ ok: boolean }>(`${base(code)}/translator-deadline/`, { form: dateForm(date) }),
  );
}

/** The leader's yes or no to a translator's request for more time: nothing moves before the answer. */
export function useDecideExtension(code: string) {
  return useOpsAction<{ id: number; decision: "approve" | "decline" }, { ok: boolean }>(code, ({ id, decision }) =>
    api<{ ok: boolean }>(`/api/extensions/${id}/${decision}/`, { form: {} }),
  );
}

/** «تمت المراجعة»: the review is done and the task goes on to the operation. */
export function useFinishReview(code: string) {
  return useOpsAction<void, { ok: boolean }>(code, () => api<{ ok: boolean }>(`${base(code)}/reviewed/`, { form: {} }));
}
