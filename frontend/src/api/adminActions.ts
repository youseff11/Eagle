import { useMutation, useQueryClient } from "@tanstack/react-query";
import { download } from "../lib/download";
import { ApiError, api, apiDownload } from "./client";
import { qk } from "./keys";
import type { AdminAudit, ClientDeletePlan, ClientsDeleted, ConnectionReport, FormErrors, FormValue, GoogleSynced } from "./types";

/**
 * What the admin does on the panel's pages. Every write is a door of its own (`/api/v1/admin/...`) that gives the
 * classic form the values as its input, so the form's own rules decide: a refusal arrives as `400 invalid` with the
 * form's messages beside their fields (`formErrors`), and nothing was saved.
 */

/** The form's messages from a failed save: `{ field: [messages] }`, or `null` when the failure was not the form's. */
export function formErrors(error: unknown): FormErrors | null {
  if (!(error instanceof ApiError) || error.code !== "invalid") return null;
  const errors = (error.payload as { errors?: unknown } | null)?.errors;
  if (!errors || typeof errors !== "object") return null;
  const out: FormErrors = {};
  for (const [name, messages] of Object.entries(errors as Record<string, unknown>)) {
    if (Array.isArray(messages)) out[name] = messages.filter((message): message is string => typeof message === "string");
  }
  return out;
}

/** The values that differ from what the server sent: a save carries only what was touched. */
export type FormChanges = Record<string, FormValue>;

export function useCreateUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (values: FormChanges) => api<{ ok: true; id: number }>("/api/v1/admin/users/create/", { json: { values } }),
    onSuccess: () => void client.invalidateQueries({ queryKey: qk.adminUsers }),
  });
}

export function useSaveUser(id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (values: FormChanges) => api<{ ok: true }>(`/api/v1/admin/users/${id}/save/`, { json: { values } }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: qk.adminUser(id) });
      void client.invalidateQueries({ queryKey: qk.adminUsers });
      // A name or a role changed may be the signed-in person's own.
      void client.invalidateQueries({ queryKey: qk.me });
    },
  });
}

function useShiftWrite<V, R = unknown>(id: number, run: (values: V) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.adminUser(id) });
      void client.invalidateQueries({ queryKey: qk.adminUsers });
    },
  });
}

export function useAddShift(id: number) {
  return useShiftWrite<{ weekday: number; start_time: string; end_time: string }>(id, (values) =>
    api(`/api/v1/admin/users/${id}/shifts/add/`, { json: values }),
  );
}

export function useDeleteShift(id: number) {
  return useShiftWrite<number>(id, (shift) => api(`/api/v1/admin/users/${id}/shifts/${shift}/delete/`, { json: {} }));
}

/** One of the company's shifts for some weekdays, none, or a new one (`template` is its id, `""`, or `"new"`). */
export interface ShiftChoice {
  template: string;
  weekdays: number[];
  new_name?: string;
  new_start?: string;
  new_end?: string;
}

export function usePickShift(id: number) {
  return useShiftWrite<ShiftChoice, { ok: true; label: string }>(id, (choice) =>
    api<{ ok: true; label: string }>(`/api/v1/admin/users/${id}/shift/`, { json: choice }),
  );
}

/** Ask Google for the company mailbox's addresses: made as a person's file opens, then the file is asked for again. */
export function useSyncAliases(id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<{ ok: true; ran: boolean }>("/api/v1/admin/aliases/sync/", { json: {} }),
    onSuccess: (answer) => {
      if (answer.ran) void client.invalidateQueries({ queryKey: qk.adminUser(id) });
    },
  });
}

export function useCreateClient() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (values: FormChanges) => api<{ ok: true; code: string }>("/api/v1/admin/clients/create/", { json: { values } }),
    onSuccess: () => void client.invalidateQueries({ queryKey: qk.adminClientsAll }),
  });
}

export function useSaveClient(code: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (values: FormChanges) => api<{ ok: true; code: string }>(`/api/v1/admin/clients/${encodeURIComponent(code)}/save/`, { json: { values } }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: qk.adminClient(code) });
      void client.invalidateQueries({ queryKey: qk.adminClientsAll });
    },
  });
}

/** Step one of deleting clients: what would go with each, and which cannot. Changes nothing. */
export function useClientDeletePlan() {
  return useMutation({
    mutationFn: (ids: number[]) => api<ClientDeletePlan>("/api/v1/admin/clients/delete-plan/", { json: { ids } }),
  });
}

