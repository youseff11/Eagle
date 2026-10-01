import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRealtimeStatus } from "../realtime/RealtimeProvider";
import { api } from "./client";
import { qk } from "./keys";
import type {
  ChatKind,
  ChatListResponse,
  MeResponse,
  MovedResponse,
  NotificationsResponse,
  ReadResponse,
  ThreadResponse,
  TranslatorHomeResponse,
} from "./types";

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

/** The translator's own desk. Refreshed when the boards move (see `useHeartbeat`, `handleEvent`). */
export function useTranslatorHome(enabled = true) {
  const refetchInterval = useFallbackInterval();
  return useQuery({
    queryKey: qk.translatorHome,
    queryFn: () => api<TranslatorHomeResponse>("/api/v1/translator/home/"),
    refetchInterval,
    // Everybody else is refused, and every refusal is written to the audit log: a page left
    // open would write a row at every refresh.
    enabled,
  });
}

/** One of the three chat lists, optionally narrowed by a search. */
export function useChatList(kind: ChatKind, query: string) {
  const refetchInterval = useFallbackInterval();
  return useQuery({
    queryKey: qk.chatList(kind, query),
    queryFn: () =>
      api<ChatListResponse>(`/api/v1/chats/?type=${kind}${query ? `&q=${encodeURIComponent(query)}` : ""}`),
    refetchInterval,
  });
}

/** Where the messages of a conversation are, from the code its row carries; `null` for a code that is none. */
export function threadPath(code: string): string | null {
  if (/^g\d+$/.test(code)) return `/api/v1/groups/${code.slice(1)}/messages/`;
  if (/^u\d+$/.test(code)) return `/api/v1/staff/${code.slice(1)}/messages/`;
  if (/^[A-Za-z0-9-]{1,40}$/.test(code)) return `/api/v1/clients/${code}/messages/`;
  return null;
}

/** Where to say "I have read this" for a conversation, or `null` where there is no room yet. */
export function readPath(code: string, room: number | undefined): string | null {
  if (/^g\d+$/.test(code)) return `/api/v1/groups/${code.slice(1)}/read/`;
  if (/^u\d+$/.test(code)) return room ? `/api/v1/groups/${room}/read/` : null;
  return /^[A-Za-z0-9-]{1,40}$/.test(code) ? `/api/v1/clients/${code}/read/` : null;
}

/**
 * The messages of one conversation. Refetched when the chats' doorbell rings, or by polling without the
 * socket - and always when the conversation is opened: what the cache holds may be minutes old, and what is
 * on screen is what "read" is about (see `Conversation`).
 */
export function useThread(code: string | undefined) {
  const refetchInterval = useFallbackInterval();
  const path = code ? threadPath(code) : null;
  return useQuery({
    queryKey: qk.thread(code ?? ""),
    queryFn: () => api<ThreadResponse>(path!),
    enabled: path !== null,
    refetchInterval,
    refetchOnMount: "always",
  });
}

/**
 * This person has the conversation on screen and has read it up to message `upto`, the newest the screen
 * shows (a POST, never a GET). Naming it matters: what the client wrote after the page last asked has been
 * on nobody's screen, and for a client "read" is also the blue ticks on their phone.
 */
export function useMarkChatRead() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ path, upto }: { path: string; upto: number }) => api<MovedResponse>(path, { json: { upto } }),
    onSuccess: (answer) => {
      if (answer.moved) {
        void client.invalidateQueries({ queryKey: qk.chats });
        void client.invalidateQueries({ queryKey: qk.me });
      }
    },
  });
}
