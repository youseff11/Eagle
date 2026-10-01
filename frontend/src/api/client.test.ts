import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, csrfToken, setUnauthorizedHandler } from "./client";
import { jsonResponse } from "../test/helpers";

describe("api", () => {
  beforeEach(() => {
    document.cookie = "csrftoken=tok123";
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    setUnauthorizedHandler(null);
    document.cookie = "csrftoken=; max-age=0";
  });

  function stub(response: Response | (() => Response)) {
    const fn = vi.fn(async (_path: string, _init?: RequestInit) =>
      typeof response === "function" ? response() : response,
    );
    vi.stubGlobal("fetch", fn);
    return fn;
  }

  it("reads the csrf token from the cookie", () => {
    expect(csrfToken()).toBe("tok123");
  });

  it("does not choke on a cookie that is not valid percent-encoding", () => {
    document.cookie = "csrftoken=%E0%A4%A";
    expect(() => csrfToken()).not.toThrow();
  });

  it("sends a GET without a csrf header and with the session cookie", async () => {
    const fetchMock = stub(jsonResponse({ ok: true }));
    await api("/api/v1/me/");
    const [path, init] = fetchMock.mock.calls[0]!;
    expect(path).toBe("/api/v1/me/");
    expect(init?.method).toBe("GET");
    expect(init?.credentials).toBe("same-origin");
    expect((init?.headers as Record<string, string>)["X-CSRFToken"]).toBeUndefined();
  });

  it("sends a JSON write as a POST with the token and the content type", async () => {
    const fetchMock = stub(jsonResponse({ ok: true }));
    await api("/api/v1/notifications/read/", { json: { all: true } });
    const init = fetchMock.mock.calls[0]![1]!;
    const headers = init.headers as Record<string, string>;
    expect(init.method).toBe("POST");
    expect(headers["X-CSRFToken"]).toBe("tok123");
    expect(headers["Content-Type"]).toBe("application/json");
    expect(init.body).toBe('{"all":true}');
  });

  it("sends a form write url-encoded, for the older endpoints", async () => {
    const fetchMock = stub(jsonResponse({ ok: true }));
    await api("/api/prefs/", { form: { lang: "en" } });
    const init = fetchMock.mock.calls[0]![1]!;
    expect(init.method).toBe("POST");
    expect(String(init.body)).toBe("lang=en");
    expect((init.headers as Record<string, string>)["X-CSRFToken"]).toBe("tok123");
  });

  it("turns the server's error code into an ApiError", async () => {
    stub(jsonResponse({ ok: false, error: "csrf" }, 403));
    const failure = await api("/api/v1/x/").catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure).toMatchObject({ status: 403, code: "csrf" });
  });

  it("gives an HTML error page a generic code instead of choking on it", async () => {
    stub(() => new Response("<html>oops</html>", { status: 500 }));
    await expect(api("/api/v1/x/")).rejects.toMatchObject({ status: 500, code: "http_500" });
  });

  it("calls the unauthorized handler once on a 401 and still throws", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    stub(jsonResponse({ ok: false, error: "auth" }, 401));
    await expect(api("/api/v1/me/")).rejects.toMatchObject({ status: 401, code: "auth" });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("treats a redirect to the login page as the session being gone", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    const redirected = new Response("<html>sign in</html>", { status: 200 });
    Object.defineProperty(redirected, "redirected", { value: true });
    Object.defineProperty(redirected, "url", { value: "http://localhost/login/?next=/api/heartbeat/" });
    stub(redirected);
    await expect(api("/api/heartbeat/")).rejects.toMatchObject({ status: 401, code: "auth" });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("does not mistake an ordinary redirect for it", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    const moved = jsonResponse({ ok: true });
    Object.defineProperty(moved, "redirected", { value: true });
    Object.defineProperty(moved, "url", { value: "http://localhost/api/v1/me/" });
    stub(moved);
    await expect(api("/api/v1/me/")).resolves.toEqual({ ok: true });
    expect(handler).not.toHaveBeenCalled();
  });

  it("does not call the handler for other failures", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    stub(jsonResponse({ ok: false, error: "not_found" }, 404));
    await expect(api("/api/v1/rooms/9/messages/")).rejects.toMatchObject({ code: "not_found" });
    expect(handler).not.toHaveBeenCalled();
  });
});