/**
 * Step two: the yes, with the admin's own password. The server works the blockers out again and answers with the backup of
 * what went, which is saved as a file before anything else happens because by then it is the only copy. The password is in
 * this one request and is not kept anywhere here.
 */
export function useDeleteClients() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ ids, password }: { ids: number[]; password: string }): Promise<ClientsDeleted> => {
      const answer = await apiDownload("/api/v1/admin/clients/delete/", { ids, password, confirm: true }, "eagle-clients-backup.json");
      download.save(answer.blob, answer.filename);
      return {
        deleted: Number(answer.headers.get("X-Eagle-Deleted") ?? 0),
        blocked: Number(answer.headers.get("X-Eagle-Blocked") ?? 0),
        files: Number(answer.headers.get("X-Eagle-Files") ?? 0),
        filename: answer.filename,
      };
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.adminClientsAll });
      void client.invalidateQueries({ queryKey: qk.boards });
    },
  });
}

/**
 * The next page of the audit log, older than the row with id `before`. Kept out of the query cache on purpose: the first page
 * is what the refresh button asks again, and older pages are only ever added under it.
 */
export function useOlderAudit(only: string) {
  return useMutation({
    mutationFn: (before: number) => {
      const query = new URLSearchParams();
      if (only) query.set("only", only);
      query.set("before", String(before));
      return api<AdminAudit>(`/api/v1/admin/audit/?${query.toString()}`);
    },
  });
}

/** A message sent as if a client sent it (multipart, so it can carry files). */
export function useSimulateSend() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (message: { channel: string; sender_identity: string; subject: string; body: string; files: File[] }) => {
      const form = new FormData();
      form.append("channel", message.channel);
      form.append("sender_identity", message.sender_identity);
      form.append("subject", message.subject);
      form.append("body", message.body);
      for (const file of message.files) form.append("files", file);
      return api<{ ok: true; id: number; code: string; blocked: boolean }>("/api/v1/admin/simulate/send/", { multipart: form });
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: qk.adminSimulate });
      void client.invalidateQueries({ queryKey: qk.boards });
    },
  });
}

/** What a clear-out did: how many rows went, how many stored files, and the name of the backup that was saved. */
export interface ResetDone {
  deleted: number;
  files: number;
  filename: string;
}

/**
 * Run a clear-out (`tasks` or `mail`) with the admin's own password and the explicit yes. The answer is the backup of what
 * was deleted: it is saved as a file before anything else happens, because it is the only copy. The password is in this
 * one request and is not kept anywhere here.
 */
export function useRunReset(kind: "tasks" | "mail") {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (password: string): Promise<ResetDone> => {
      const answer = await apiDownload(`/api/v1/admin/reset/${kind}/run/`, { password, confirm: true }, `eagle-${kind}-backup.json`);
      download.save(answer.blob, answer.filename);
      return {
        deleted: Number(answer.headers.get("X-Eagle-Deleted") ?? 0),
        files: Number(answer.headers.get("X-Eagle-Files") ?? 0),
        filename: answer.filename,
      };
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.adminResetCounts(kind) });
      void client.invalidateQueries({ queryKey: qk.boards });
    },
  });
}

/**
 * Save the settings that were changed (a secret only when it was typed or explicitly cleared). The form decides what is valid.
 * The rollout switches are among them: a save that moves them changes which people are sent to which interface, so the
 * signed-in person's own menu is asked for again.
 */
export function useSaveSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (values: FormChanges) => api<{ ok: true }>("/api/v1/admin/settings/save/", { json: { values } }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: qk.adminSettings });
      void client.invalidateQueries({ queryKey: qk.me });
    },
  });
}

/** The alias list from Google, now. */
export function useGoogleSync() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<GoogleSynced>("/api/v1/admin/settings/google/sync/", { json: {} }),
    onSettled: () => void client.invalidateQueries({ queryKey: qk.adminSettings }),
  });
}

export function useGoogleDisconnect() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<{ ok: true }>("/api/v1/admin/settings/google/disconnect/", { json: {} }),
    onSettled: () => void client.invalidateQueries({ queryKey: qk.adminSettings }),
  });
}

/** Check the saved WhatsApp or mail credentials, and send a test to `to` when one is given. */
export function useConnectionTest(kind: "whatsapp" | "email") {
  return useMutation({
    mutationFn: (to: string) => api<ConnectionReport>(`/api/v1/admin/settings/test/${kind}/`, { json: { to } }),
  });
}
