import { useQuery } from "@tanstack/react-query";
import type { KpiCounts, KpiRow } from "./b2b";
import { api } from "./client";
import { qk } from "./keys";

/**
 * The CEO board (`/api/v1/admin/ceo/`, `dashboard/ceo.py`): the owner's. Money per currency is never added across
 * currencies; an EGP figure, a rate or a score that cannot be known comes as `null` ("not measured").
 */

export type PerCurrency = Record<string, string>;

export interface CeoBoard {
  ok: boolean;
  from: string;
  to: string;
  sales: {
    today: { won: number; won_value: PerCurrency };
    period: KpiCounts;
    people: KpiRow[];
  };
  projects: {
    active: number;
    late: number;
    delivered: number;
    words_delivered: number;
    rework_rate: number | null;
    review_score: number | null;
    complaints: number;
    complaints_open: number;
  };
  workload: { translators: { id: number; name: string; tasks: number; words: number }[]; free: number };
  money: {
    invoiced: PerCurrency;
    received: PerCurrency;
    owed: PerCurrency;
    overdue: PerCurrency;
    overdue_count: number;
    drafts: number;
    revenue_egp: string | null;
    costs_egp: string | null;
    profit_egp: string | null;
    margin: number | null;
    invoices: number;
  };
  by_project: {
    invoice: string;
    invoice_id: number;
    task: string;
    client: string;
    amount: string;
    currency: string;
    price_egp: string | null;
    profit_egp: string | null;
    margin: number | null;
  }[];
  by_client: { code: string; name?: string; invoices: number; invoiced: PerCurrency; revenue_egp: string | null; profit_egp: string | null }[];
}

export function useCeoBoard(from: string, to: string, enabled = true) {
  const query = new URLSearchParams();
  if (from) query.set("from", from);
  if (to) query.set("to", to);
  const search = query.toString();
  return useQuery({
    queryKey: qk.ceo(from, to),
    queryFn: () => api<CeoBoard>(`/api/v1/admin/ceo/${search ? `?${search}` : ""}`),
    enabled,
  });
}
