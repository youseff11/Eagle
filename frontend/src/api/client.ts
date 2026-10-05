/**
 * The one way this app talks to Django.
 *
 * Same origin, session cookie, JSON in and out. A write carries the CSRF token
 * from the cookie `/api/v1/me/` sets. Every failure is an `ApiError` with the
 * server's short error code ("auth", "not_found", "csrf", "bad_ids" ...), never
 * the HTML page an old endpoint might answer with.
 */

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  /** What the server answered (parsed JSON, or `null`): a refusal may carry the reason in words (`message`). */
  readonly payload: unknown;

  constructor(status: number, code: string, payload: unknown = null) {
    super(`${status} ${code}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.payload = payload;
  }

  /** The reason the server gave in words, when it gave one (`message` on the newer doors, `detail` on the older ones). */
  get detail(): string {
    if (!this.payload || typeof this.payload !== "object") return "";
    const { message, detail } = this.payload as { message?: unknown; detail?: unknown };
    if (typeof message === "string" && message) return message;
    return typeof detail === "string" ? detail : "";
  }
}

let onUnauthorized: (() => void) | null = null;

/** Called once for every 401: the session is gone, send the person to sign in. */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

export function csrfToken(): string {
  const entry = document.cookie.split("; ").find((part) => part.startsWith("csrftoken="));
  // Django's token is letters and digits; decoding a stray cookie could throw and stop every write.
  return entry ? entry.slice("csrftoken=".length) : "";
}

export interface RequestOptions {
  method?: "GET" | "POST";
  /** A JSON body. */
  json?: unknown;
  /** A form body, for the older endpoints that read `request.POST`. */
  form?: Record<string, string>;
  /** A multipart body, for what carries files. The browser writes its Content-Type (with the boundary): never set it here. */
  multipart?: FormData;
  signal?: AbortSignal;
}

function errorCode(payload: unknown, status: number): string {
  if (payload && typeof payload === "object" && "error" in payload) {
    const code = (payload as { error: unknown }).error;
    if (typeof code === "string" && code) return code;
  }
  return `http_${status}`;
}

/** A file the server sent back (a backup): its bytes, the name it gave, and the headers it carried. */
export interface Download {
  blob: Blob;
  filename: string;
  headers: Headers;
}

/**
 * A write whose answer is a file. A refusal still arrives as JSON (an `ApiError` as anywhere else); only a success is
 * read as bytes. Used where the file is the only copy of what the request just deleted.
 */
export async function apiDownload(path: string, json: unknown, fallbackName: string): Promise<Download> {
  const response = await fetch(path, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
    body: JSON.stringify(json),
    credentials: "same-origin",
  });
  if (response.status === 401) {
    onUnauthorized?.();
    throw new ApiError(401, "auth");
  }
  if (!response.ok) {
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    throw new ApiError(response.status, errorCode(payload, response.status), payload);
  }
  const match = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") ?? "");
  return { blob: await response.blob(), filename: match?.[1] ?? fallbackName, headers: response.headers };
}

/**
 * What was asked for ahead of a click (`askAheadUrl`), by address: the answer, or the ask still on its way. Each is for the
 * next page that asks for the same address, once; an unused one goes stale after `AHEAD_TTL_MS`.
 */
const ahead = new Map<string, { at: number; promise: Promise<unknown> }>();
const AHEAD_TTL_MS = 10 * 60 * 1000;
/** An answer older than this is drawn at once and then asked for again behind the page (`AHEAD_AGED_EVENT`). */
const AHEAD_AGED_MS = 10_000;
/** Said on `window` when a page was opened on an answer that has had time to go stale: the app asks again, quietly. */
export const AHEAD_AGED_EVENT = "eagle:ahead-aged";

/**
 * Ask for a read now, for the page that will want it: the pointer is on its link, or the person's menu is being warmed. The
 * answer waits for that page's own `api()` call for the same address, which takes it instead of asking again, so the page
 * opens on data and not on a wait. A failure is forgotten (the page asks for itself, and says what went wrong).
 */
export function askAheadUrl(path: string): Promise<unknown> {
  const held = ahead.get(path);
  if (held && Date.now() - held.at < AHEAD_TTL_MS) return held.promise.catch(() => undefined);
  const promise = fetchJson<unknown>(path, {});
  ahead.set(path, { at: Date.now(), promise });
  return promise.catch(() => {
    if (ahead.get(path)?.promise === promise) ahead.delete(path);
  });
}

export function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const read = options.json === undefined && options.form === undefined && options.multipart === undefined && !options.signal;
  if (read && (options.method ?? "GET") === "GET") {
    const held = ahead.get(path);
    if (held) {
      ahead.delete(path);
      const age = Date.now() - held.at;
      if (age < AHEAD_TTL_MS) {
        if (age > AHEAD_AGED_MS) window.dispatchEvent(new Event(AHEAD_AGED_EVENT));
        return held.promise as Promise<T>;
      }
    }
  }
  if (read) return fetchJson<T>(path, options);
  // A write changes what was asked ahead: what is held for a page was true before it, so it is dropped (the page asks for itself).
  return fetchJson<T>(path, options).then((answer) => {
    ahead.clear();
    return answer;
  });
}

async function fetchJson<T>(path: string, options: RequestOptions): Promise<T> {
  const writes = options.json !== undefined || options.form !== undefined || options.multipart !== undefined;
  const method = options.method ?? (writes ? "POST" : "GET");
  const headers: Record<string, string> = { Accept: "application/json" };
  let body: BodyInit | undefined;

  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.json);
  } else if (options.form !== undefined) {
    body = new URLSearchParams(options.form);
  } else if (options.multipart !== undefined) {
    body = options.multipart;
  }
  if (method !== "GET") headers["X-CSRFToken"] = csrfToken();

  const response = await fetch(path, {
    method,
    headers,
    body,
    credentials: "same-origin",
    signal: options.signal,
  });

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  // The older endpoints answer an expired session with a redirect to the HTML login page, which
  // fetch follows quietly: that is the same news as a 401.
  const sentToLogin = response.redirected && new URL(response.url, window.location.origin).pathname.startsWith("/login");
  if (response.status === 401 || sentToLogin) {
    onUnauthorized?.();
    throw new ApiError(401, "auth");
  }
  if (!response.ok) throw new ApiError(response.status, errorCode(payload, response.status), payload);
  return payload as T;
}
