import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { FormChanges } from "./adminActions";
import { api } from "./client";
import { qk } from "./keys";

/**
 * What a person does about leave: ask, withdraw, and (the manager and HR) decide. The classic form decides what is valid (a
 * refusal arrives as `400 invalid` with the form's messages, see `formErrors`), and a rule of the engine answers `409` with its
 * words. After any write the pages ask again, the person's own and HR's queue both: a request is one row seen from two sides.
 */
function useWrite<V, R>(run: (values: V) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.leave });
      void client.invalidateQueries({ queryKey: qk.hr });
    },
  });
}

/** Ask for time off. */
export function useAskLeave() {
  return useWrite<FormChanges, { ok: true; id: number }>((values) => api("/api/v1/leave/request/", { json: { values } }));
}

/** Withdraw your own request while nobody has acted on it. */
export function useCancelLeave() {
  return useWrite<number, { ok: true }>((id) => api(`/api/v1/leave/${id}/cancel/`, { json: {} }));
}

/** Approve or reject a request (the manager's step or HR's). A rejection can carry the reason. */
export function useDecideLeave() {
  return useWrite<{ id: number; action: "approve" | "reject"; note: string }, { ok: true }>(({ id, action, note }) =>
    api(`/api/v1/leave/${id}/${action}/`, { json: { note } }),
  );
}
