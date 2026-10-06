import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { qk } from "../api/keys";
import { handleEvent, RealtimeProvider, sessionRenewed } from "./RealtimeProvider";

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

  it("a room doorbell refreshes the chat list, that room and the unread numbers on the tabs, and nothing else", () => {
    const { client, invalidateQueries } = spy();
    handleEvent(client, { t: "room", id: 12 });
    // `me` carries the number on each chats tab (and the sidebar's): a message in a room moves them.
    expect(invalidateQueries.mock.calls.map((call) => call[0])).toEqual([
      { queryKey: qk.chats },
      { queryKey: qk.room(12) },
      { queryKey: qk.me },
    ]);
  });
});

describe("sessionRenewed", () => {
  const sockets: { closed: boolean; close: () => void; onclose: unknown; onopen: unknown; onmessage: unknown; send: () => void }[] = [];

  class FakeSocket {
    closed = false;
    onclose: unknown = null;
    onopen: unknown = null;
    onmessage: unknown = null;
    constructor() {
      sockets.push(this);
    }
    close() {
      this.closed = true;
    }
    send() {}
  }

  afterEach(() => {
    vi.unstubAllGlobals();
    sockets.length = 0;
  });

  it("closes the socket that carries the old session and opens another with the new one", () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    const view = render(
      <QueryClientProvider client={new QueryClient()}>
        <RealtimeProvider>
          <div>page</div>
        </RealtimeProvider>
      </QueryClientProvider>,
    );
    expect(sockets).toHaveLength(1);
    sessionRenewed();
    expect(sockets).toHaveLength(2);
    expect(sockets[0]!.closed).toBe(true);
    expect(sockets[1]!.closed).toBe(false);
    // Gone with the page: nothing is listening for it any more.
    view.unmount();
    sessionRenewed();
    expect(sockets).toHaveLength(2);
  });
});
