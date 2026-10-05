import { screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ScreenKey } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { Shell } from "./Shell";

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute("dir");
  document.documentElement.removeAttribute("data-theme");
});

function open(role: Parameters<typeof me>[0], screens: ScreenKey[]) {
  const mocked = mockFetch({
    "/api/prefs/": () => jsonResponse({ ok: true }),
    "/api/v1/me/": () => jsonResponse(me(role, 0, screens)),
    "/api/v1/": () => jsonResponse({ ok: true, items: [], threads: [], next_before: null }),
  });
  vi.stubGlobal("fetch", mocked.fn);
  renderWithProviders(
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<div>home page</div>} />
      </Route>
    </Routes>,
  );
  return () => mocked.calls.map((call) => call.url);
}

describe("the pages of the menu are asked for in the background", () => {
  it("an operation person's lists are fetched without a click, and no page that writes when it is read", async () => {
    const asked = open({ role: "operation" }, ["operation", "chats"]);
    await screen.findByText("home page");
    await waitFor(() => expect(asked()).toContain("/api/v1/tasks/"), { timeout: 3000 });
    await waitFor(() => expect(asked()).toContain("/api/v1/chats/?type=clients"), { timeout: 3000 });
    expect(asked()).toEqual(expect.arrayContaining([
      "/api/v1/mail/threads/", "/api/v1/team/", "/api/v1/notifications/?limit=20",
    ]));
    // The client codes are in this person's menu, and are never warmed: opening them writes an identity row.
    expect(asked().filter((url) => url.startsWith("/api/v1/clients/"))).toEqual([]);
    expect(asked().filter((url) => url.startsWith("/api/v1/attendance/"))).toEqual([]);
  });

  it("a translator's desk is fetched, and not a page that is not in a translator's menu", async () => {
    const asked = open({ role: "translator" }, ["translator_home"]);
    await screen.findByText("home page");
    await waitFor(() => expect(asked()).toContain("/api/v1/translator/home/"), { timeout: 3000 });
    // Refused for a translator, and every refusal is written to the audit log.
    expect(asked().filter((url) => ["/api/v1/tasks/", "/api/v1/team/", "/api/v1/mail/threads/", "/api/v1/admin/overview/"].includes(url))).toEqual([]);
  });

  it("nothing is fetched ahead of time before the server has said who the person is", async () => {
    const mocked = mockFetch({
      "/api/prefs/": () => jsonResponse({ ok: true }),
      "/api/v1/me/": () => new Promise<Response>(() => undefined),
      "/api/v1/": () => jsonResponse({ ok: true }),
    });
    vi.stubGlobal("fetch", mocked.fn);
    renderWithProviders(
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<div>home page</div>} />
        </Route>
      </Routes>,
    );
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(mocked.calls.map((call) => call.url).filter((url) => !url.startsWith("/api/v1/me/") && !url.startsWith("/api/heartbeat"))).toEqual(
      expect.not.arrayContaining(["/api/v1/tasks/", "/api/v1/team/"]),
    );
  });
});
