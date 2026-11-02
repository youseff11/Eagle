import { useQuery } from "@tanstack/react-query";
import { api } from "./client";
import { qk } from "./keys";

/**
 * «سجل الدفع» (`/api/v1/admin/usage/months/`, `dashboard/usage_history.py`): the admin's. What each host's bill came to, month
 * by month, this month's running figures on top. A figure that cannot be known is `null` ("not measured"), never a zero.
 */

export type UsageMonthState = "ok" | "off" | "error" | "unknown";

export interface UsageMonthCell {
  state: UsageMonthState;
  /** In dollars; `null` when not measured, failed, not linked or in another currency. */
  usd: number | null;
  /** The figure when it is not in dollars (Meta bills in the account's currency): shown, not in the total. */
  amount: string;
  estimate: boolean;
  note: { ar: string; en: string } | null;
  error: string;
}

export interface UsageMonthRow {
  /** `2026-10`. */
  month: string;
  label: { ar: string; en: string };
  /** This month: the figures so far, as the usage panel last read them. */
  running: boolean;
  closed: boolean;
  cells: Record<string, UsageMonthCell>;
  /** Of the dollar figures; `null` when none is known. */
  total_usd: number | null;
  /** False when a linked host is missing from the total. */
  complete: boolean;
  estimate: boolean;
  at: { ar: string; en: string } | null;
}

export interface UsageMonths {
  ok: true;
  hosts: { key: string; name: string; link: string }[];
  months: UsageMonthRow[];
}

export function useUsageMonths(enabled = true) {
  return useQuery({
    queryKey: qk.adminUsageMonths,
    queryFn: () => api<UsageMonths>("/api/v1/admin/usage/months/"),
    enabled,
  });
}
