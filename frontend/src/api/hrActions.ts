import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { FormChanges } from "./adminActions";
import { api } from "./client";
import { qk } from "./keys";

/** What the shift picker sends: the chosen shift (an id, `new`, or empty), the working days, and the three boxes of a new shift. */
interface ShiftChoiceBody {
  template: string;
  weekdays: number[];
  new_name: string;
  new_start: string;
  new_end: string;
}

/**
 * What HR does on its pages. Every write is a door of its own (`/api/v1/hr/...`): the classic forms decide what is valid (a
 * refusal arrives as `400 invalid` with the form's messages, see `formErrors`), and a refusal the engine gives answers `409`
 * with its words. After any write the pages ask again: a figure on screen is only as good as the last time it was read.
 */
function useWrite<V, R>(run: (values: V) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.hr });
      // The register counts a person's shifts, and it lives with the boards (the socket asks it again).
      void client.invalidateQueries({ queryKey: qk.hrRegisterAll });
    },
  });
}

/** Apply a star penalty (`confirm`: the stars stay off) or forgive it (`forgive`: they are given back); the note is optional. */
export function useDecidePenalty() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action, note }: { id: number; action: "confirm" | "forgive"; note: string }) =>
      api<{ ok: true }>(`/api/v1/hr/penalties/${id}/${action}/`, { json: { note } }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.hr });
      void client.invalidateQueries({ queryKey: qk.hrRegisterAll });
      // The accounts violations page lists the same penalties.
      void client.invalidateQueries({ queryKey: qk.accountsViolations });
    },
  });
}

/** Correct a day: the boxes that changed, and the reason (not optional). */
export function useSaveHrDay(id: number) {
  return useWrite<FormChanges, { ok: true; written: string[] }>((values) => api(`/api/v1/hr/attendance/${id}/save/`, { json: { values } }));
}

/** «راجعته»: HR has looked at a flagged day. */
export function useClearHrDay(id: number) {
  return useWrite<string, { ok: true }>((reason) => api(`/api/v1/hr/attendance/${id}/clear/`, { json: { reason } }));
}

/** Add a day to a person's roster; a day added here is switched on. */
export function useAddRosterDay() {
  return useWrite<{ user: number; values: FormChanges }, { ok: true; id: number }>((body) => api("/api/v1/hr/schedules/shift/", { json: body }));
}

export function useDeleteRosterDay() {
  return useWrite<number, { ok: true; user: number }>((id) => api(`/api/v1/hr/schedules/shift/${id}/delete/`, { json: {} }));
}

/** Move one date for a person; a second save for the same date replaces the first. */
export function useAddOverride() {
  return useWrite<{ user: number; values: FormChanges }, { ok: true; id: number }>((body) => api("/api/v1/hr/schedules/override/", { json: body }));
}

export function useDeleteOverride() {
  return useWrite<number, { ok: true; user: number }>((id) => api(`/api/v1/hr/schedules/override/${id}/delete/`, { json: {} }));
}

/** A company shift from the four boxes on the schedules page. */
export function useAddTemplate() {
  return useWrite<FormChanges, { ok: true; id: number }>((values) => api("/api/v1/hr/schedules/template/", { json: { values } }));
}

/** Add a company shift (no `id`) or change one. */
export function useSaveShift() {
  return useWrite<{ id: number | null; values: FormChanges }, { ok: true; id: number }>(({ id, values }) =>
    api("/api/v1/hr/shifts/save/", { json: id === null ? { values } : { id, values } }),
  );
}

export function useDeleteShift() {
  return useWrite<number, { ok: true }>((id) => api(`/api/v1/hr/shifts/${id}/delete/`, { json: {} }));
}

export function useSaveOffice() {
  return useWrite<{ id: number | null; values: FormChanges }, { ok: true; id: number }>(({ id, values }) =>
    api("/api/v1/hr/offices/save/", { json: id === null ? { values } : { id, values } }),
  );
}

export function useDeleteOffice() {
  return useWrite<number, { ok: true; deleted: number }>((id) => api(`/api/v1/hr/offices/${id}/delete/`, { json: {} }));
}

/** Approve or reject a browser. */
export function useDecideDevice() {
  return useWrite<{ id: number; action: "approve" | "reject" }, { ok: true }>(({ id, action }) =>
    api(`/api/v1/hr/devices/${id}/${action}/`, { json: {} }),
  );
}

