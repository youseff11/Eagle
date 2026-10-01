import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRealtimeStatus } from "../realtime/RealtimeProvider";
import { api } from "./client";
import { qk } from "./keys";
import type { MeResponse, NotificationsResponse, ReadResponse } from "./types";

/** How often to ask when the socket is not there to say something changed. */
export const FALLBACK_POLL_MS = 15000;
const PAGE = 20;

function useFallbackInterval(): number | false {
  return useRealtimeStatus() === "open" ? false : FALLBACK_POLL_MS;
}

export function useMe() {
  const refetchInterval = useFallbackInterval();
  return useQuery({
    queryKey: qk.me,
    queryFn: () => api<MeResponse>("/api/v1/me/"),
    refetchInterval,
  });
}

export function useNotifications() {
  const refetchInterval = useFallbackInterval();
  return useInfiniteQuery({
    queryKey: qk.notifications,
    initialPageParam: null as number | null,
    queryFn: ({ pageParam }) =>
      api<NotificationsResponse>(
        `/api/v1/notifications/?limit=${PAGE}${pageParam ? `&before=${pageParam}` : ""}`,
      ),
    getNextPageParam: (last) => last.next_before,
    refetchInterval,
  });
}

/** Mark some notifications read, or all of them when no ids are given. */
export function useMarkRead() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (ids?: number[]) =>
      api<ReadResponse>("/api/v1/notifications/read/", { json: ids ? { ids } : { all: true } }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: qk.notifications });
      void client.invalidateQueries({ queryKey: qk.me });
    },
  });
}
