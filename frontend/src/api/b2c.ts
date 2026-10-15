import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { qk } from "./keys";
import type { B2bChoice, B2bPerson } from "./b2b";

/**
 * The B2C field visits (`/api/v1/b2c/`, `dashboard/api_b2c.py`). A field Sales person plans a visit to a company on their
 * sheet, presses «وصلت» at the company and «خلصت» on leaving: each press reads the phone's place once, at the press, and
 * the server measures how far it is from the company. The Sales manager then verifies the visit or turns it down. Who may
 * do what is the server's (`b2c.py`): the page draws what each visit says (`can_decide`, `can_escalate`, `mine`).
 */

export type VisitStatus = "planned" | "checked_in" | "pending" | "verified" | "rejected";

export interface Visit {
  id: number;
  code: string;
  status: VisitStatus;
  lead: { id: number; company_name: string; governorate: string; address: string; sheet: number; has_place: boolean; map_link: string };
  person: B2bPerson | null;
  planned_at: string;
  planned_day: string;
  purpose: string;
  check_in_at: string;
  /** Metres from the company at «وصلت», `null` when the company has no place or the phone gave none. */
  check_in_distance: number | null;
  check_in_accuracy: number | null;
  check_in_map: string;
  check_out_at: string;
  check_out_distance: number | null;
  check_out_accuracy: number | null;
  check_out_map: string;
  minutes: number | null;
  no_location_reason: string;
  outcome: string;
  met: string;
  interest: string;
  summary: string;
  next_step: string;
  next_step_on: string;
  /** What the manager has to look at (`b2c.FLAGS`). */
  flags: string[];
  escalated: boolean;
  escalation_note: string;
  decided_by: B2bPerson | null;
  decided_at: string;
  decision_note: string;
  mine: boolean;
  can_decide: boolean;
  can_escalate: boolean;
  /** The person's objection to a turned-down visit (once), what the first decision said, and whether they may object now. */
  appeal_note: string;
  appealed_from: string;
  appealed_at: string;
  can_appeal: boolean;
}

export interface VisitBoardRow {
  person: { id: number; name: string; active: boolean };
  target: number;
  leave_days: number;
  planned: number;
  open: number;
  pending: number;
  verified: number;
  rejected: number;
  submitted: number;
  remaining: number;
  /** Percentages, `null` when there is nothing to divide by: "not measured", never 0%. */
  achievement: number | null;
  verification_rate: number | null;
}

export interface VisitsResponse {
  ok: boolean;
  month: string;
  can_manage: boolean;
  field: boolean;
  rules: { target: number; work_days: number; radius_m: number; accuracy_m: number };
  board: VisitBoardRow[];
  visits: Visit[];
  outcomes: B2bChoice[];
  interests: B2bChoice[];
  flags: { value: string; ar: string; en: string }[];
}

export interface VisitLead {
  id: number;
  company_name: string;
  governorate: string;
  address: string;
  has_place: boolean;
  person: B2bPerson | null;
}

export function useVisits(month: string, enabled = true) {
  return useQuery({
    queryKey: qk.b2cVisits(month),
    queryFn: () => api<VisitsResponse>(`/api/v1/b2c/visits/${month ? `?month=${month}` : ""}`),
    enabled,
  });
}

/** The companies a visit may be to, by what was typed (nothing is asked for until the box is opened). */
export function useVisitLeads(words: string, enabled: boolean) {
  return useQuery({
    queryKey: qk.b2cVisitLeads(words),
    queryFn: () => api<{ ok: boolean; items: VisitLead[] }>(`/api/v1/b2c/leads/?q=${encodeURIComponent(words)}`),
    enabled,
  });
}

/** Every write asks the visits and the sheets again: a visit's report moves its company's row (the next follow-up). */
function useVisitWrite<V, R>(run: (values: V) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSettled: () => void client.invalidateQueries({ queryKey: qk.b2b }),
  });
}

export function usePlanVisit() {
  return useVisitWrite((values: { lead: number; planned_at: string; purpose: string }) =>
    api<{ ok: boolean; visit: Visit }>("/api/v1/b2c/visits/new/", { json: values }),
  );
}

/** The phone's place at one press, or the reason there is none. */
export type Press = { lat: number; lng: number; accuracy: number } | { reason: string };

