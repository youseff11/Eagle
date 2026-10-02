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

  /** The reason the server gave in words, when it gave one. */
  get detail(): string {
    const value = this.payload && typeof this.payload === "object" ? (this.payload as { message?: unknown }).message : undefined;
    return typeof value === "string" ? value : "";
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

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
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
