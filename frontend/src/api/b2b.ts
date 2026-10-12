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
  /** "high", "medium", "low" or "" (none marked). */
  priority: string;
  /** What the deal is worth, as the Sales person guesses it ("1500", "1500.5"), "" when none: no currency, as on the team's sheet. */
  deal_value: string;
  /** Every number the company has (the WhatsApp ones first, then the phone cell's, one a line): what a message may go to. */
  phones: string[];
  next_follow_up: string;
  /** Every note, the oldest first, each with the day it was written and who wrote it. */
  notes: B2bNote[];
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
  /** The row's newest quotation, in a word. */
  quote: { code: string; status: QuotationStatus; total: string; currency: string } | null;
}

export interface B2bNote {
  id: number;
  text: string;
  /** When it was written ("12/10/2026 5:20 PM"), and the day alone ("12/10/2026"). */
  at: string;
  day: string;
  by: B2bPerson | null;
}

export type QuotationStatus = "draft" | "sent" | "accepted" | "rejected";

export interface Quotation {
  id: number;
  code: string;
  status: QuotationStatus;
  source_lang: string;
  target_lang: string;
  service: string;
  unit: string;
  quantity: number;
  rate: string;
  discount_percent: string;
  total: string;
  currency: string;
  deadline: string;
  payment_terms: string;
  notes: string;
  created_at: string;
  sent_at: string;
  decided_at: string;
  /** The task the operation made from it, once accepted. */
  task: string;
  /** Where its invoice stands (Accounting's): never the costs nor the profit. */
  invoice: { code: string; status: string; overdue: boolean; amount: string; paid: string; currency: string } | null;
}

export interface QuotationsResponse {
  ok: boolean;
  lead: { id: number; company_name: string; contact_person: string; email: string };
  quotations: Quotation[];
  can_make: boolean;
  can_decide: boolean;
  services: B2bChoice[];
  units: B2bChoice[];
  currencies: string[];
  languages: { code: string; ar: string; en: string }[];
}

