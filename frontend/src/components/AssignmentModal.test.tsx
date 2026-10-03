import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { qk } from "../api/keys";
import type { PendingAssignment, Role } from "../api/types";
import { chime } from "../lib/chime";
import { navigation } from "../lib/navigation";
import { jsonResponse, mockFetch, renderWithProviders, type Routes as FetchRoutes } from "../test/helpers";
import { AssignmentModal } from "./AssignmentModal";
import { ToastProvider } from "./Toasts";

vi.mock("../lib/chime", () => ({ chime: vi.fn(), armSound: vi.fn(() => () => undefined), resetSound: vi.fn() }));

const ACCEPT = "/api/assignments/5/accept/";
const DECLINE = "/api/assignments/5/decline/";

function pending(overrides: Partial<PendingAssignment> = {}): PendingAssignment {
  return {
    id: 5,
    task_code: "TSK-00001",
    task_title: "Contract for review",
    task_url: "/tasks/TSK-00001/",
    client: "CL-0001",
    role: "translator" as Role,
    seconds_left: 60,
    window: 60,
    assigned_by: "Mona",
    files_url: "/assignments/5/",
    open_url: "/api/assignments/5/files/",
    priority: "normal",
    deadline: "2026-10-30 5:30 PM",
    deadline_iso: "2026-10-30T14:30:00+00:00",
    note: "Please take this one",
    ...overrides,
  };
}

