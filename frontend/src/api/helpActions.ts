import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "./client";
import { qk } from "./keys";
import type { HelpAnswer, HelpHome, HelpOrderResult, Lang } from "./types";

/** The questions to offer when the assistant opens (this person's role's first), asked for only once it is opened. */
export function useHelpHome(lang: Lang, enabled: boolean) {
  return useQuery({
    queryKey: qk.help(lang),
    queryFn: () => api<HelpHome>(`/api/v1/help/?lang=${lang}`),
    enabled,
    staleTime: 30_000,
  });
}

/** One turn of the conversation, as the server's AI path reads it. */
export interface HelpTurn {
  role: "user" | "assistant";
  text: string;
}

export interface HelpQuestion {
  /** What the person typed; empty for a question picked from the offered ones. */
  question: string;
  /** The guide picked from the offered ones: answered from that guide itself. */
  guide?: string;
  lang: Lang;
  /** Where the person is (the path inside the app): the server keeps only its shape, `/tasks/:code`. */
  page: string;
  history: HelpTurn[];
  /** True: an order the owner gives is carried out at once, not left waiting for a press. */
  auto?: boolean;
}

export function useAsk() {
  return useMutation({
    mutationFn: (values: HelpQuestion) => api<HelpAnswer>("/api/v1/help/ask/", { json: values }),
  });
}

/** The owner's yes to a prepared order: it is carried out once, through the door a click would have used. */
export function useRunOrder() {
  return useMutation({
    gcTime: 0,
    mutationFn: ({ id, lang }: { id: number; lang: Lang }) =>
      api<HelpOrderResult>(`/api/v1/help/orders/${id}/run/`, { json: { lang } }),
  });
}

/** The owner's no: the order is withdrawn. */
export function useCancelOrder() {
  return useMutation({
    mutationFn: (id: number) => api<{ ok: true }>(`/api/v1/help/orders/${id}/cancel/`, { json: {} }),
  });
}