/** Approve or reject an overtime claim that is waiting. */
export function useDecideClaim() {
  return useWrite<{ id: number; action: "approve" | "reject" }, { ok: true }>(({ id, action }) =>
    api(`/api/v1/hr/overtime/${id}/${action}/`, { json: {} }),
  );
}

/** Put a person on a company shift for some weekdays, on none, or on a new one. */
export function usePickHrShift(id: number) {
  return useWrite<ShiftChoiceBody, { ok: true; label: string }>((body) => api(`/api/v1/hr/employees/${id}/shift/`, { json: body }));
}

/** Home or office, from the employee's file. */
export function useSetWorkMode(id: number) {
  return useWrite<string, { ok: true }>((mode) => api(`/api/v1/hr/employees/${id}/work-mode/`, { json: { work_mode: mode } }));
}

/** Set a person's incentive - the sum added to their pay each month, by hand (`"0"` takes it off): the admin's alone. */
export function useSetIncentive(id: number) {
  return useWrite<string, { ok: true; incentive: string }>((amount) => api(`/api/v1/hr/employees/${id}/incentive/`, { json: { amount } }));
}

/** Give a person a salary plan, or none (`null`): the admin's alone. */
export function useAssignPlan(id: number) {
  return useWrite<number | null, { ok: true }>((plan) => api(`/api/v1/hr/employees/${id}/plan/`, { json: { plan } }));
}

/** Record a probation review's verdict. */
export function useDecideReview(id: number) {
  return useWrite<FormChanges, { ok: true }>((values) => api(`/api/v1/hr/probation/${id}/decide/`, { json: { values } }));
}

/** Open the three reviews for somebody hired before there were any. */
export function useOpenReviews() {
  return useWrite<number, { ok: true; created: number }>((person) => api(`/api/v1/hr/probation/open/${person}/`, { json: {} }));
}

export function useLogComplaint() {
  return useWrite<FormChanges, { ok: true; id: number }>((values) => api("/api/v1/hr/complaints/create/", { json: { values } }));
}

/** Close a complaint, or open it again. */
export function useResolveComplaint() {
  return useWrite<number, { ok: true; resolved: boolean }>((id) => api(`/api/v1/hr/complaints/${id}/resolve/`, { json: {} }));
}

/** Ask the owner for a salary change; nothing moves until they approve. */
export function useAskSalaryChange() {
  return useWrite<{ user: number; values: FormChanges }, { ok: true; id: number }>((body) => api("/api/v1/hr/salary-requests/create/", { json: body }));
}

/** The owner's decision on a salary change. */
export function useDecideSalaryChange() {
  return useWrite<{ id: number; action: "approve" | "reject"; note: string }, { ok: true }>(({ id, action, note }) =>
    api(`/api/v1/hr/salary-requests/${id}/${action}/`, { json: { note } }),
  );
}

/** Add a salary plan (no `id`) or change one. */
export function useSavePlan() {
  return useWrite<{ id: number | null; values: FormChanges }, { ok: true; id: number }>(({ id, values }) =>
    api("/api/v1/hr/salary-plans/save/", { json: id === null ? { values } : { id, values } }),
  );
}

// Recruitment: the pipeline side

/** Add a vacancy; its code comes back so the page can go on to choose the bot's questions. */
export function useCreateVacancy() {
  return useWrite<FormChanges, { ok: true; code: string }>((values) => api("/api/v1/hr/vacancies/create/", { json: { values } }));
}

/** Change a vacancy: the boxes that changed. A deadline left out is left alone. */
export function useSaveVacancy(code: string) {
  return useWrite<FormChanges, { ok: true }>((values) => api(`/api/v1/hr/vacancies/${encodeURIComponent(code)}/save/`, { json: { values } }));
}

/** Give the vacancy a question from the bank. */
export function useAddVacancyQuestion(code: string) {
  return useWrite<number, { ok: true; id: number; added: boolean }>((question) =>
    api(`/api/v1/hr/vacancies/${encodeURIComponent(code)}/questions/`, { json: { question } }),
  );
}

/** The order and the "required" box of every question the vacancy has, in one save. */
export function useOrderVacancyQuestions(code: string) {
  return useWrite<{ id: number; order: number; required: boolean }[], { ok: true; saved: number }>((rows) =>
    api(`/api/v1/hr/vacancies/${encodeURIComponent(code)}/questions/order/`, { json: { rows } }),
  );
}

export function useRemoveVacancyQuestion() {
  return useWrite<number, { ok: true; code: string }>((link) => api(`/api/v1/hr/vacancies/questions/${link}/delete/`, { json: {} }));
}

