import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, me, mockFetch } from "../test/helpers";
import { qk } from "./keys";
import { WARM, WARM_URLS, warmPages } from "./prefetch";
import { useMailThreads, useTasks } from "./queries";

afterEach(() => vi.unstubAllGlobals());

function newClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function serve() {
  const mocked = mockFetch({ "/api/v1/": () => jsonResponse({ ok: true, items: [], threads: [], next_before: null }) });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked.calls;
}

describe("warmPages", () => {
  const cases: [string, string][] = [
    ["/notifications", "/api/v1/notifications/?limit=20"],
    ["/translator", "/api/v1/translator/home/"],
    ["/tasks", "/api/v1/tasks/"],
    ["/team", "/api/v1/team/"],
    ["/inbox", "/api/v1/mail/threads/"],
    ["/lead", "/api/v1/lead/"],
    ["/lead/translators", "/api/v1/lead/translators/"],
    ["/admin", "/api/v1/admin/overview/"],
    ["/hr/employees", "/api/v1/hr/employees/"],
    ["/chats", "/api/v1/chats/?type=clients"],
  ];

  it("has a case for every address it warms", () => {
    expect(Object.keys(WARM).sort()).toEqual(cases.map(([path]) => path).sort());
  });

  it.each(cases)("%s asks for the first page of its list", async (path, url) => {
    const calls = serve();
    await warmPages(newClient(), [path], me());
    expect(calls.map((call) => call.url)).toEqual([url]);
  });

  it("puts what it fetched under the key the page's own hook reads", async () => {
    serve();
    const client = newClient();
    await warmPages(client, ["/tasks", "/inbox"], me());
    expect(client.getQueryData(qk.tasks(""))).toBeDefined();
    expect(client.getQueryData(qk.mail("", ""))).toBeDefined();
  });

  it("opens a page on the data it already has, with no loading in between", async () => {
    serve();
    const client = newClient();
    await warmPages(client, ["/tasks", "/inbox"], me());
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
    const tasks = renderHook(() => useTasks(""), { wrapper });
    const mail = renderHook(() => useMailThreads("", ""), { wrapper });
    expect(tasks.result.current.data).toBeDefined();
    expect(mail.result.current.data).toBeDefined();
    expect(tasks.result.current.isPending).toBe(false);
  });

  it("asks only for the addresses it is given: a person's own menu, nothing more", async () => {
    const calls = serve();
    await warmPages(newClient(), ["/tasks"], me());
    expect(calls.map((call) => call.url)).toEqual(["/api/v1/tasks/"]);
  });

  it("never warms a page that writes something when it is read", async () => {
    const calls = serve();
    // The client records and the client codes write an identity row at every GET; the attendance card settles days.
    const never = ["/clients", "/clients/CL-0001", "/admin/clients", "/admin/clients/new", "/attendance"];
    expect(never.filter((path) => Object.hasOwn(WARM, path) || Object.hasOwn(WARM_URLS, path))).toEqual([]);
    await warmPages(newClient(), never, me());
    expect(calls).toEqual([]);
  });

  it("does not mistake an inherited property for an address", async () => {
    const calls = serve();
    await warmPages(newClient(), ["constructor", "__proto__", "toString", ""], me());
    expect(calls).toEqual([]);
  });

  it("stops when it is told to, before the next address", async () => {
    const calls = serve();
    let asked = 0;
    await warmPages(newClient(), ["/tasks", "/team", "/inbox"], me(), () => asked++ >= 1);
    expect(calls.map((call) => call.url)).toEqual(["/api/v1/tasks/"]);
  });

  it("warms the chat list the chats page opens on: the first of the person's own kinds", async () => {
    const cases: [string[], string[]][] = [
      [["staff", "groups"], ["/api/v1/chats/?type=staff"]],
      [["groups"], ["/api/v1/chats/?type=groups"]],
      [["unknown", "clients"], ["/api/v1/chats/?type=clients"]],
      [[], []],
      [["unknown"], []],
    ];
    for (const [types, expected] of cases) {
      const calls = serve();
      await warmPages(newClient(), ["/chats"], { ...me(), chats: { types } });
      expect(calls.map((call) => call.url), types.join()).toEqual(expected);
    }
  });

  it("is a page that opens cold, not an error, when the server says no", async () => {
    vi.stubGlobal("fetch", mockFetch({ "/api/v1/": () => jsonResponse({ ok: false }, 500) }).fn);
    const client = newClient();
    await expect(warmPages(client, ["/tasks", "/team"], me())).resolves.toBeUndefined();
    expect(client.getQueryData(qk.tasks(""))).toBeUndefined();
  });
});

describe("WARM_URLS: the rest of the menu, by address", () => {
  it("asks for the address a page reads first, and only for a page of the person's menu", async () => {
    const calls = serve();
    await warmPages(newClient(), ["/accounts", "/hr/leave", "/not-in-the-lists"], me());
    expect(calls.map((call) => call.url)).toEqual(["/api/v1/accounts/overview/", "/api/v1/hr/leave/"]);
  });

  it("lists only reads of the API, and nothing the identity rule keeps from being read ahead", () => {
    for (const [path, urls] of Object.entries(WARM_URLS)) {
      expect(urls.length, path).toBeGreaterThan(0);
      for (const url of urls) {
        expect(url, path).toMatch(/^\/api\/v1\/[a-z0-9/-]+\/$/);
        expect(url, path).not.toMatch(/clients|^\/api\/v1\/attendance\/$/);
      }
    }
    // The HR board is the one attendance address listed: its read settles days the way the clock does (idempotent).
    expect(WARM_URLS["/hr/attendance"]).toEqual(["/api/v1/hr/attendance/"]);
  });

  it("takes what was asked ahead when the page asks for the same address, and asks the server once", async () => {
    const calls = serve();
    await warmPages(newClient(), ["/accounts/rules"], me());
    const { api } = await import("./client");
    await api("/api/v1/accounts/rules/");
    expect(calls.map((call) => call.url)).toEqual(["/api/v1/accounts/rules/"]);
  });
});
