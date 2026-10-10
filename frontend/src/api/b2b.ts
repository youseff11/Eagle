import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "./client";
import { qk } from "./keys";

/**
 * The B2B company sheets (`/api/v1/b2b/`, `dashboard/api_b2b.py`). The Sales manager makes a sheet and gives it to a Sales
 * person, who fills it with companies and contacts each one from its row. What reaches the company on that person's line
 * marks the row by itself; a call is written by hand. Who may do what is the server's (`b2b.py`): the page draws what the
 * answer says (`can_manage`, `can_contact`) and nothing more.
 */

export interface B2bPerson {
  id: number;
  name: string;
}

export interface B2bSheet {
  id: number;
  title: string;
  note: string;
  assigned_to: B2bPerson | null;
  created_by: B2bPerson | null;
  created_at: string;
  rows: number;
  contacted: number;
  can_manage: boolean;
  can_contact: boolean;
}

/** The columns a row is typed or pasted in, in the order the server reads a pasted block. */
export type B2bColumn =
  | "company_name"
  | "country"
  | "website"
  | "industry"
  | "contact_person"
  | "position"
  | "email"
  | "phone"
  | "whatsapp"
  | "linkedin"
  | "languages"
  | "services"
  | "source";

export type B2bRow = Record<B2bColumn, string>;

export interface B2bLead extends B2bRow {
  id: number;
  status: string;
  next_follow_up: string;
  notes: string;
  client_code: string;
  whatsapp_at: string;
  email_at: string;
  call_at: string;
  last_contact_at: string;
  /** The first time the company answered on the Sales person's line. */
  replied_at: string;
  /** The last time the Sales person reached out (a message or a call): what makes a follow-up done. */
  last_outreach_at: string;
  /** Where the next follow-up stands (`b2b.follow_up_state`): none, coming, due today, late, or done. */
  follow_up: FollowUpState;
  overdue: boolean;
}

export type FollowUpState = "" | "upcoming" | "today" | "overdue" | "done";

/** A follow-up on the list of the day: the row, and the sheet and the Sales person it is with. */
export interface B2bFollowUp extends B2bLead {
  sheet: { id: number; title: string };
  sales: B2bPerson | null;
}

export interface B2bFollowUpsResponse {
  ok: boolean;
  today: string;
  items: B2bFollowUp[];
}

export interface B2bActivity {
  id: number;
  kind: "whatsapp" | "email" | "call" | "status";
  automatic: boolean;
  /** The company's own message to us, not ours to them. */
  incoming: boolean;
  /** A stage change: the stage the company moved to. */
  status: string;
  at: string;
  by: B2bPerson | null;
  outcome: string;
  duration_minutes: number | null;
  notes: string;
}

export interface B2bChoice {
  value: string;
  label: string;
}

export interface B2bSheetsResponse {
  ok: boolean;
  can_manage: boolean;
  sales: B2bPerson[];
  sheets: B2bSheet[];
}

export interface B2bSheetResponse {
  ok: boolean;
  sheet: B2bSheet;
  sales: B2bPerson[];
  /** The other sheets a company may be moved to (the manager's only; empty for anybody else). */
  sheets: { id: number; title: string; assigned_to: B2bPerson | null }[];
  leads: B2bLead[];
  columns: { name: B2bColumn; ar: string; en: string; max: number }[];
  statuses: B2bChoice[];
  outcomes: B2bChoice[];
}

export interface B2bLeadResponse {
  ok: boolean;
  lead: B2bLead;
  activities: B2bActivity[];
  can_contact: boolean;
}

/** The reason a refusal gave, in the page's language, or `fallback`. */
export function refusalText(failure: unknown, lang: string, fallback: string): string {
  if (failure instanceof ApiError && failure.payload && typeof failure.payload === "object") {
    const { message, message_en } = failure.payload as { message?: unknown; message_en?: unknown };
    const words = lang === "en" ? message_en : message;
    if (typeof words === "string" && words) return words;
  }
  return fallback;
}

export function useB2bSheets(enabled = true) {
  return useQuery({
    queryKey: qk.b2bSheets,
    queryFn: () => api<B2bSheetsResponse>("/api/v1/b2b/sheets/"),
    enabled,
  });
}

export function useB2bSheet(id: number) {
  return useQuery({
    queryKey: qk.b2bSheet(id),
    queryFn: () => api<B2bSheetResponse>(`/api/v1/b2b/sheets/${id}/`),
    enabled: id > 0,
  });
}

export function useB2bLead(id: number) {
  return useQuery({
    queryKey: qk.b2bLead(id),
    queryFn: () => api<B2bLeadResponse>(`/api/v1/b2b/leads/${id}/`),
    enabled: id > 0,
  });
}

/** The follow-ups due today or late: one's own, or the team's for the manager. */
export function useB2bFollowUps(enabled = true) {
  return useQuery({
    queryKey: qk.b2bFollowUps,
    queryFn: () => api<B2bFollowUpsResponse>("/api/v1/b2b/follow-ups/"),
    enabled,
  });
}