/** Add a question to the bank (no `id`) or change one. */
export function useSaveQuestion() {
  return useWrite<{ id: number | null; values: FormChanges }, { ok: true; id: number }>(({ id, values }) =>
    api("/api/v1/hr/questions/save/", { json: id === null ? { values } : { id, values } }),
  );
}

export function useAddDepartment() {
  return useWrite<FormChanges, { ok: true; id: number }>((values) => api("/api/v1/hr/departments/", { json: { values } }));
}

/** The recruitment rules: only the boxes that changed. */
export function useSaveRecruitSettings() {
  return useWrite<FormChanges, unknown>((values) => api("/api/v1/hr/recruitment/settings/save/", { json: { values } }));
}

// Recruitment: the candidates' side

/** A write that may carry a file: JSON when there is none, otherwise the values (as JSON text) and the file side by side. */
function withFile(values: FormChanges, field: string, file: File | null): { json: unknown } | { multipart: FormData } {
  if (!file) return { json: { values } };
  const body = new FormData();
  body.append("values", JSON.stringify(values));
  body.append(field, file);
  return { multipart: body };
}

/** Change the profile: the boxes that changed. The CV is its own write (`useUploadCv`). */
export function useSaveCandidate(code: string) {
  return useWrite<FormChanges, { ok: true }>((values) => api(`/api/v1/hr/candidates/${encodeURIComponent(code)}/save/`, { json: { values } }));
}

export function useUploadCv(code: string) {
  return useWrite<File, { ok: true }>((file) => {
    const body = new FormData();
    body.append("file", file);
    return api(`/api/v1/hr/candidates/${encodeURIComponent(code)}/cv/`, { multipart: body });
  });
}

/** Move the candidate along the pipeline; the server says where they may go. */
export function useMoveCandidate(code: string) {
  return useWrite<{ status: string; reason: string }, { ok: true }>((body) =>
    api(`/api/v1/hr/candidates/${encodeURIComponent(code)}/status/`, { json: body }),
  );
}

/** Tell this candidate who the company is. Logged, and not undone. */
export function useRevealCandidate(code: string) {
  return useWrite<string, { ok: true }>((reason) => api(`/api/v1/hr/candidates/${encodeURIComponent(code)}/reveal/`, { json: { reason } }));
}

/** Write to the candidate. The server sends it through the identity filter; nothing here ever sends by another road. */
export function useMessageCandidate(code: string) {
  return useWrite<string, { ok: true }>((body) => api(`/api/v1/hr/candidates/${encodeURIComponent(code)}/message/`, { json: { body } }));
}

export function useBookInterview(code: string) {
  return useWrite<FormChanges, { ok: true; id: number }>((values) =>
    api(`/api/v1/hr/candidates/${encodeURIComponent(code)}/interviews/`, { json: { values } }),
  );
}

export function useScoreInterview(id: number) {
  return useWrite<FormChanges, { ok: true; total: number; max: number }>((values) =>
    api(`/api/v1/hr/interviews/${id}/score/`, { json: { values } }),
  );
}

/** Set the candidate a test: the form's boxes (and the deadline boxes) and, if there is one, its file. */
export function useSetCandidateTest(code: string) {
  return useWrite<{ values: FormChanges; file: File | null }, { ok: true; id: number }>(({ values, file }) =>
    api(`/api/v1/hr/candidates/${encodeURIComponent(code)}/tests/`, withFile(values, "assignment", file)),
  );
}

/** The owner's decision on a hire. */
export function useDecideHire() {
  return useWrite<{ code: string; action: "approve" | "reject"; reason: string }, { ok: true }>(({ code, action, reason }) =>
    api(`/api/v1/hr/approvals/${encodeURIComponent(code)}/${action}/`, { json: { reason } }),
  );
}

/** Turn an approved candidate into an employee. The password rides in this request and nowhere else. */
export function useHire(code: string) {
  return useWrite<FormChanges, { ok: true; id: number; username: string }>((values) =>
    api(`/api/v1/hr/candidates/${encodeURIComponent(code)}/hire/save/`, { json: { values } }),
  );
}

/** Mark a candidate's test (and attach the candidate's work with it). The HR pages and the reviewer's both read it again. */
export function useMarkTest(id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ values, file }: { values: FormChanges; file: File | null }) =>
      api<{ ok: true; total: number; max: number }>(`/api/v1/reviewer/tests/${id}/score/`, withFile(values, "submission", file)),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.hr });
      void client.invalidateQueries({ queryKey: qk.reviewer });
    },
  });
}
