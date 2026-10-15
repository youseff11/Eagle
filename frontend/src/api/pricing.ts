import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { qk } from "./keys";
import type { B2bChoice } from "./b2b";

/**
 * The price list and the discount limits (`/api/v1/b2b/price-list/`, `dashboard/pricing.py`). Every Sales person reads the
 * list in force; the owner saves a new version and sets the limits; whoever may approve a waiting discount sees it here.
 */

export interface PriceItem {
  service: string;
  unit: string;
  currency: string;
  /** "EN>AR", or "" for any pair. */
  pair: string;
  rate: string;
}

export interface PriceVersion {
  id: number;
  version: number;
  note: string;
  created_at: string;
  items: PriceItem[];
}

export interface WaitingDiscount {
  id: number;
  code: string;
  company_name: string;
  sheet: number;
  person: string;
  quantity: number;
  unit: string;
  rate: string;
  discount_percent: string;
  total: string;
  currency: string;
  list_rate: string;
  version: number | null;
  effective_discount: string;
}

export interface PriceListResponse {
  ok: boolean;
  can_edit: boolean;
  list: PriceVersion | null;
  /** The version in force (null: no list yet). */
  current: number | null;
  versions: { version: number; created_at: string; note: string }[];
  limits: { sales: string; manager: string; mine: string };
  waiting: WaitingDiscount[];
  services: B2bChoice[];
  units: B2bChoice[];
  currencies: string[];
}

export function usePriceList(version: string, enabled = true) {
  return useQuery({
    queryKey: qk.priceList(version),
    queryFn: () => api<PriceListResponse>(`/api/v1/b2b/price-list/${version ? `?version=${version}` : ""}`),
    enabled,
  });
}

/** Every write asks the list and the quotations again (a decided discount changes what may be sent). */
function useWrite<V, R>(run: (values: V) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.priceListAll });
      void client.invalidateQueries({ queryKey: qk.b2b });
    },
  });
}

export const useSavePriceList = () =>
  useWrite((values: { note: string; items: PriceItem[] }) => api<{ ok: boolean; list: PriceVersion }>("/api/v1/b2b/price-list/save/", { json: values }));
export const useSaveLimits = () =>
  useWrite((values: { sales: string; manager: string }) => api<{ ok: boolean }>("/api/v1/b2b/price-list/limits/", { json: values }));
export const useDecideDiscount = () =>
  useWrite(({ id, approved, note }: { id: number; approved: boolean; note: string }) =>
    api<{ ok: boolean; state: string }>(`/api/v1/b2b/quotations/${id}/discount/`, { json: { approved, note } }),
  );
