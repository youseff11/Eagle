/** Query keys. A doorbell from the server invalidates by these. */
export const qk = {
  me: ["me"] as const,
  notifications: ["notifications"] as const,
  chats: ["chats"] as const,
  /** Everything a list page shows: one prefix, so a change on the boards refreshes them all. */
  boards: ["boards"] as const,
  translatorHome: ["boards", "translator-home"] as const,
  room: (id: number) => ["room", id] as const,
};
