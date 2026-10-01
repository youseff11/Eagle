/**
 * What a person has written and not yet seen arrive (chat slice 3b).
 *
 * The message shows at once as a bubble of its own ("sending"), and the page sends it. The server's answer is
 * the whole thread as it now is, so on success the bubble is simply replaced by the real one. Two things can
 * go wrong, and they are not the same:
 *
 * - the server refused (any 4xx): nothing was written, and sending it again is safe -> `refused`;
 * - nothing came back (the connection dropped, it timed out, the server failed): the message may or may not
 *   be there, and sending it again could put it on a client's phone twice -> `unsure`. The page looks at the
 *   thread before it says anything: if a message of ours with these words has appeared since, it arrived.
 *
 * The queue lives in the query cache under `qk.outbox`, not in a component: a person who leaves a
 * conversation while a message is on its way still finds it, failed or not, when they come back, and the
 * send itself carries on after the screen is gone.
 */

import type { QueryClient } from "@tanstack/react-query";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useSyncExternalStore } from "react";
import { ApiError } from "../api/client";
import { qk } from "../api/keys";
import { fetchThread, postMessage } from "../api/queries";
import type { ThreadEntry, ThreadResponse } from "../api/types";

/** The message a reply answers, as the reply bar and the bubble show it. */
export interface ReplyTarget {
  uid: string;
  who: string;
  text: string;
}

export interface Outgoing {
  key: number;
  body: string;
  reply: ReplyTarget | null;
  /** The uids that were in the thread when it was first sent: whatever is new after them may be this message. */
  before: string[];
  state: "sending" | "refused" | "unsure";
  /** The server's short code for a refusal (`forbidden`, `not_found`, `csrf` ...). */
  error: string;
}

let counter = 0;

/** Does this entry look like the message `item` stands for: ours, new since it was sent, with the same words? */
function matches(entry: ThreadEntry, item: Outgoing, meId: number): boolean {
  if (entry.kind !== "out" || new Set(item.before).has(entry.uid)) return false;
  if (entry.body.trim() !== item.body.trim()) return false;
  // A group says `mine`; a client's thread does not, and names whoever sent it by id (a name is not unique).
  return entry.mine || (meId > 0 && entry.sender_id === meId);
}

/**
 * The queue without what has already arrived: each message that is in the thread now is matched with one
 * queued message (the first, in order), so two identical lines sent in a row are two bubbles, not one. A
 * refused message is never matched - nothing of it was written.
 */
export function unmatched(items: Outgoing[], messages: ThreadEntry[], meId: number): Outgoing[] {
  const used = new Set<string>();
  return items.filter((item) => {
    if (item.state === "refused") return true;
    const hit = messages.find((entry) => !used.has(entry.uid) && matches(entry, item, meId));
    if (!hit) return true;
    used.add(hit.uid);
    return false;
  });
}

function items(client: QueryClient, code: string): Outgoing[] {
  return client.getQueryData<Outgoing[]>(qk.outbox(code)) ?? [];
}

function put(client: QueryClient, code: string, next: Outgoing[]): void {
  client.setQueryData(qk.outbox(code), next);
}

function patch(client: QueryClient, code: string, key: number, change: Partial<Outgoing>): void {
  put(client, code, items(client, code).map((item) => (item.key === key ? { ...item, ...change } : item)));
}

/** Take a message off the queue: it arrived, or the person gave it up. */
export function drop(client: QueryClient, code: string, keys: number[]): void {
  if (keys.length === 0) return;
  put(client, code, items(client, code).filter((item) => !keys.includes(item.key)));
}

/**
 * Look at the conversation as it is now, with a request that starts now: one already on its way may have been
 * asked before the server wrote the message, and would say it is not there.
 */
async function lookAgain(client: QueryClient, code: string): Promise<ThreadResponse> {
  const fresh = await fetchThread(code);
  client.setQueryData(qk.thread(code), fresh);
  return fresh;
}

