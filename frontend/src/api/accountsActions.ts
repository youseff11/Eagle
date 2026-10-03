import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { FormChanges } from "./adminActions";
import { api } from "./client";
import { qk } from "./keys";

/**
 * What accounting and the admin do on the money pages. Every write is a door of its own (`/api/v1/accounts/...`): the classic
 * forms decide what is valid (a refusal arrives as `400 invalid` with the form's messages, see `formErrors`), a locked month
 * and a decided deduction answer `409` with the reason, and nothing here moves money by itself. After any write the pages ask
 * again: a number on screen is only as good as the last time it was read.
 */
function useWrite<V, R>(run: (values: V) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSettled: () => void client.invalidateQueries({ queryKey: qk.accounts }),
  });
}

/** «احسب الشهر»: run a month (`2026-09`). */
export function useRunMonth() {
  return useWrite<string, { ok: true }>((period) => api("/api/v1/accounts/recalculate/", { json: { period } }));
}

/** Approve a month, or lock it. */
export function useApprovePeriod() {
  return useWrite<{ id: number; lock: boolean }, { ok: true }>(({ id, lock }) =>
    api(`/api/v1/accounts/periods/${id}/approve/`, { json: { lock } }),
  );
}

/** Release a line's two monthly bonuses (the admin's). */
export function useReleaseBonuses(id: number) {
  return useWrite<void, { ok: true }>(() => api(`/api/v1/accounts/lines/${id}/bonus/`, { json: {} }));
}

/** Re-derive a month's words from the job log (what opening the sheet used to do on the classic page), then read the sheet again. */
export function useRefreshWords() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (values: { user: number; period: string }) => api<{ ok: true }>("/api/v1/accounts/attendance/refresh/", { json: values }),
    onSuccess: () => void client.invalidateQueries({ queryKey: qk.accounts }),
  });
}

/** Record a day. The whole row is what is sent, as on the classic sheet. */
export function useSaveDay() {
  return useWrite<{ user: number; values: FormChanges }, { ok: true; id: number }>((body) => api("/api/v1/accounts/attendance/save/", { json: body }));
}

/** Propose a deduction. */
export function useProposeViolation() {
  return useWrite<FormChanges, { ok: true; id: number }>((values) => api("/api/v1/accounts/violations/create/", { json: { values } }));
}

/** Approve or reject a deduction that is waiting. */
export function useDecideViolation() {
  return useWrite<{ id: number; action: "approve" | "reject" }, { ok: true }>(({ id, action }) =>
    api(`/api/v1/accounts/violations/${id}/${action}/`, { json: {} }),
  );
}

/** Add a salary: history is append-only. */
export function useSaveSalary(id: number) {
  return useWrite<FormChanges, { ok: true; id: number }>((values) => api(`/api/v1/accounts/salary/${id}/save/`, { json: { values } }));
}

/** Save the payroll rules that were changed. */
export function useSaveRules() {
  return useWrite<FormChanges, { ok: true }>((values) => api("/api/v1/accounts/rules/save/", { json: { values } }));
}

export function useAddTier() {
  return useWrite<FormChanges, { ok: true; id: number }>((values) => api("/api/v1/accounts/rules/tiers/add/", { json: { values } }));
}

export function useDeleteTier() {
  return useWrite<number, { ok: true; deleted: number }>((id) => api(`/api/v1/accounts/rules/tiers/${id}/delete/`, { json: {} }));
}
