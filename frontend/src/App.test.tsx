import { QueryClient } from "@tanstack/react-query";
import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { qk } from "./api/keys";
import type { PendingAssignment } from "./api/types";
import { calls } from "./lib/calls";
import { navigation } from "./lib/navigation";
import { jsonResponse, me, mockFetch, renderWithProviders } from "./test/helpers";

vi.mock("./lib/chime", () => ({ chime: vi.fn(), armSound: vi.fn(() => () => undefined), resetSound: vi.fn() }));

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const PENDING: PendingAssignment = {
  id: 5,
  task_code: "TSK-00001",
  task_title: "Contract for review",
  task_url: "/tasks/TSK-00001/",
  client: "CL-0001",
  role: "translator",
  seconds_left: 60,
  window: 60,
  assigned_by: "Mona",
  files_url: "/assignments/5/",
  open_url: "/api/assignments/5/files/",
  priority: "normal",
  deadline: "2026-10-30 5:30 PM",
  deadline_iso: "2026-10-30T14:30:00+00:00",
  note: "",
};

/** What the old heartbeat endpoint answers, changed between beats. */
function serve() {
  const state: { pending: PendingAssignment | null; attendance: { kind: string } | null } = { pending: null, attendance: null };
  const mocked = mockFetch({
    "/api/prefs/": () => jsonResponse({ ok: true }),
    "/api/v1/me/": () => jsonResponse(me({ role: "translator" }, 0, ["translator_home"])),
    "/api/heartbeat/": () => jsonResponse({ ok: true, attendance: state.attendance, pending: state.pending, call: null, live: "a" }),
  });
  vi.stubGlobal("fetch", mocked.fn);
  return { ...mocked, state };
}

const beat = (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)));

describe("App: the accept screen is wired to the heartbeat", () => {
  it("draws the accept screen over the page a beat after an assignment arrives, and takes it away a beat after it is answered", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    const server = serve();
    renderWithProviders(<App pollMs={4000} />, { route: "/payroll" });
    await beat(0);
    expect(screen.queryByRole("dialog")).toBeNull();

    server.state.pending = PENDING;
    await beat(4000);
    expect(await screen.findByRole("dialog")).toHaveTextContent("TSK-00001 · Contract for review");

    // Answered somewhere else (the classic page, another tab): the next beat says nothing waits.
    server.state.pending = null;
    await beat(4000);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("does not send a person with a waiting assignment away to the classic interface", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    const assign = vi.spyOn(navigation, "assign").mockImplementation(() => undefined);
    const server = serve();
    server.state.pending = PENDING;
    renderWithProviders(<App pollMs={4000} />, { route: "/payroll" });
    await beat(0);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
  });

});

describe("App: the check-in screen is wired to the heartbeat", () => {
  const GATE = {
    kind: "check_in",
    date: "2026-09-21",
    shift: "9:00 ص - 5:00 م",
    start: { ar: "9:00 ص", en: "9:00 AM" },
    end: { ar: "5:00 م", en: "5:00 PM" },
    grace_until: { ar: "9:10 ص", en: "9:10 AM" },
    grace: 10,
    late_now: 0,
    needs_location: false,
    checkout_after: 60,
  };

  function serveGate(state: { gate: unknown; screen: boolean }) {
    const mocked = mockFetch({
      "/api/prefs/": () => jsonResponse({ ok: true }),
      "/api/v1/me/": () => jsonResponse(me({ role: "translator" }, 0, ["attendance"])),
      "/api/v1/attendance/": () => jsonResponse({ ok: false, error: "x" }, 500),
      "/api/heartbeat/": () => jsonResponse({ ok: true, attendance: state.gate, attendance_screen: state.screen, pending: null, call: null, live: "a" }),
    });
    vi.stubGlobal("fetch", mocked.fn);
    return mocked;
  }

  it("opens over the page a beat after the shift starts, and goes a beat after the check-in, without leaving the app", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    const assign = vi.spyOn(navigation, "assign").mockImplementation(() => undefined);
    const state = { gate: null as unknown, screen: true };
    serveGate(state);
    renderWithProviders(<App pollMs={4000} />, { route: "/payroll" });
    await beat(0);
    expect(screen.queryByRole("dialog")).toBeNull();

    state.gate = GATE;
    await beat(4000);
    expect(await screen.findByRole("dialog", { name: "سجّل حضورك" })).toBeInTheDocument();
    expect(document.querySelector(".shell")).toHaveAttribute("inert");

    // Checked in on another device: the next beat says nothing is asked.
    state.gate = null;
    await beat(4000);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.querySelector(".shell")).not.toHaveAttribute("inert");
    expect(assign).not.toHaveBeenCalled();
  });

  it("shows what the page that carried the app asked on the first paint, before any beat", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(qk.gate, GATE);
    serveGate({ gate: GATE, screen: true });
    renderWithProviders(<App pollMs={4000} />, { route: "/payroll", client });
    expect(screen.getByRole("dialog", { name: "سجّل حضورك" })).toBeInTheDocument();
  });
});

describe("App: a call that rings is drawn by this app", () => {
  function serveCall(state: { call: unknown }) {
    const mocked = mockFetch({
      "/api/prefs/": () => jsonResponse({ ok: true }),
      "/api/v1/me/": () => jsonResponse(me({ role: "translator" }, 0, ["translator_home"])),
      "/api/heartbeat/": () => jsonResponse({ ok: true, attendance: null, pending: null, call: state.call, live: "a" }),
      "/api/calls/": () => jsonResponse({ ok: true, call: { id: 9, status: "ringing", video: false, caller: false, other: "Sam", initials: "SA", answered_at: "" }, signals: [] }),
    });
    vi.stubGlobal("fetch", mocked.fn);
    return mocked;
  }

  it("rings over the page a beat after the call comes in, without leaving the app", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    const assign = vi.spyOn(navigation, "assign").mockImplementation(() => undefined);
    const state = { call: null as unknown };
    serveCall(state);
    calls.reset();
    renderWithProviders(<App pollMs={4000} />, { route: "/payroll" });
    await beat(0);
    expect(screen.queryByRole("dialog", { name: "Sam" })).toBeNull();

    state.call = { id: 9, video: true, from: "Sam", initials: "SA", chat_url: "/ops/chats/u/4/" };
    await beat(4000);
    expect(await screen.findByRole("dialog", { name: "Sam" })).toHaveAttribute("data-phase", "incoming");
    expect(screen.getByText("مكالمة فيديو جاية…")).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
    calls.reset();
  });
});