function serve(routes: FetchRoutes = {}) {
  const mocked = mockFetch({ "/api/prefs/": () => jsonResponse({ ok: true }), ...routes });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

/** What the heartbeat says reaches the screen a moment later: the cache tells its watchers on a timer of its own. */
async function tell(view: ReturnType<typeof renderWithProviders>, value: PendingAssignment | null) {
  await act(async () => {
    view.client.setQueryData(qk.pending, value);
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function open(initial: PendingAssignment | null = pending(), options: { route?: string; lang?: "ar" | "en" } = {}) {
  const view = renderWithProviders(
    <ToastProvider>
      <AssignmentModal />
      <Routes>
        <Route path="/" element={<div>home page</div>} />
        <Route path="/tasks/:code" element={<div>task page</div>} />
        <Route path="/assignments/:id" element={<div>hand-off page</div>} />
      </Routes>
    </ToastProvider>,
    { route: options.route ?? "/", lang: options.lang },
  );
  if (initial) await tell(view, initial);
  return view;
}

const posts = (calls: { url: string; init?: RequestInit }[], path: string) => calls.filter((c) => c.url === path && c.init?.method === "POST");
const dialog = () => screen.queryByRole("dialog");

beforeEach(() => vi.mocked(chime).mockClear());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("AssignmentModal: what it shows", () => {
  it("is nothing while no hand-off waits", async () => {
    serve();
    await open(null);
    expect(dialog()).toBeNull();
    expect(chime).not.toHaveBeenCalled();
  });

  it("appears when the heartbeat says a hand-off waits, and goes when it says none does", async () => {
    serve();
    const view = await open();
    expect(dialog()).not.toBeNull();
    await tell(view, null);
    expect(dialog()).toBeNull();
  });

  it("shows the task, the client's code, who sent it, the date and the note", async () => {
    serve();
    await open();
    const box = within(screen.getByRole("dialog"));
    expect(box.getByText("تاسك جديدة ليك")).toBeInTheDocument();
    expect(box.getByText("TSK-00001 · Contract for review")).toBeInTheDocument();
    expect(box.getByText("CL-0001")).toBeInTheDocument();
    expect(box.getByText("Mona")).toBeInTheDocument();
    // The server writes the English time; an Arabic page shows ص / م.
    expect(box.getByText("2026-10-30 5:30 م")).toBeInTheDocument();
    expect(box.getByText("Please take this one")).toBeInTheDocument();
    expect(box.getByRole("timer")).toHaveTextContent("60");
  });

  it("says how long is left until the deadline, counted from now", async () => {
    serve();
    await open(pending({ deadline_iso: new Date(Date.now() + (2 * 1440 + 3 * 60 + 5) * 60000).toISOString() }));
    expect(screen.getByText(/باقي 2 يوم و3 ساعة على الديدلاين/)).toBeInTheDocument();
  });

  it("speaks English when asked", async () => {
    serve();
    await open(pending(), { lang: "en" });
    const box = within(screen.getByRole("dialog"));
    expect(box.getByText("A task is waiting for you")).toBeInTheDocument();
    expect(box.getByText("2026-10-30 5:30 PM")).toBeInTheDocument();
    expect(box.getByRole("button", { name: "Accept" })).toBeInTheDocument();
    expect(box.getByRole("button", { name: "Decline" })).toBeInTheDocument();
  });

  it("leaves out the note and the deadline when there are none", async () => {
    serve();
    await open(pending({ note: "", deadline: "", deadline_iso: "" }));
    expect(screen.queryByText("Please take this one")).toBeNull();
    expect(screen.getByText("الديدلاين").nextSibling).toHaveTextContent("—");
  });

  it("draws the words as text, never as markup", async () => {
    serve();
    await open(pending({ task_title: "<img src=x onerror=alert(1)>", note: "<b>bold</b>" }));
    expect(screen.getByText(/<img src=x onerror=alert\(1\)>/)).toBeInTheDocument();
    expect(document.querySelector(".modal img, .modal b")).toBeNull();
  });

  it("offers the job's own page to read first, which answers nothing", async () => {
    const mocked = serve();
    await open();
    expect(screen.getByRole("link", { name: /شوف الملفات والتفاصيل الأول/ })).toHaveAttribute("href", "/assignments/5");
    expect(mocked.calls.filter((c) => c.init?.method === "POST")).toHaveLength(0);
  });

  it("links the task only for an address on this site", async () => {
    serve();
    const view = await open();
    expect(screen.getByRole("link", { name: "افتح التاسك" })).toHaveAttribute("href", "/tasks/TSK-00001/");
    await tell(view, pending({ task_url: "https://evil.example/x" }));
    expect(screen.queryByRole("link", { name: "افتح التاسك" })).toBeNull();
  });
});

describe("AssignmentModal: sound and the clock", () => {
  beforeEach(() => vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] }));
  const advance = (ms: number) => act(() => void vi.advanceTimersByTime(ms));

  it("rings three times when it appears, and again at 20, 10 and 5 seconds - once each", async () => {
    serve();
    await open(pending({ seconds_left: 22 }));
    expect(chime).toHaveBeenCalledTimes(1);
    expect(chime).toHaveBeenCalledWith(3, 980);
    advance(2000); // 20
    expect(chime).toHaveBeenCalledTimes(2);
    expect(chime).toHaveBeenLastCalledWith(1, 1200);
    advance(10_000); // 10
    advance(5000); // 5
    expect(chime).toHaveBeenCalledTimes(4);
    advance(1000); // 4: nothing
    expect(chime).toHaveBeenCalledTimes(4);
  });

  it("turns the ring red from 15 seconds on, and shows how much of the window is left", async () => {
    serve();
    await open(pending({ seconds_left: 30, window: 60 }));
    const ring = screen.getByRole("timer");
    expect(ring).not.toHaveClass("is-critical");
    expect(ring.getAttribute("style")).toContain("--pct: 50");
    advance(15_000);
    expect(screen.getByRole("timer")).toHaveClass("is-critical");
    expect(screen.getByRole("timer")).toHaveTextContent("15");
  });

  it("goes when the window runs out, says what that cost, and does not come back for the same hand-off", async () => {
    serve();
    const view = await open(pending({ seconds_left: 3 }));
    advance(3000);
    expect(dialog()).toBeNull();
    expect(screen.getByText("عدى وقت الرد")).toBeInTheDocument();
    expect(screen.getByText("اتخصم من تقييمك.")).toBeInTheDocument();
    // The server has not swept yet and says it is still waiting: it is not drawn again.
    await tell(view, pending({ seconds_left: 0 }));
    expect(dialog()).toBeNull();
    // A different hand-off is.
    await tell(view, pending({ id: 6, seconds_left: 60 }));
    expect(dialog()).not.toBeNull();
  });

  it("shows nothing but the expiry for a hand-off that was already out of time when it was told", async () => {
    serve();
    await open(pending({ seconds_left: 0 }));
    expect(dialog()).toBeNull();
    expect(screen.getByText("عدى وقت الرد")).toBeInTheDocument();
  });
});

describe("AssignmentModal: accepting", () => {
  it("sends the accept, says so, closes, and takes a translator to the task in this app", async () => {
    const mocked = serve({ [ACCEPT]: () => jsonResponse({ ok: true, reason: "accepted", task: "TSK-00001" }) });
    await open();
    fireEvent.click(screen.getByRole("button", { name: "استلمت" }));
    expect(await screen.findByText("تم الاستلام")).toBeInTheDocument();
    expect(await screen.findByText("task page")).toBeInTheDocument();
    expect(dialog()).toBeNull();
    const [call] = posts(mocked.calls, ACCEPT);
    expect(String(call!.init!.body)).toBe("");
    expect(new Headers(call!.init!.headers).get("X-CSRFToken")).toBeDefined();
  });

  it("takes anybody else to the classic task page instead, for an address on this site", async () => {
    const assign = vi.spyOn(navigation, "assign").mockImplementation(() => undefined);
    serve({ [ACCEPT]: () => jsonResponse({ ok: true, reason: "accepted", task: "TSK-00001" }) });
    await open(pending({ role: "team_lead" }));
    fireEvent.click(screen.getByRole("button", { name: "استلمت" }));
    await screen.findByText("تم الاستلام");
    expect(assign).toHaveBeenCalledWith("/tasks/TSK-00001/");
    expect(screen.queryByText("task page")).toBeNull();
  });

  it("does not follow a task address that leaves the site", async () => {
    const assign = vi.spyOn(navigation, "assign").mockImplementation(() => undefined);
    serve({ [ACCEPT]: () => jsonResponse({ ok: true, reason: "accepted", task: "x" }) });
    await open(pending({ role: "team_lead", task_url: "https://evil.example/x" }));
    fireEvent.click(screen.getByRole("button", { name: "استلمت" }));
    await screen.findByText("تم الاستلام");
    expect(assign).toHaveBeenCalledWith("/");
  });

  it("says it was too late when the server says so, and does not go to the task", async () => {
    serve({ [ACCEPT]: () => jsonResponse({ ok: false, reason: "expired", task: "TSK-00001" }) });
    await open();
    fireEvent.click(screen.getByRole("button", { name: "استلمت" }));
    expect(await screen.findByText("الوقت خلص")).toBeInTheDocument();
    expect(screen.getByText("التاسك رجعت لمين بعتها.")).toBeInTheDocument();
    expect(dialog()).toBeNull();
    expect(screen.queryByText("task page")).toBeNull();
  });

  it("is not 'too late' when it was already accepted - a second tab, a double press", async () => {
    serve({ [ACCEPT]: () => jsonResponse({ ok: false, reason: "accepted", task: "TSK-00001" }) });
    await open();
    fireEvent.click(screen.getByRole("button", { name: "استلمت" }));
    expect(await screen.findByText("تم الاستلام")).toBeInTheDocument();
    expect(await screen.findByText("task page")).toBeInTheDocument();
    expect(screen.queryByText("الوقت خلص")).toBeNull();
  });

  it("is too late for somebody else's hand-off or one that was cancelled", async () => {
    for (const reason of ["forbidden", "cancelled", "declined"]) {
      const view = await open(pending({ id: 5 }));
      vi.unstubAllGlobals();
      serve({ [ACCEPT]: () => jsonResponse({ ok: false, reason, task: "TSK-00001" }) });
      fireEvent.click(screen.getByRole("button", { name: "استلمت" }));
      expect(await screen.findByText("الوقت خلص"), reason).toBeInTheDocument();
      view.unmount();
    }
  });

  it("is not sure, rather than failed, when nothing came back: it stays, and can be pressed again", async () => {
    serve({ [ACCEPT]: () => Promise.reject(new TypeError("network down")) });
    await open();
    fireEvent.click(screen.getByRole("button", { name: "استلمت" }));
    expect(await screen.findByText("مش متأكدين إن الاستلام تم")).toBeInTheDocument();
    expect(dialog()).not.toBeNull();
    expect(screen.getByRole("button", { name: "استلمت" })).toBeEnabled();
    expect(screen.queryByText("الوقت خلص")).toBeNull();
  });

  it("is not sure, rather than failed, when the server failed", async () => {
    serve({ [ACCEPT]: () => jsonResponse({ ok: false, error: "server" }, 500) });
    await open();
    fireEvent.click(screen.getByRole("button", { name: "استلمت" }));
    expect(await screen.findByText("مش متأكدين إن الاستلام تم")).toBeInTheDocument();
    expect(dialog()).not.toBeNull();
  });

  it("sends one accept for a double press", async () => {
    let release: (response: Response) => void = () => undefined;
    const mocked = serve({ [ACCEPT]: () => new Promise<Response>((resolve) => (release = resolve)) });
    await open();
    const accept = screen.getByRole("button", { name: "استلمت" });
    fireEvent.click(accept);
    fireEvent.click(accept);
    expect(accept).toBeDisabled();
    expect(screen.getByRole("button", { name: "رفض" })).toBeDisabled();
    expect(posts(mocked.calls, ACCEPT)).toHaveLength(1);
    await act(async () => release(jsonResponse({ ok: true, reason: "accepted", task: "TSK-00001" })));
    await screen.findByText("task page");
  });
});

describe("AssignmentModal: declining", () => {
  const reasonBox = () => screen.getByLabelText("سبب الرفض (لازم لو هترفض)");

  it("asks why first, sends nothing without a reason, and puts the cursor in the box", async () => {
    const mocked = serve();
    await open();
    fireEvent.click(screen.getByRole("button", { name: "رفض" }));
    expect(screen.getByText("اكتب سبب الرفض")).toBeInTheDocument();
    expect(screen.getByText("اللي بعتلك محتاج يعرف يعمل إيه بعد كده.")).toBeInTheDocument();
    expect(posts(mocked.calls, DECLINE)).toHaveLength(0);
    await waitFor(() => expect(document.activeElement).toBe(reasonBox()));
    // Spaces are no reason.
    fireEvent.change(reasonBox(), { target: { value: "    " } });
    fireEvent.click(screen.getByRole("button", { name: "رفض" }));
    expect(posts(mocked.calls, DECLINE)).toHaveLength(0);
  });

  it("sends the reason, trimmed, and closes", async () => {
    const mocked = serve({ [DECLINE]: () => jsonResponse({ ok: true, error: "", task: "TSK-00001" }) });
    await open();
    fireEvent.change(reasonBox(), { target: { value: "  Busy with another file " } });
    fireEvent.click(screen.getByRole("button", { name: "رفض" }));
    expect(await screen.findByText("اتبعت الرفض")).toBeInTheDocument();
    expect(dialog()).toBeNull();
    expect(Object.fromEntries(new URLSearchParams(String(posts(mocked.calls, DECLINE)[0]!.init!.body)))).toEqual({ reason: "Busy with another file" });
  });

  it("says the server's own sentence when it refuses, and stays", async () => {
    serve({ [DECLINE]: () => jsonResponse({ ok: false, error: "التسليمة دي مش مستنية ردك.", task: "TSK-00001" }, 400) });
    await open();
    fireEvent.change(reasonBox(), { target: { value: "Busy" } });
    fireEvent.click(screen.getByRole("button", { name: "رفض" }));
    expect(await screen.findByText("مقدرتش أرفض")).toBeInTheDocument();
    expect(screen.getByText("التسليمة دي مش مستنية ردك.")).toBeInTheDocument();
    expect(dialog()).not.toBeNull();
    expect(screen.getByRole("button", { name: "رفض" })).toBeEnabled();
  });

  it("is not told the hand-off is gone when the decline could not be sent", async () => {
    serve({ [DECLINE]: () => Promise.reject(new TypeError("network down")) });
    await open();
    fireEvent.change(reasonBox(), { target: { value: "Busy" } });
    fireEvent.click(screen.getByRole("button", { name: "رفض" }));
    expect(await screen.findByText("مقدرتش أرفض")).toBeInTheDocument();
    expect(dialog()).not.toBeNull();
  });
});

describe("AssignmentModal: where it is drawn", () => {
  it("is not drawn on the hand-off's own page, which has the same countdown and buttons", async () => {
    serve();
    await open(pending({ id: 5 }), { route: "/assignments/5" });
    expect(screen.getByText("hand-off page")).toBeInTheDocument();
    expect(dialog()).toBeNull();
  });

  it("is drawn over another hand-off's page, and over every other page", async () => {
    serve();
    await open(pending({ id: 5 }), { route: "/assignments/9" });
    expect(dialog()).not.toBeNull();
  });

  it("is drawn over the desk and the task page too", async () => {
    serve();
    await open(pending(), { route: "/tasks/TSK-00002" });
    expect(dialog()).not.toBeNull();
  });
});
