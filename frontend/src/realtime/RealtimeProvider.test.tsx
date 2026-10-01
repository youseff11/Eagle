import type { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { qk } from "../api/keys";
import { handleEvent } from "./RealtimeProvider";

function spy() {
  const invalidateQueries = vi.fn(async (_filters?: unknown) => undefined);
  return { client: { invalidateQueries } as unknown as QueryClient, invalidateQueries };
}

describe("handleEvent", () => {
  it("a notification doorbell refreshes the notifications and the unread count", () => {
    const { client, invalidateQueries } = spy();
    handleEvent(client, { t: "notify" });
    expect(invalidateQueries.mock.calls.map((call) => call[0])).toEqual([
      { queryKey: qk.notifications },
      { queryKey: qk.me },
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
