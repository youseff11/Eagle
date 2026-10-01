/**
 * The WebSocket to /ws/events/, kept alive.
 *
 * The server only ever sends a doorbell: `{"t":"notify"}` or `{"t":"room","id":N}`.
 * What those mean is decided by whoever handles them (they refetch from the API,
 * which applies the permissions). This class owns only the connection:
 *
 *  - ping on a timer, because the server revalidates the session at each ping and
 *    the edge drops a silent connection; no answer in time means the connection is
 *    dead, so it is closed and reopened;
 *  - reconnect with growing, jittered delays after any close, starting over only
 *    once a connection has stayed up for ten seconds. 4401 (the session is gone)
 *    stops and says so; 4429 (too many sockets) waits a minute. The server sends
 *    both only AFTER accepting; refused during the handshake (a dead session, a sixth
 *    tab) the browser sees a plain failure and the ordinary delays apply. A dead
 *    session is then found by the 401 on `/api/v1/me/`, which is polled while the
 *    socket is down;
 *  - after every (re)connect, `onOpen` fires so the caller can catch up on
 *    whatever was missed while it was down.
 */

export type RealtimeEvent = { t: "notify" } | { t: "room"; id: number };
export type RealtimeStatus = "connecting" | "open" | "closed" | "stopped";

export interface SocketLike {
  onopen: (() => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onclose: ((event: { code: number }) => void) | null;
  onerror: (() => void) | null;
  send(data: string): void;
  close(code?: number): void;
}

export interface RealtimeOptions {
  url: string;
  pingSeconds: number;
  onOpen(): void;
  onEvent(event: RealtimeEvent): void;
  onStatus(status: RealtimeStatus): void;
  onUnauthorized(): void;
  /** Test seams. */
  createSocket?: (url: string) => SocketLike;
  random?: () => number;
  pongTimeoutMs?: number;
}

export const CLOSE_UNAUTHENTICATED = 4401;
export const CLOSE_TOO_MANY = 4429;
const RETRY_DELAYS_MS = [1000, 2000, 5000, 10000, 20000, 30000];
const TOO_MANY_DELAY_MS = 60000;
const PONG_TIMEOUT_MS = 10000;
/** A connection that lasted this long counts as having worked; one that closes at once does not. */
const STABLE_AFTER_MS = 10000;

/** What a frame means to us, or `null` for anything we do not act on. */
export function parseEvent(data: unknown): RealtimeEvent | null {
  if (typeof data !== "string") return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object") return null;
  const record = parsed as { t?: unknown; id?: unknown };
  if (record.t === "notify") return { t: "notify" };
  if (record.t === "room" && typeof record.id === "number" && Number.isInteger(record.id)) {
    return { t: "room", id: record.id };
  }
  return null;
}

export function socketUrl(location: Pick<Location, "protocol" | "host"> = window.location): string {
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${location.host}/ws/events/`;
}

export class RealtimeConnection {
  private socket: SocketLike | null = null;
  private attempts = 0;
  private stopped = true;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private pongTimer: ReturnType<typeof setTimeout> | null = null;
  private stableTimer: ReturnType<typeof setTimeout> | null = null;
  private nextDelayOverride: number | null = null;
  private readonly options: RealtimeOptions;

  constructor(options: RealtimeOptions) {
    this.options = options;
  }

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    window.addEventListener("online", this.reconnectNow);
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    window.removeEventListener("online", this.reconnectNow);
    this.clearTimers();
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      socket.onclose = null;
      socket.close(1000);
    }
    this.options.onStatus("stopped");
  }

  private readonly reconnectNow = (): void => {
    if (this.stopped || this.socket) return;
    this.attempts = 0;
    this.clearRetry();
    this.connect();
  };

  private connect(): void {
    this.options.onStatus("connecting");
    const make = this.options.createSocket ?? ((url: string) => new WebSocket(url) as unknown as SocketLike);
    const socket = make(this.options.url);
    this.socket = socket;

    socket.onopen = () => {
      // Not `attempts = 0` yet: a server that accepts and closes straight away would
      // otherwise be retried every second for ever. Only a connection that stays up counts.
      this.stableTimer = setTimeout(() => {
        this.attempts = 0;
      }, STABLE_AFTER_MS);
      this.options.onStatus("open");
      this.startPings(socket);
      this.options.onOpen();
    };
    socket.onmessage = (message) => {
      this.clearPong();
      const event = parseEvent(message.data);
      if (event) this.options.onEvent(event);
    };
    socket.onerror = () => {
      /* a close follows; that is where it is handled */
    };
    socket.onclose = (event) => this.handleClose(event.code);
  }

  private handleClose(code: number): void {
    this.socket = null;
    this.clearTimers();
    if (this.stopped) return;
    if (code === CLOSE_UNAUTHENTICATED) {
      this.stopped = true;
      window.removeEventListener("online", this.reconnectNow);
      this.options.onStatus("stopped");
      this.options.onUnauthorized();
      return;
    }
    this.options.onStatus("closed");
    this.nextDelayOverride = code === CLOSE_TOO_MANY ? TOO_MANY_DELAY_MS : null;
    this.scheduleRetry();
  }

  private scheduleRetry(): void {
    const base = this.nextDelayOverride ?? RETRY_DELAYS_MS[Math.min(this.attempts, RETRY_DELAYS_MS.length - 1)]!;
    const jitter = 0.8 + (this.options.random ?? Math.random)() * 0.4;
    this.attempts += 1;
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      if (!this.stopped) this.connect();
    }, Math.round(base * jitter));
  }

  private startPings(socket: SocketLike): void {
    this.pingTimer = setInterval(() => {
      if (this.socket !== socket) return;
      socket.send(JSON.stringify({ t: "ping" }));
      this.clearPong();
      this.pongTimer = setTimeout(() => {
        // Nothing came back: the connection is dead even though no close arrived.
        socket.close();
      }, this.options.pongTimeoutMs ?? PONG_TIMEOUT_MS);
    }, this.options.pingSeconds * 1000);
  }

  private clearPong(): void {
    if (this.pongTimer) clearTimeout(this.pongTimer);
    this.pongTimer = null;
  }

  private clearRetry(): void {
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = null;
  }

  private clearTimers(): void {
    if (this.stableTimer) clearTimeout(this.stableTimer);
    this.stableTimer = null;
    this.clearRetry();
    this.clearPong();
    if (this.pingTimer) clearInterval(this.pingTimer);
    this.pingTimer = null;
  }
}
