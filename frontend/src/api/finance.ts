import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { qk } from "./keys";

/**
 * Client invoices, payments and project costs (`/api/v1/finance/`, `dashboard/api_finance.py`): Accounting's and the owner's.
 * The rules are the server's (`finance.py`); the page draws what the answer says. Amounts come as strings to the cent
 * ("80.00"), and a figure that cannot be known yet (no exchange rate, a cost not priced) comes as `null`: "not measured".
 */

export type InvoiceStatus = "draft" | "sent" | "partial" | "paid" | "cancelled";

export interface InvoiceRow {
  id: number;
  code: string;
  client_code: string;
  task: string;
  quotation: string;
  amount: string;
  paid: string;
  left: string;
  currency: string;
  status: InvoiceStatus;
  overdue: boolean;
  issue_date: string;
  due_date: string;
  sent_at: string;
  sales: string;
}

export interface InvoiceCost {
  id: number;
  kind: string;
  person: string;
  description: string;
  words: number | null;
  rate_per_250: string | null;
  amount: string | null;
  automatic: boolean;
}

export interface InvoiceDetail extends InvoiceRow {
  /** The client's code; the name and the address only for who may see the client's identity. */
  client: { code: string; name?: string; company?: string; email?: string };
  egp_rate: string;
  payment_terms: string;
  notes: string;
  payments: { id: number; amount: string; paid_on: string; method: string; note: string; by: string }[];
  costs: InvoiceCost[];
  profit: { price_egp: string | null; costs: string | null; profit: string | null; margin: number | null; currency: string };
}

export interface InvoicesResponse {
  ok: boolean;
  show: string;
  invoices: InvoiceRow[];
  /** What is still owed, per currency. */
  owed: Record<string, string>;
  /** Delivered tasks with no invoice: what may still be invoiced by hand. */
  uninvoiced: { code: string; client_code: string; title: string; delivered_at: string; words: number }[];
  currencies: string[];
}

export interface InvoiceResponse {
  ok: boolean;
  invoice: InvoiceDetail;
  cost_kinds: { value: string; label: string }[];
  currencies: string[];
}

export function useInvoices(show: string, enabled = true) {
  return useQuery({
    queryKey: qk.invoices(show),
    // "all" is the plain address: the one the menu warms ahead of a click.
    queryFn: () => api<InvoicesResponse>(show === "all" ? "/api/v1/finance/invoices/" : `/api/v1/finance/invoices/?show=${encodeURIComponent(show)}`),
    enabled,
  });
}

export function useInvoice(id: number) {
  return useQuery({
    queryKey: qk.invoice(id),
    queryFn: () => api<InvoiceResponse>(`/api/v1/finance/invoices/${id}/`),
    enabled: id > 0,
  });
}

/** Every write: the door, then everything about invoices asked again (the list's totals move with any of them). */
function useWrite<V, R>(run: (values: V) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSettled: () => void client.invalidateQueries({ queryKey: qk.finance }),
  });
}

type Answer = { ok: boolean; invoice: InvoiceDetail };

export interface InvoiceValues {
  amount: string;
  currency: string;
  egp_rate: string;
  due_date: string;
  payment_terms: string;
  notes: string;
}

export function useSaveInvoice(id: number) {
  return useWrite((values: InvoiceValues) => api<Answer>(`/api/v1/finance/invoices/${id}/save/`, { json: values }));
}

/** Send or cancel an invoice: one door each. */
export function useInvoiceAction(id: number) {
  return useWrite((action: "send" | "cancel") => api<Answer>(`/api/v1/finance/invoices/${id}/${action}/`, { json: {} }));
}

export function useAddPayment(id: number) {
  return useWrite((values: { amount: string; paid_on: string; method: string; note: string }) =>
    api<Answer>(`/api/v1/finance/invoices/${id}/payments/`, { json: values }),
  );
}

export function useDeletePayment() {
  return useWrite((paymentId: number) => api<Answer>(`/api/v1/finance/payments/${paymentId}/delete/`, { json: {} }));
}

export function useAddCost(id: number) {
  return useWrite((values: { kind: string; amount: string; description: string }) =>
    api<Answer>(`/api/v1/finance/invoices/${id}/costs/`, { json: values }),
  );
}

export function useSaveCost() {
  return useWrite(({ costId, amount, description }: { costId: number; amount: string; description: string }) =>
    api<Answer>(`/api/v1/finance/costs/${costId}/save/`, { json: { amount, description } }),
  );
}

export function useDeleteCost() {
  return useWrite((costId: number) => api<Answer>(`/api/v1/finance/costs/${costId}/delete/`, { json: {} }));
}

/** Invoice a delivered task by hand (one with no quotation behind it). */
export function useInvoiceTask() {
  return useWrite(({ code, amount, currency }: { code: string; amount: string; currency: string }) =>
    api<Answer>(`/api/v1/finance/tasks/${encodeURIComponent(code)}/invoice/`, { json: { amount, currency } }),
  );
}