/** The counts of one Sales person's row (or the team's total): a zero is a real zero. */
export interface KpiCounts {
  new_leads: number;
  contacted: number;
  whatsapp: number;
  emails: number;
  calls: number;
  replies: number;
  meetings: number;
  proposals: number;
  won: number;
  lost: number;
  follow_ups_on_time: number;
  follow_ups_late: number;
  follow_ups_missed: number;
  overdue_now: number;
  holding: number;
  untouched: number;
  /** Percentages, `null` when there is nothing to divide by: "not measured", never 0%. */
  conversion_rate: number | null;
  follow_up_rate: number | null;
}

export interface KpiRow extends KpiCounts {
  person: { id: number; name: string; active: boolean };
}

export interface KpiResponse {
  ok: boolean;
  from: string;
  to: string;
  /** The manager's (and the owner's) answer: every Sales person, and the team's total. */
  team: boolean;
  rows: KpiRow[];
  total: KpiCounts;
}

/** The Sales numbers for the days `from`..`to` (both included; empty = this month so far). */
export function useB2bKpis(from: string, to: string, enabled = true) {
  const query = new URLSearchParams();
  if (from) query.set("from", from);
  if (to) query.set("to", to);
  const search = query.toString();
  return useQuery({
    queryKey: qk.b2bKpis(from, to),
    queryFn: () => api<KpiResponse>(`/api/v1/b2b/kpis/${search ? `?${search}` : ""}`),
    enabled,
  });
}

/** Every write: the door, then the sheets asked again (a row's marks, a sheet's counts). */
function useWrite<V, R>(run: (values: V) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSettled: () => void client.invalidateQueries({ queryKey: qk.b2b }),
  });
}

export interface SheetValues {
  title: string;
  note: string;
  assigned_to: number;
}

export function useCreateSheet() {
  return useWrite((values: SheetValues) => api<{ ok: boolean; sheet: B2bSheet }>("/api/v1/b2b/sheets/new/", { json: values }));
}

export function useSaveSheet(id: number) {
  return useWrite((values: SheetValues) => api<{ ok: boolean; sheet: B2bSheet }>(`/api/v1/b2b/sheets/${id}/save/`, { json: values }));
}

export function useDeleteSheet(id: number) {
  return useWrite(() => api<{ ok: boolean }>(`/api/v1/b2b/sheets/${id}/delete/`, { json: {} }));
}

export function useAddRows(sheetId: number) {
  return useWrite((rows: Partial<B2bRow>[]) =>
    api<{ ok: boolean; added: number; leads: B2bLead[] }>(`/api/v1/b2b/sheets/${sheetId}/rows/`, { json: { rows } }),
  );
}

export type LeadValues = B2bRow & { status: string; next_follow_up: string; notes: string };

export function useSaveLead() {
  return useWrite(({ id, values }: { id: number; values: LeadValues }) =>
    api<{ ok: boolean; lead: B2bLead }>(`/api/v1/b2b/leads/${id}/save/`, { json: values }),
  );
}

export function useMoveLead() {
  return useWrite(({ id, sheet }: { id: number; sheet: number }) =>
    api<{ ok: boolean; lead: B2bLead }>(`/api/v1/b2b/leads/${id}/move/`, { json: { sheet } }),
  );
}

export function useDeleteLead() {
  return useWrite((id: number) => api<{ ok: boolean }>(`/api/v1/b2b/leads/${id}/delete/`, { json: {} }));
}

export function useLeadWhatsapp() {
  return useWrite((id: number) =>
    api<{ ok: boolean; sent: boolean; chat: string; lead: B2bLead }>(`/api/v1/b2b/leads/${id}/whatsapp/`, { json: {} }),
  );
}

export function useLeadEmail() {
  return useWrite(({ id, subject, body }: { id: number; subject: string; body: string }) =>
    api<{ ok: boolean; lead: B2bLead }>(`/api/v1/b2b/leads/${id}/email/`, { json: { subject, body } }),
  );
}

export interface CallValues {
  outcome: string;
  notes: string;
  duration_minutes: number | null;
  at: string;
  next_follow_up: string;
}

export function useLeadCall() {
  return useWrite(({ id, values }: { id: number; values: CallValues }) =>
    api<{ ok: boolean; lead: B2bLead }>(`/api/v1/b2b/leads/${id}/call/`, { json: values }),
  );
}

/**
 * Cells copied from Google Sheets or Excel arrive as lines of tab-separated values. Each line is a row, read in `columns`'
 * order; a first line that names the columns (in Arabic or English) is the header and is left out. Empty lines are skipped.
 */
export function parsePasted(text: string, columns: { name: B2bColumn; ar: string; en: string; max: number }[]): Partial<B2bRow>[] {
  const lines = text.replace(/\r\n?/g, "\n").split("\n").filter((line) => line.trim() !== "");
  const names = new Set(columns.flatMap((column) => [column.ar.trim().toLowerCase(), column.en.trim().toLowerCase()]));
  if (lines.length > 0) {
    const first = (lines[0] ?? "").split("\t")[0]?.trim().toLowerCase() ?? "";
    if (names.has(first)) lines.shift();
  }
  return lines.map((line) => {
    const cells = line.split("\t");
    const row: Partial<B2bRow> = {};
    columns.forEach((column, index) => {
      row[column.name] = (cells[index] ?? "").trim().slice(0, column.max);
    });
    return row;
  });
}
