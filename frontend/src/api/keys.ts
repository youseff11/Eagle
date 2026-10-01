/** Query keys. A doorbell from the server invalidates by these. */
export const qk = {
  me: ["me"] as const,
  notifications: ["notifications"] as const,
  chats: ["chats"] as const,
  room: (id: number) => ["room", id] as const,
};
