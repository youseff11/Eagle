import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { qk } from "./keys";

/**
 * The Sales commissions (`/api/v1/commissions/`, `dashboard/commissions.py`). The owner sets the rates, splits a deal,
 * approves a line once its invoice is paid in full, and marks it paid; a Sales person reads their own lines, a manager their
 * team's. Every rule is the server's: the page draws `can_manage` and each line's `due` and `status`.
 */

export type CommissionStatus = "pending" | "approved" | "paid" | "cancelled";

export interface CommissionInvoice {
  id: number;
  code: string;
  status: string;
  amount: string;
  currency: string;
  client_code: string;
}

export interface CommissionLine {
  id: number;
  code: string;
  invoice: CommissionInvoice;
  person: { id: number; name: string };
  share: string;
  /** The rate it is counted at ("5.00"), null when none is set yet. */
  rate: string | null;
  /** The rate is this line's own (not the person's nor the company's). */
  own_rate: boolean;
  status: CommissionStatus;
  amount: string | null;
  currency: string;
  amount_egp: string | null;
  /** The client paid the invoice in full: the line may be approved and paid. */
  due: boolean;
  approved_by: { id: number; name: string } | null;
  approved_at: string;
  paid_at: string;
  note: string;
}

export interface CommissionsResponse {
  ok: boolean;
  can_manage: boolean;
  lines: CommissionLine[];
  /** In EGP: waiting for the client, due, approved, paid; `unknown` lines whose EGP figure cannot be known yet. */
  totals: { waiting: string; due: string; approved: string; paid: string; unknown: number };
  company_rate: string | null;
  people: { id: number; name: string; rate: string | null; track: string }[];
  uncovered: CommissionInvoice[];
}

export function useCommissions(status: string, enabled = true) {
  return useQuery({
    queryKey: qk.commissions(status),
    queryFn: () => api<CommissionsResponse>(`/api/v1/commissions/${status ? `?status=${status}` : ""}`),
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
export const useLineRate = () =>
  useWrite(({ id, rate }: { id: number; rate: string }) => api<{ ok: boolean }>(`/api/v1/commissions/${id}/rate/`, { json: { rate } }));
export const useSplit = () =>
  useWrite(({ invoice, shares }: { invoice: number; shares: { person: number; share: string }[] }) =>
    api<{ ok: boolean }>(`/api/v1/commissions/invoices/${invoice}/split/`, { json: { shares } }),
  );
export const useApprove = () => useWrite((id: number) => api<{ ok: boolean }>(`/api/v1/commissions/${id}/approve/`, { json: {} }));
export const usePaid = () => useWrite((id: number) => api<{ ok: boolean }>(`/api/v1/commissions/${id}/paid/`, { json: {} }));
export const useTakeBack = () => useWrite((id: number) => api<{ ok: boolean }>(`/api/v1/commissions/${id}/take-back/`, { json: {} }));
