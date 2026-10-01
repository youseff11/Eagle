/** Query keys. A doorbell from the server invalidates by these. */
export const qk = {
  me: ["me"] as const,
  notifications: ["notifications"] as const,
  /** The prefix of everything the chats page shows: one doorbell refreshes the lists and the open thread. */
  chats: ["chats"] as const,
  chatList: (kind: string, query: string) => ["chats", "list", kind, query] as const,
  /** Every list, whatever the tab or the search: what a send refreshes. */
  chatLists: ["chats", "list"] as const,
  thread: (code: string) => ["chats", "thread", code] as const,
  /** What this person wrote in a conversation and has not seen arrive: kept outside `chats`, so a doorbell never drops it. */
  outbox: (code: string) => ["outbox", code] as const,
  /** Everything a list page shows: one prefix, so a change on the boards refreshes them all. */
  boards: ["boards"] as const,
  translatorHome: ["boards", "translator-home"] as const,
  room: (id: number) => ["room", id] as const,
};
