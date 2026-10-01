import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  CLOSE_TOO_MANY,
  CLOSE_UNAUTHENTICATED,
  RealtimeConnection,
  parseEvent,
  socketUrl,
  type RealtimeEvent,
  type RealtimeOptions,
  type RealtimeStatus,
  type SocketLike,
} from "./connection";

class FakeSocket implements SocketLike {
  static all: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];
  closedWith: number | undefined | "never" = "never";

  constructor(readonly url: string) {
    FakeSocket.all.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close(code?: number) {
    this.closedWith = code;
    this.onclose?.({ code: code ?? 1005 });
  }
  // The server's side of the conversation.
  open() {
    this.onopen?.();
  }
  say(frame: unknown) {
    this.onmessage?.({ data: typeof frame === "string" ? frame : JSON.stringify(frame) });
  }
  serverCloses(code: number) {
    this.onclose?.({ code });
  }
}

function setup(overrides: Partial<RealtimeOptions> = {}) {
  const log = {
    statuses: [] as RealtimeStatus[],
    events: [] as RealtimeEvent[],
    opened: 0,
    unauthorized: 0,
  };
  const connection = new RealtimeConnection({
    url: "ws://localhost/ws/events/",
    pingSeconds: 25,
    onOpen: () => void (log.opened += 1),
    onEvent: (event) => void log.events.push(event),
    onStatus: (status) => void log.statuses.push(status),
    onUnauthorized: () => void (log.unauthorized += 1),
    createSocket: (url) => new FakeSocket(url),
    random: () => 0.5, // jitter factor 1.0: delays are exactly the table's
    ...overrides,
  });
  return { connection, log };
}

const latest = () => FakeSocket.all[FakeSocket.all.length - 1]!;

