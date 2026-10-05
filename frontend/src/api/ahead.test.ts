import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, mockFetch } from "../test/helpers";
import { AHEAD_AGED_EVENT, api, askAheadUrl } from "./client";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function serve(answer: () => Response = () => jsonResponse({ ok: true, n: 1 })) {
  const mocked = mockFetch({ "/api/v1/": answer });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked.calls;
}

describe("askAheadUrl", () => {
  it("is taken by the page's own ask for the same address, once, so the server is asked once", async () => {
    const calls = serve();
    await askAheadUrl("/api/v1/thing/");
    expect(await api("/api/v1/thing/")).toEqual({ ok: true, n: 1 });
    expect(calls.map((call) => call.url)).toEqual(["/api/v1/thing/"]);
    // Used up: the next ask is a real one.
    await api("/api/v1/thing/");
    expect(calls).toHaveLength(2);
  });

  it("is waited for when the page asks while it is still on its way", async () => {
    const calls = serve();
    void askAheadUrl("/api/v1/slow/");
    const answer = await api<{ n: number }>("/api/v1/slow/");
    expect(answer.n).toBe(1);
    expect(calls).toHaveLength(1);
  });

  it("asks once for two asks ahead of the same address", async () => {
    const calls = serve();
    await Promise.all([askAheadUrl("/api/v1/twice/"), askAheadUrl("/api/v1/twice/")]);
    expect(calls).toHaveLength(1);
  });

  it("is not used for a write, for another address, or for a read that carries an abort signal", async () => {
    const calls = serve();
    await askAheadUrl("/api/v1/only-reads/");
    await api("/api/v1/only-reads/", { json: { a: 1 } });
    await api("/api/v1/other/");
    await api("/api/v1/only-reads/", { signal: new AbortController().signal });
    expect(calls.map((call) => `${call.init?.method ?? "GET"} ${call.url}`)).toEqual([
      "GET /api/v1/only-reads/",
      "POST /api/v1/only-reads/",
      "GET /api/v1/other/",
      "GET /api/v1/only-reads/",
    ]);
  });

  it("is forgotten when it fails, and the page asks for itself", async () => {
    let first = true;
    const calls = serve(() => {
      if (first) {
        first = false;
        return jsonResponse({ ok: false, error: "server" }, 500);
      }
      return jsonResponse({ ok: true, n: 2 });
    });
    await askAheadUrl("/api/v1/flaky/");
    expect(await api("/api/v1/flaky/")).toEqual({ ok: true, n: 2 });
    expect(calls).toHaveLength(2);
  });

  it("is dropped by a write, which changes what it was true of: the page asks for itself", async () => {
    const calls = serve();
    await askAheadUrl("/api/v1/list/");
    await api("/api/v1/save/", { json: { a: 1 } });
    await api("/api/v1/list/");
    expect(calls.map((call) => `${call.init?.method ?? "GET"} ${call.url}`)).toEqual(["GET /api/v1/list/", "POST /api/v1/save/", "GET /api/v1/list/"]);
  });

  it("is kept when the write fails (nothing changed)", async () => {
    const mocked = mockFetch({
      "/api/v1/save/": () => jsonResponse({ ok: false, error: "invalid" }, 400),
      "/api/v1/": () => jsonResponse({ ok: true }),
    });
    vi.stubGlobal("fetch", mocked.fn);
    const calls = mocked.calls;
    await askAheadUrl("/api/v1/kept/");
    await expect(api("/api/v1/save/", { json: { a: 1 } })).rejects.toThrow();
    await api("/api/v1/kept/").catch(() => undefined);
    expect(calls.filter((call) => call.url === "/api/v1/kept/")).toHaveLength(1);
  });

  it("goes stale after ten minutes: the page asks for itself", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    const calls = serve();
    await askAheadUrl("/api/v1/old/");
    vi.setSystemTime(Date.now() + 11 * 60 * 1000);
    await api("/api/v1/old/");
    expect(calls).toHaveLength(2);
  });

  it("says so when the page is opened on an answer that has had time to go stale", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    serve();
    const heard = vi.fn();
    window.addEventListener(AHEAD_AGED_EVENT, heard);
    await askAheadUrl("/api/v1/fresh/");
    await api("/api/v1/fresh/");
    expect(heard).not.toHaveBeenCalled();
    await askAheadUrl("/api/v1/aged/");
    vi.setSystemTime(Date.now() + 30_000);
    await api("/api/v1/aged/");
    expect(heard).toHaveBeenCalledTimes(1);
    window.removeEventListener(AHEAD_AGED_EVENT, heard);
  });
});
