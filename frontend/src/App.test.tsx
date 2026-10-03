import { act, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { PendingAssignment } from "./api/types";
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

  it("still sends a person whose check-in screen is due to the classic interface, with the accept screen waiting or not", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    const assign = vi.spyOn(navigation, "assign").mockImplementation(() => undefined);
    const server = serve();
    server.state.pending = PENDING;
    server.state.attendance = { kind: "check_in" };
    renderWithProviders(<App pollMs={4000} />, { route: "/payroll" });
    await beat(0);
    expect(assign).toHaveBeenCalledWith("/?classic=1");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
