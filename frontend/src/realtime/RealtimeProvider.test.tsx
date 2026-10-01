import type { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { qk } from "../api/keys";
import { handleEvent } from "./RealtimeProvider";

function spy() {
  const invalidateQueries = vi.fn(async (_filters?: unknown) => undefined);
  return { client: { invalidateQueries } as unknown as QueryClient, invalidateQueries };
}

describe("handleEvent", () => {
  it("a notification doorbell refreshes the notifications, the unread count, the boards and the chats", () => {
    const { client, invalidateQueries } = spy();
    handleEvent(client, { t: "notify" });
    // The boards too: every workflow step notifies somebody, so this is the quickest word that a
    // task moved, ahead of the next heartbeat. And the chats: a client's message sits in no room,
    // so it is announced as a notification.
    expect(invalidateQueries.mock.calls.map((call) => call[0])).toEqual([
      { queryKey: qk.notifications },
      { queryKey: qk.me },
      { queryKey: qk.boards },
      { queryKey: qk.chats },
    ]);
  });

  it("a room doorbell refreshes the chat list and that room, and nothing else", () => {
    const { client, invalidateQueries } = spy();
    handleEvent(client, { t: "room", id: 12 });
    expect(invalidateQueries.mock.calls.map((call) => call[0])).toEqual([
      { queryKey: qk.chats },
      { queryKey: qk.room(12) },
    ]);
  });
});