/** Send what is queued under `key`, and settle it as the answer says. Never throws. */
export async function deliver(client: QueryClient, code: string, key: number, meId: number): Promise<void> {
  const item = items(client, code).find((candidate) => candidate.key === key);
  if (!item) return;
  patch(client, code, key, { state: "sending", error: "" });
  try {
    const answer = await postMessage(code, item.body, item.reply?.uid);
    client.setQueryData(qk.thread(code), { ok: true, client: answer.client, messages: answer.messages });
    drop(client, code, [key]);
    // The row in the list now says what was just written.
    void client.invalidateQueries({ queryKey: qk.chatLists });
  } catch (error) {
    if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
      patch(client, code, key, { state: "refused", error: error.code });
      return;
    }
    patch(client, code, key, { state: "unsure", error: "" });
    try {
      const fresh = await lookAgain(client, code);
      if (unmatched([item], fresh.messages, meId).length === 0) drop(client, code, [key]);
    } catch {
      // Still no news: it stays "not sure", with the person to decide.
    }
  }
}

/**
 * "Try again". A message that may already have arrived is looked for first: the person asked to send it
 * again, not to send it twice.
 */
export async function retry(client: QueryClient, code: string, key: number, meId: number): Promise<void> {
  const item = items(client, code).find((candidate) => candidate.key === key);
  if (!item || item.state === "sending") return;
  if (item.state === "unsure") {
    patch(client, code, key, { state: "sending" });
    try {
      const fresh = await lookAgain(client, code);
      if (unmatched([item], fresh.messages, meId).length === 0) {
        drop(client, code, [key]);
        return;
      }
    } catch {
      // Cannot tell: the person asked, and it goes.
    }
  }
  await deliver(client, code, key, meId);
}

/** Queue a message and send it. Returns its key. */
export function submit(
  client: QueryClient,
  code: string,
  draft: { body: string; reply: ReplyTarget | null; known: string[] },
  meId: number,
): number {
  counter += 1;
  const item: Outgoing = {
    key: counter,
    body: draft.body,
    reply: draft.reply,
    before: draft.known,
    state: "sending",
    error: "",
  };
  put(client, code, [...items(client, code), item]);
  void deliver(client, code, item.key, meId);
  return item.key;
}

/** What is queued in one conversation, live. */
export function useOutbox(code: string): Outgoing[] {
  const query = useQuery({
    queryKey: qk.outbox(code),
    // Never fetched: the queue is only ever written by `submit`, `deliver` and `drop`.
    queryFn: () => [] as Outgoing[],
    initialData: [] as Outgoing[],
    enabled: false,
    staleTime: Infinity,
    gcTime: Infinity,
  });
  return query.data;
}

/**
 * The conversations in which a message did not go (refused, or nobody knows if it arrived), as the codes
 * joined by a comma. A string, so it is a stable thing to subscribe to: the list marks them and the menu
 * says so from any page, because a message that stayed behind unseen is a client who was not answered.
 */
export function useOutboxProblems(): string[] {
  const client = useQueryClient();
  const read = () =>
    client
      .getQueriesData<Outgoing[]>({ queryKey: ["outbox"] })
      .filter(([, items]) => (items ?? []).some((item) => item.state !== "sending"))
      .map(([key]) => String(key[1]))
      .sort()
      .join(",");
  const joined = useSyncExternalStore(
    (notify) => client.getQueryCache().subscribe(notify),
    read,
    () => "",
  );
  return joined === "" ? [] : joined.split(",");
}

/** Stable handles for a component to call. */
export function useOutboxActions(code: string, meId: number) {
  const client = useQueryClient();
  return {
    send: useCallback(
      (draft: { body: string; reply: ReplyTarget | null; known: string[] }) => submit(client, code, draft, meId),
      [client, code, meId],
    ),
    retry: useCallback((key: number) => void retry(client, code, key, meId), [client, code, meId]),
    discard: useCallback((key: number) => drop(client, code, [key]), [client, code]),
    /** Take off the queue what has reached the thread by another road (a poll, the doorbell). */
    prune: useCallback((keys: number[]) => drop(client, code, keys), [client, code]),
  };
}