export function useCheckIn() {
  return useVisitWrite(({ id, press }: { id: number; press: Press }) =>
    api<{ ok: boolean; visit: Visit }>(`/api/v1/b2c/visits/${id}/check-in/`, { json: press }),
  );
}

export interface VisitReport {
  outcome: string;
  met: string;
  interest: string;
  summary: string;
  next_step: string;
  next_step_on: string;
}

export function useCheckOut() {
  return useVisitWrite(({ id, press, report }: { id: number; press: Press; report: VisitReport }) =>
    api<{ ok: boolean; visit: Visit }>(`/api/v1/b2c/visits/${id}/check-out/`, { json: { ...press, ...report } }),
  );
}

export function useCancelVisit() {
  return useVisitWrite((id: number) => api<{ ok: boolean }>(`/api/v1/b2c/visits/${id}/cancel/`, { json: {} }));
}

export function useDecideVisit() {
  return useVisitWrite(({ id, verified, note }: { id: number; verified: boolean; note: string }) =>
    api<{ ok: boolean; visit: Visit }>(`/api/v1/b2c/visits/${id}/decide/`, { json: { verified, note } }),
  );
}

export function useEscalateVisit() {
  return useVisitWrite(({ id, note }: { id: number; note: string }) =>
    api<{ ok: boolean; visit: Visit }>(`/api/v1/b2c/visits/${id}/escalate/`, { json: { note } }),
  );
}

export function useAppealVisit() {
  return useVisitWrite(({ id, note }: { id: number; note: string }) =>
    api<{ ok: boolean; visit: Visit }>(`/api/v1/b2c/visits/${id}/appeal/`, { json: { note } }),
  );
}

export function useVerifyClean() {
  return useVisitWrite((ids: number[]) => api<{ ok: boolean; verified: number }>("/api/v1/b2c/visits/verify-clean/", { json: { ids } }));
}

/** A rate with what it is made of (the requirements' section 9): `value` is null when there is nothing to divide by. */
export interface BoardRate {
  value: number | null;
  part: number;
  whole: number;
}

export interface BoardCounts {
  new_leads: number;
  contacted: number;
  calls: number;
  messages: number;
  planned: number;
  submitted: number;
  verified: number;
  rejected: number;
  pending: number;
  /** The visits owed for the period (0 for an online person: no visit target). */
  due: number;
  qualified: number;
  qualified_from_visits: number;
  quotations: number;
  quotes_waiting: number;
  won: number;
  lost: number;
  follow_ups_on_time: number;
  follow_ups_late: number;
  follow_ups_missed: number;
  overdue_now: number;
  untouched: number;
  holding: number;
  open_value: string;
  quote_values: Record<string, { total: string; count: number }>;
  visit_achievement: BoardRate;
  verification_rate: BoardRate;
  lead_conversion: BoardRate;
  quotation_conversion: BoardRate;
  win_rate: BoardRate;
  follow_up_compliance: BoardRate;
}

export interface BoardRow extends BoardCounts {
  person: { id: number; name: string; active: boolean; track: string };
  field: boolean;
}

export interface BoardCompany {
  id: number;
  company_name: string;
  sheet: number;
  person: string;
  governorate: string;
  next_follow_up: string;
}

export interface BoardResponse {
  ok: boolean;
  from: string;
  to: string;
  /** The manager's (and the owner's) answer: every B2C Sales person, and the team's total. */
  team: boolean;
  filters: { people: B2bPerson[]; sources: string[]; governorates: string[] };
  rows: BoardRow[];
  total: BoardCounts & { quote_average: Record<string, string> };
  stages: { value: string; count: number }[];
  sources: { value: string; count: number; won: number }[];
  governorates: { value: string; count: number; verified: number }[];
  matrix: { person: BoardRow["person"]; stages: Record<string, number> }[];
  untouched: BoardCompany[];
  overdue: BoardCompany[];
  rejected: { code: string; company_name: string; sheet: number; person: string; note: string; flags: string[] }[];
}

/** The query the board and its export are asked with: the period and the filters, as the page's address holds them. */
export function boardQuery(values: Record<string, string>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) if (value) query.set(key, value);
  const text = query.toString();
  return text ? `?${text}` : "";
}

export function useB2cBoard(values: Record<string, string>, enabled = true) {
  const search = boardQuery(values);
  return useQuery({
    queryKey: qk.b2cBoard(search),
    queryFn: () => api<BoardResponse>(`/api/v1/b2c/board/${search}`),
    enabled,
  });
}