/** What a quotation form posts. */
export interface QuotationValues {
  source_lang: string;
  target_lang: string;
  service: string;
  unit: string;
  quantity: number;
  rate: string;
  discount_percent: string;
  currency: string;
  deadline: string;
  payment_terms: string;
  notes: string;
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
  kind: "whatsapp" | "email" | "call" | "status" | "quotation";
  automatic: boolean;
  /** The company's own message to us, not ours to them. */
  incoming: boolean;
  /** A stage change: the stage the company moved to. */
  status: string;
  /** A quotation line: which one (`notes` says what happened to it: created, sent, accepted, rejected). */
  quotation: string;
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
  priorities: B2bChoice[];
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
  visits: number;
  won: number;
  lost: number;
  follow_ups_on_time: number;
  follow_ups_late: number;
  follow_ups_missed: number;
  overdue_now: number;
  holding: number;
  untouched: number;
  quotations: number;
  quotes_accepted: number;
  /** The accepted quotations' totals, per currency ("USD" -> "72.00"): never added across currencies. */
  revenue: Record<string, string>;
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

/** Delete any sheet by its id: the list's own button (one hook for every row). */
export function useDeleteAnySheet() {
  return useWrite((id: number) => api<{ ok: boolean }>(`/api/v1/b2b/sheets/${id}/delete/`, { json: {} }));
}

export function useDeleteSheet(id: number) {
  return useWrite(() => api<{ ok: boolean }>(`/api/v1/b2b/sheets/${id}/delete/`, { json: {} }));
}

export function useAddRows(sheetId: number) {
  return useWrite((rows: (Partial<LeadValues> & { notes?: string })[]) =>
    api<{ ok: boolean; added: number; leads: B2bLead[] }>(`/api/v1/b2b/sheets/${sheetId}/rows/`, { json: { rows } }),
  );
}

export type LeadValues = B2bRow & { status: string; priority: string; deal_value: string; next_follow_up: string };

export function useSaveLead() {
  return useWrite(({ id, values }: { id: number; values: LeadValues }) =>
    api<{ ok: boolean; lead: B2bLead }>(`/api/v1/b2b/leads/${id}/save/`, { json: values }),
  );
}

/** One cell edited on the sheet: only what is sent changes, so two people on one sheet do not write over each other. */
export function useSaveCell() {
  return useWrite(({ id, values }: { id: number; values: Partial<LeadValues> }) =>
    api<{ ok: boolean; lead: B2bLead }>(`/api/v1/b2b/leads/${id}/save/`, { json: values }),
  );
}

/** A note on the company, dated now and signed by the server. */
export function useAddNote() {
  return useWrite(({ id, text }: { id: number; text: string }) =>
    api<{ ok: boolean; lead: B2bLead }>(`/api/v1/b2b/leads/${id}/notes/`, { json: { text } }),
  );
}

export function useDeleteNote() {
  return useWrite((id: number) => api<{ ok: boolean; lead: B2bLead }>(`/api/v1/b2b/notes/${id}/delete/`, { json: {} }));
}

/** A message written on the sheet, by WhatsApp to one of the company's numbers or by e-mail; the row is marked by itself. */
export function useSendMessage() {
  return useWrite((values: { id: number; channel: "whatsapp" | "email"; to: string; subject: string; body: string }) => {
    const { id, ...rest } = values;
    return api<{ ok: boolean; chat: string; lead: B2bLead }>(`/api/v1/b2b/leads/${id}/send/`, { json: rest });
  });
}

/** The short code of a refusal (`window_closed`, `not_yours`...), or "". */
export function refusalCode(failure: unknown): string {
  if (failure instanceof ApiError && failure.payload && typeof failure.payload === "object") {
    const { error } = failure.payload as { error?: unknown };
    if (typeof error === "string") return error;
  }
  return "";
}

export function useMoveLead() {
  return useWrite(({ id, sheet }: { id: number; sheet: number }) =>
    api<{ ok: boolean; lead: B2bLead }>(`/api/v1/b2b/leads/${id}/move/`, { json: { sheet } }),
  );
}

export function useQuotations(leadId: number) {
  return useQuery({
    queryKey: qk.b2bQuotes(leadId),
    queryFn: () => api<QuotationsResponse>(`/api/v1/b2b/leads/${leadId}/quotations/`),
    enabled: leadId > 0,
  });
}

type QuoteAnswer = { ok: boolean; quotation: Quotation };

export function useCreateQuotation(leadId: number) {
  return useWrite((values: QuotationValues) => api<QuoteAnswer>(`/api/v1/b2b/leads/${leadId}/quotations/new/`, { json: values }));
}

export function useSaveQuotation() {
  return useWrite(({ id, values }: { id: number; values: QuotationValues }) =>
    api<QuoteAnswer>(`/api/v1/b2b/quotations/${id}/save/`, { json: values }),
  );
}

/** Send, copy or delete a quotation, or write down the company's answer: one door each, the quotation's id in the address. */
export function useQuotationAction() {
  return useWrite(({ id, action, accepted }: { id: number; action: "send" | "copy" | "delete" | "decide"; accepted?: boolean }) =>
    api<QuoteAnswer>(`/api/v1/b2b/quotations/${id}/${action}/`, { json: action === "decide" ? { accepted } : {} }),
  );
}

export function useDeleteLead() {
  return useWrite((id: number) => api<{ ok: boolean }>(`/api/v1/b2b/leads/${id}/delete/`, { json: {} }));
}

export function useLeadWhatsapp() {
  return useWrite(({ id, number }: { id: number; number: string }) =>
    api<{ ok: boolean; sent: boolean; chat: string; lead: B2bLead }>(`/api/v1/b2b/leads/${id}/whatsapp/`, { json: { number } }),
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

/** What reading a file or pasted cells answered: the rows (to correct before adding), and which header each column came from. */
export interface ReadRowsResponse {
  ok: boolean;
  rows: B2bRow[];
  mapped: Partial<Record<B2bColumn, string>>;
  /** The file had more rows than one go takes: the rest is in another upload. */
  more: boolean;
}

/** Read an Excel / CSV file, or pasted cells, into rows - nothing is written (`/sheets/<id>/read/`). */
export function useReadRows(sheetId: number) {
  return useMutation({
    mutationFn: (source: { file: File } | { text: string } | { link: string }) => {
      if ("file" in source) {
        const form = new FormData();
        form.append("file", source.file);
        return api<ReadRowsResponse>(`/api/v1/b2b/sheets/${sheetId}/read/`, { multipart: form });
      }
      // A Google Sheets link: the server reads that sheet itself (it must be open to anyone with the link).
      if ("link" in source) return api<ReadRowsResponse>(`/api/v1/b2b/sheets/${sheetId}/read/`, { json: { link: source.link } });
      return api<ReadRowsResponse>(`/api/v1/b2b/sheets/${sheetId}/read/`, { json: { text: source.text } });
    },
  });
}

/** The figures a Sales target may set (part 7). */
export type TargetMetric = "new_leads" | "contacted" | "quotations" | "won" | "revenue";

export interface TargetProgress {
  /** The target (a count, or the revenue as "100.00"); `null` = no target for it. */
  target: number | string | null;
  done: number | string;
  /** `null` with no target: not measured, never 0%. */
  percent: number | null;
}

export interface TargetRow {
  person: { id: number; name: string };
  currency: string;
  progress: Record<TargetMetric, TargetProgress>;
}

export interface TargetsResponse {
  ok: boolean;
  month: string;
  can_edit: boolean;
  metrics: TargetMetric[];
  currencies: string[];
  rows: TargetRow[];
}

/** The targets of a month (`YYYY-MM`; empty = this month) and how far each person is. */
export function useTargets(month: string, enabled = true) {
  return useQuery({
    queryKey: qk.b2bTargets(month),
    queryFn: () => api<TargetsResponse>(`/api/v1/b2b/targets/${month ? `?month=${encodeURIComponent(month)}` : ""}`),
    enabled,
  });
}

export interface TargetValues {
  person: number;
  month: string;
  new_leads: number | null;
  contacted: number | null;
  quotations: number | null;
  won: number | null;
  revenue: string | null;
  revenue_currency: string;
}

export function useSaveTarget() {
  return useWrite((values: TargetValues) => api<{ ok: boolean; rows: TargetRow[] }>("/api/v1/b2b/targets/save/", { json: values }));
}
