import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { qk } from "./keys";

/**
 * The Sales commissions, per deal (`/api/v1/commissions/`, `dashboard/commissions.py`; per deal since 21/10/2026). A
 * company moved to «تم التعاقد» is a deal here by itself, with its details; the owner corrects its value, links its invoice,
 * and gives each person on it their own percent; a line is approved once the deal's invoice is paid in full, then marked
 * paid. A Sales person reads their own lines, a manager their team's. Every rule is the server's: the page draws
 * `can_manage` and each deal's `stage` and `paid`.
 */

export type CommissionStatus = "pending" | "approved" | "paid" | "cancelled";
export type DealStage = "waiting" | "due" | "approved" | "paid" | "cancelled";

export interface CommissionInvoice {
  id: number;
  code: string;
  status: string;
  amount: string;
  currency: string;
  client_code: string;
}

export interface DealQuotation {
  code: string;
  status: string;
  service: string;
  unit: string;
  quantity: number;
  rate: string;
  discount: string;
  total: string;
  currency: string;
  source_lang: string;
  target_lang: string;
  deadline: string;
  payment_terms: string;
}

export interface DealCompany {
  name: string;
  sheet: string;
  contact_person?: string;
  position?: string;
  country?: string;
  governorate?: string;
  industry?: string;
  services?: string;
  languages?: string;
  source?: string;
  customer_type?: string;
  /** The «deal value» written on the sheet's row. */
  sheet_value?: string | null;
}

export interface CommissionLine {
  id: number;
  code: string;
  person: { id: number; name: string };
  /** This person's percent of the deal's value ("5.00"), null when none is set yet. */
  rate: string | null;
  /** The rate is this line's own (not the person's nor the company's). */
  own_rate: boolean;
  status: CommissionStatus;
  amount: string | null;
  currency: string;
  amount_egp: string | null;
  approved_by: { id: number; name: string } | null;
  approved_at: string;
  paid_at: string;
  note: string;
}

export interface Deal {
  id: number;
  code: string;
  market: string;
  status: "open" | "cancelled";
  stage: DealStage;
  company: DealCompany;
  client_code: string;
  owner: { id: number; name: string } | null;
  won_at: string;
  won_by: { id: number; name: string } | null;
  value: string | null;
  currency: string;
  value_by_hand: boolean;
  egp_rate: string | null;
  quotation: DealQuotation | null;
  invoice: CommissionInvoice | null;
  /** The client paid the deal's invoice in full: its lines may be approved and paid. */
  paid: boolean;
  note: string;
  lines: CommissionLine[];
}

export interface CommissionsResponse {
  ok: boolean;
  can_manage: boolean;
  deals: Deal[];
  /** In EGP: waiting for the client, due, approved, paid; `unknown` lines whose EGP figure cannot be known yet. */
  totals: { waiting: string; due: string; approved: string; paid: string; unknown: number };
  currencies: string[];
  company_rate: string | null;
  people: { id: number; name: string; rate: string | null; track: string }[];
  /** Invoices on no deal: the owner links one to its deal or makes a deal of it. */
  uncovered: CommissionInvoice[];
}

export interface DealChanges {
  value?: string;
  currency?: string;
  invoice?: number | null;
  people?: { person: number; rate: string }[];
  note?: string;
}

export function useCommissions(stage: string, enabled = true) {
  return useQuery({
    queryKey: qk.commissions(stage),
    queryFn: () => api<CommissionsResponse>(`/api/v1/commissions/${stage ? `?stage=${stage}` : ""}`),
    enabled,
  });
}

function useWrite<V, R>(run: (values: V) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({ mutationFn: run, onSettled: () => void client.invalidateQueries({ queryKey: qk.commissionsAll }) });
}

export const useCompanyRate = () => useWrite((rate: string) => api<{ ok: boolean }>("/api/v1/commissions/rate/", { json: { rate } }));
export const usePersonRate = () =>
  useWrite(({ id, rate }: { id: number; rate: string }) => api<{ ok: boolean }>(`/api/v1/commissions/people/${id}/rate/`, { json: { rate } }));
export const useSetDeal = () =>
  useWrite(({ id, changes }: { id: number; changes: DealChanges }) => api<{ ok: boolean; deal: Deal }>(`/api/v1/commissions/deals/${id}/`, { json: changes }));
export const useCancelDeal = () => useWrite((id: number) => api<{ ok: boolean }>(`/api/v1/commissions/deals/${id}/cancel/`, { json: {} }));
export const useDealOfInvoice = () => useWrite((id: number) => api<{ ok: boolean; deal: Deal }>(`/api/v1/commissions/invoices/${id}/deal/`, { json: {} }));
export const useApprove = () => useWrite((id: number) => api<{ ok: boolean }>(`/api/v1/commissions/${id}/approve/`, { json: {} }));
export const usePaid = () => useWrite((id: number) => api<{ ok: boolean }>(`/api/v1/commissions/${id}/paid/`, { json: {} }));
export const useTakeBack = () => useWrite((id: number) => api<{ ok: boolean }>(`/api/v1/commissions/${id}/take-back/`, { json: {} }));