beforeEach(() => {
  FakeSocket.all = [];
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("parseEvent", () => {
  it("understands the two doorbells", () => {
    expect(parseEvent('{"t":"notify"}')).toEqual({ t: "notify" });
    expect(parseEvent('{"t":"room","id":12}')).toEqual({ t: "room", id: 12 });
  });

  it("ignores anything else", () => {
    for (const junk of [
      "not json",
      '"just a string"',
      "null",
      "[]",
      '{"t":"pong"}',
      '{"t":"room"}',
      '{"t":"room","id":"12"}',
      '{"t":"room","id":1.5}',
      '{"t":"reboot"}',
      42,
      null,
      undefined,
    ]) {
      expect(parseEvent(junk), JSON.stringify(junk)).toBeNull();
    }
  });
});

describe("socketUrl", () => {
  it("uses wss on https and ws on http", () => {
    expect(socketUrl({ protocol: "https:", host: "eagle.example" })).toBe("wss://eagle.example/ws/events/");
    expect(socketUrl({ protocol: "http:", host: "localhost:5173" })).toBe("ws://localhost:5173/ws/events/");
  });
});

describe("RealtimeConnection", () => {
  it("connects, reports open, and tells the caller to catch up", () => {
    const { connection, log } = setup();
    connection.start();
    expect(log.statuses).toEqual(["connecting"]);
    expect(latest().url).toBe("ws://localhost/ws/events/");
    latest().open();
    expect(log.statuses).toEqual(["connecting", "open"]);
    expect(log.opened).toBe(1);
    connection.stop();
  });

  it("hands on the events it understands and drops the rest", () => {
    const { connection, log } = setup();
    connection.start();
    latest().open();
    latest().say({ t: "notify" });
    latest().say({ t: "room", id: 4 });
    latest().say({ t: "pong" });
    latest().say("garbage");
    expect(log.events).toEqual([{ t: "notify" }, { t: "room", id: 4 }]);
    connection.stop();
  });

  it("pings on the timer", () => {
    const { connection } = setup({ pingSeconds: 25 });
    connection.start();
    latest().open();
    expect(latest().sent).toEqual([]);
    vi.advanceTimersByTime(25_000);
    expect(latest().sent).toEqual(['{"t":"ping"}']);
    latest().say({ t: "pong" });
    vi.advanceTimersByTime(25_000);
    expect(latest().sent).toHaveLength(2);
    connection.stop();
  });

  it("closes a connection that does not answer a ping, and opens another", () => {
    const { connection, log } = setup({ pongTimeoutMs: 10_000 });
    connection.start();
    const first = latest();
    first.open();
    vi.advanceTimersByTime(25_000); // ping goes out
    expect(first.closedWith).toBe("never");
    vi.advanceTimersByTime(10_000); // no pong
    expect(first.closedWith).toBeUndefined();
    expect(log.statuses.at(-1)).toBe("closed");
    vi.advanceTimersByTime(1_000);
    expect(FakeSocket.all).toHaveLength(2);
    connection.stop();
  });

  it("an answer in time keeps the connection", () => {
    const { connection } = setup({ pongTimeoutMs: 10_000 });
    connection.start();
    const first = latest();
    first.open();
    vi.advanceTimersByTime(25_000);
    first.say({ t: "pong" });
    vi.advanceTimersByTime(10_000);
    expect(first.closedWith).toBe("never");
    connection.stop();
  });

  it("reconnects after a close with growing delays, and starts over once it works", () => {
    const { connection } = setup();
    connection.start();
    latest().serverCloses(1006);
    vi.advanceTimersByTime(999);
    expect(FakeSocket.all).toHaveLength(1);
    vi.advanceTimersByTime(1); // 1 s
    expect(FakeSocket.all).toHaveLength(2);
    latest().serverCloses(1006);
    vi.advanceTimersByTime(2_000); // 2 s
    expect(FakeSocket.all).toHaveLength(3);
    latest().serverCloses(1006);
    vi.advanceTimersByTime(5_000); // 5 s
    expect(FakeSocket.all).toHaveLength(4);
    latest().open(); // it worked, and stayed up: the next failure starts from 1 s again
    vi.advanceTimersByTime(10_000);
    latest().serverCloses(1006);
    vi.advanceTimersByTime(1_000);
    expect(FakeSocket.all).toHaveLength(5);
    connection.stop();
  });

  it("a connection that opens and closes at once does not earn a short delay", () => {
    const { connection } = setup();
    connection.start();
    // The server accepts and hangs up every time: 1 s, 2 s, 5 s, 10 s ... not 1 s for ever.
    for (const wait of [1_000, 2_000, 5_000, 10_000]) {
      latest().open();
      latest().serverCloses(1011);
      vi.advanceTimersByTime(wait - 1);
      const before = FakeSocket.all.length;
      vi.advanceTimersByTime(1);
      expect(FakeSocket.all.length, `after ${wait} ms`).toBe(before + 1);
    }
    connection.stop();
  });

  it("never waits longer than thirty seconds between tries", () => {
    const { connection } = setup();
    connection.start();
    for (let i = 0; i < 10; i += 1) {
      latest().serverCloses(1006);
      vi.advanceTimersByTime(30_000);
    }
    expect(FakeSocket.all).toHaveLength(11);
    connection.stop();
  });

  it("stops for good when the session is gone", () => {
    const { connection, log } = setup();
    connection.start();
    latest().open();
    latest().serverCloses(CLOSE_UNAUTHENTICATED);
    expect(log.unauthorized).toBe(1);
    expect(log.statuses.at(-1)).toBe("stopped");
    vi.advanceTimersByTime(120_000);
    expect(FakeSocket.all).toHaveLength(1);
  });

  it("waits a minute when the server says there are too many sockets", () => {
    const { connection } = setup();
    connection.start();
    latest().serverCloses(CLOSE_TOO_MANY);
    vi.advanceTimersByTime(59_000);
    expect(FakeSocket.all).toHaveLength(1);
    vi.advanceTimersByTime(1_000);
    expect(FakeSocket.all).toHaveLength(2);
    connection.stop();
  });

  it("stop closes the socket, cancels the retry and does not reconnect", () => {
    const { connection, log } = setup();
    connection.start();
    latest().open();
    const socket = latest();
    connection.stop();
    expect(socket.closedWith).toBe(1000);
    expect(log.statuses.at(-1)).toBe("stopped");
    vi.advanceTimersByTime(120_000);
    expect(FakeSocket.all).toHaveLength(1);

    const second = setup();
    second.connection.start();
    latest().serverCloses(1006);
    second.connection.stop();
    vi.advanceTimersByTime(120_000);
    expect(FakeSocket.all).toHaveLength(2);
  });

  it("tries again at once when the browser comes back online", () => {
    const { connection } = setup();
    connection.start();
    latest().serverCloses(1006);
    expect(FakeSocket.all).toHaveLength(1);
    window.dispatchEvent(new Event("online"));
    expect(FakeSocket.all).toHaveLength(2);
    connection.stop();
  });

  it("is not started twice", () => {
    const { connection } = setup();
    connection.start();
    connection.start();
    expect(FakeSocket.all).toHaveLength(1);
    connection.stop();
  });
});
