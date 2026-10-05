import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AssignmentResponse, Role } from "../api/types";
import { ToastProvider } from "../components/Toasts";
import { jsonResponse, me, mockFetch, renderWithProviders, type Routes as FetchRoutes } from "../test/helpers";
import { AssignmentPage } from "./AssignmentPage";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const DOOR = "/api/v1/assignments/5/";
const FILES = "/api/assignments/5/files/";
const ACCEPT = "/api/assignments/5/accept/";
const DECLINE = "/api/assignments/5/decline/";

function handoff(over: { assignment?: Partial<AssignmentResponse["assignment"]>; task?: Partial<AssignmentResponse["task"]> } = {}): AssignmentResponse {
  return {
    ok: true,
    assignment: {
      id: 5,
      status: "pending",
      pending: true,
      seconds_left: 45,
      window: 60,
      role: "translator" as Role,
      note: "Please take this one",
      from: "Mona",
      mine: true,
      ...over.assignment,
    },
    task: {
      code: "TSK-00001",
      title: "Contract for review",
      origin: { value: "whatsapp", icon: "message", ar: "واتساب", en: "WhatsApp" },
      client: "CL-0001",
      source_lang: "English",
      target_lang: "Arabic",
      due: { ar: "2026-10-30 5:30 PM", en: "2026-10-30 5:30 PM" },
      due_iso: new Date(Date.now() + 50 * 3600 * 1000).toISOString(),
      description: "Translate pages 2-4\nKeep the table",
      files: [
        { id: 1, url: "/files/in/contract.pdf", name: "contract.pdf", size: "2.0 KB", image: false },
        { id: 2, url: "/files/in/photo.png", name: "photo.png", size: "10 B", image: true },
      ],
      ...over.task,
    },
  };
}

function serve(body: AssignmentResponse | Response, extra: FetchRoutes = {}) {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role: "translator" })),
    [DOOR]: () => (body instanceof Response ? body : jsonResponse(body)),
    [FILES]: () => jsonResponse({ ok: true, url: "/assignments/5/" }),
    ...extra,
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function open(route = "/assignments/5", lang: "ar" | "en" = "ar") {
  return renderWithProviders(
    <ToastProvider>
      <Routes>
        <Route path="/assignments/:id" element={<AssignmentPage />} />
        <Route path="/tasks/:code" element={<div>task page</div>} />
      </Routes>
    </ToastProvider>,
    { route, lang },
  );
}

const loaded = () => screen.findByText(/Contract for review/);
const posts = (calls: { url: string; init?: RequestInit }[], path: string) => calls.filter((c) => c.url === path && c.init?.method === "POST");

describe("AssignmentPage: reading the job before taking it", () => {
  it("shows the job: title, code, the client's code, languages, who sent it and the date", async () => {
    serve(handoff());
    const { container } = open();
    await loaded();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Contract for review");
    expect(screen.getByText("واتساب")).toBeInTheDocument();
    expect(container.querySelector(".page-head__sub")).toHaveTextContent("TSK-00001 · CL-0001 · English → Arabic");
    const side = container.querySelector(".sticky-side .card") as HTMLElement;
    expect(within(side).getByText("Mona")).toBeInTheDocument();
    expect(within(side).getByText("2026-10-30 5:30 PM")).toBeInTheDocument();
    // How long is left until the deadline, counted from now.
    expect(within(side).getByText(/باقي 2 يوم و\d+ ساعة على الديدلاين/)).toBeInTheDocument();
  });

  it("speaks English when asked", async () => {
    serve(handoff());
    open("/assignments/5", "en");
    expect(await screen.findByText("Task files")).toBeInTheDocument();
    expect(screen.getByText("2026-10-30 5:30 PM")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept" })).toBeInTheDocument();
    expect(screen.getByText(/days .* left until the deadline/)).toBeInTheDocument();
  });

  it("lists the files: links that open on their own, pictures as pictures, and how many", async () => {
    serve(handoff());
    const { container } = open();
    const pdf = await screen.findByRole("link", { name: /contract\.pdf/ });
    expect(pdf).toHaveAttribute("href", "/files/in/contract.pdf");
    expect(pdf).toHaveAttribute("target", "_blank");
    expect(pdf.getAttribute("rel")).toContain("noopener");
    expect(container.querySelector('a.preview-file--img img[alt="photo.png"]')?.getAttribute("src")).toBe("/files/in/photo.png");
    expect(screen.getByText("ملفات التاسك").parentElement).toHaveTextContent("2");
    expect(screen.getByText("2.0 KB")).toBeInTheDocument();
  });

  it("draws a file only as a link to this site, and still names it", async () => {
    serve(handoff({ task: { files: [{ id: 1, url: "https://evil.example/a.pdf", name: "outside.pdf", size: "1 B", image: false }, { id: 2, url: "javascript:alert(1)", name: "script.png", size: "1 B", image: true }] } }));
    const { container } = open();
    expect(await screen.findByText("outside.pdf")).toBeInTheDocument();
    expect(screen.getByText("script.png")).toBeInTheDocument();
    expect(container.querySelector(".preview-files a")).toBeNull();
    expect(container.querySelector(".preview-files img")).toBeNull();
  });

  it("says so when the task has no files and no description", async () => {
    serve(handoff({ task: { files: [], description: "" } }));
    open();
    expect(await screen.findByText("التاسك دي مفيهاش ملفات من العميل.")).toBeInTheDocument();
    expect(screen.getByText("مفيش وصف مكتوب.")).toBeInTheDocument();
  });

  it("shows the brief with its line breaks, and the sender's note beside who wrote it", async () => {
    serve(handoff());
    const { container } = open();
    await loaded();
    const brief = screen.getByText(/Translate pages 2-4/);
    expect(brief).toHaveStyle({ whiteSpace: "pre-wrap" });
    expect(brief.textContent).toBe("Translate pages 2-4\nKeep the table");
    const note = container.querySelector(".note") as HTMLElement;
    expect(note).toHaveTextContent("MonaPlease take this one");
  });

  it("draws the words as text, never as markup", async () => {
    serve(handoff({ task: { title: "<img src=x onerror=alert(1)>", description: "<b>x</b>" } }));
    const { container } = open();
    expect(await screen.findByText(/<img src=x onerror=alert\(1\)>/)).toBeInTheDocument();
    expect(container.querySelector("h1 img, .msg-item__text b")).toBeNull();
  });

  it("has no date to count to when there is none", async () => {
    serve(handoff({ task: { due: null, due_iso: "" } }));
    const { container } = open();
    await loaded();
    expect(container.querySelector(".deadline-left")).toBeNull();
    expect(screen.getByText("الديدلاين").nextSibling).toHaveTextContent("—");
  });

  it("says how late the deadline already is, in red", async () => {
    serve(handoff({ task: { due_iso: new Date(Date.now() - 3 * 3600 * 1000).toISOString() } }));
    const { container } = open();
    await loaded();
    expect(container.querySelector(".deadline-left.is-late")).toHaveTextContent(/الديدلاين فات من 3 ساعة/);
  });

  it("says it is not available when it is not the person's, and when the id is not a number - asking nothing for the second", async () => {
    serve(jsonResponse({ ok: false, error: "not_found" }, 404));
    open();
    expect(await screen.findByRole("alert")).toHaveTextContent("التسليم ده مش متاح ليك.");
    vi.unstubAllGlobals();
    const mocked = serve(handoff());
    open("/assignments/abc");
    await waitFor(() => expect(screen.getAllByRole("alert").length).toBeGreaterThan(0));
    expect(mocked.calls.some((c) => c.url.startsWith("/api/v1/assignments/"))).toBe(false);
  });

  it("says it could not load on a server failure", async () => {
    serve(jsonResponse({ ok: false, error: "server" }, 500));
    open();
    expect(await screen.findByRole("alert")).toHaveTextContent("حصلت مشكلة في التحميل.");
  });
});

describe("AssignmentPage: looking is recorded, answering is not", () => {
  it("says the files were opened with a POST of its own, once, while the hand-off waits for this person", async () => {
    const mocked = serve(handoff());
    open();
    await loaded();
    await waitFor(() => expect(posts(mocked.calls, FILES)).toHaveLength(1));
    expect(posts(mocked.calls, ACCEPT)).toHaveLength(0);
    expect(posts(mocked.calls, DECLINE)).toHaveLength(0);
    // A later read of the same page does not say it again.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(posts(mocked.calls, FILES)).toHaveLength(1);
  });

  it("does not say it when the hand-off is closed, or is somebody else's", async () => {
    const closed = serve(handoff({ assignment: { status: "accepted", pending: false } }));
    open();
    await loaded();
    expect(posts(closed.calls, FILES)).toHaveLength(0);
    vi.unstubAllGlobals();
    document.body.innerHTML = "";

    const others = serve(handoff({ assignment: { mine: false } }));
    open();
    await loaded();
    expect(posts(others.calls, FILES)).toHaveLength(0);
  });
});

describe("AssignmentPage: the decision", () => {
  const reasonBox = () => screen.getByLabelText("سبب الرفض (لازم لو هترفض)");

  it("shows the time left and the two buttons while it waits for this person", async () => {
    serve(handoff());
    open();
    await loaded();
    expect(screen.getByRole("timer")).toHaveTextContent("45s");
    expect(screen.getByRole("button", { name: "استلمت" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "رفض" })).toBeEnabled();
    expect(screen.getByText("فتح الصفحة دي مش استلام — العداد لسه شغال.")).toBeInTheDocument();
  });

  it("counts the seconds down on its own", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    serve(handoff());
    open();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(screen.getByRole("timer")).toHaveTextContent("45s");
    act(() => void vi.advanceTimersByTime(5000));
    expect(screen.getByRole("timer")).toHaveTextContent("40s");
  });

  it("reads the hand-off again, and says what it cost, when the window runs out on the page", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    const mocked = serve(handoff({ assignment: { seconds_left: 2 } }));
    open();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    const before = mocked.calls.filter((c) => c.url === DOOR).length;
    act(() => void vi.advanceTimersByTime(2000));
    expect(await screen.findByText("عدى وقت الرد")).toBeInTheDocument();
    await waitFor(() => expect(mocked.calls.filter((c) => c.url === DOOR).length).toBeGreaterThan(before));
  });

  it("accepts, says so, and takes a translator to the task", async () => {
    const mocked = serve(handoff(), { [ACCEPT]: () => jsonResponse({ ok: true, reason: "accepted", task: "TSK-00001" }) });
    open();
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "استلمت" }));
    expect(await screen.findByText("task page")).toBeInTheDocument();
    expect(screen.getByText("تم الاستلام")).toBeInTheDocument();
    expect(posts(mocked.calls, ACCEPT)).toHaveLength(1);
  });

  it("says it was too late when the server says so, and stays on the page", async () => {
    serve(handoff(), { [ACCEPT]: () => jsonResponse({ ok: false, reason: "expired", task: "TSK-00001" }) });
    open();
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "استلمت" }));
    expect(await screen.findByText("الوقت خلص")).toBeInTheDocument();
    expect(screen.queryByText("task page")).toBeNull();
  });

  it("asks why before it declines, and sends the reason trimmed", async () => {
    const mocked = serve(handoff(), { [DECLINE]: () => jsonResponse({ ok: true, error: "", task: "TSK-00001" }) });
    open();
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "رفض" }));
    expect(screen.getByText("اكتب سبب الرفض")).toBeInTheDocument();
    expect(posts(mocked.calls, DECLINE)).toHaveLength(0);
    await waitFor(() => expect(document.activeElement).toBe(reasonBox()));
    fireEvent.change(reasonBox(), { target: { value: "  Not my field " } });
    fireEvent.click(screen.getByRole("button", { name: "رفض" }));
    expect(await screen.findByText("اتبعت الرفض")).toBeInTheDocument();
    expect(Object.fromEntries(new URLSearchParams(String(posts(mocked.calls, DECLINE)[0]!.init!.body)))).toEqual({ reason: "Not my field" });
  });

  it("reads the hand-off again after an answer, and shows it closed", async () => {
    const state = { body: handoff() };
    const mocked = serve(state.body, {
      [DOOR]: () => jsonResponse(state.body),
      [DECLINE]: () => {
        state.body = handoff({ assignment: { status: "declined", pending: false } });
        return jsonResponse({ ok: true, error: "", task: "TSK-00001" });
      },
    });
    open();
    await loaded();
    fireEvent.change(reasonBox(), { target: { value: "Busy" } });
    fireEvent.click(screen.getByRole("button", { name: "رفض" }));
    expect(await screen.findByText("التسليم ده اتقفل (اتستلم أو اترفض أو الوقت خلص).")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "استلمت" })).toBeNull();
    expect(mocked.calls.filter((c) => c.url === DOOR).length).toBeGreaterThan(1);
  });
});

describe("AssignmentPage: a hand-off that is not waiting for this person", () => {
  it("has no buttons once closed, and a way to the task when it was accepted", async () => {
    serve(handoff({ assignment: { status: "accepted", pending: false } }));
    open();
    await loaded();
    expect(screen.getByText("التسليم ده اتقفل (اتستلم أو اترفض أو الوقت خلص).")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "استلمت" })).toBeNull();
    expect(screen.getByRole("link", { name: /افتح التاسك/ })).toHaveAttribute("href", "/tasks/TSK-00001");
  });

  it("has no way to the task when it was declined, expired or cancelled", async () => {
    for (const status of ["declined", "expired", "cancelled"] as const) {
      serve(handoff({ assignment: { status, pending: false } }));
      const view = open();
      await loaded();
      expect(screen.queryByRole("link", { name: /افتح التاسك/ }), status).toBeNull();
      view.unmount();
      vi.unstubAllGlobals();
    }
  });

  it("is read only for the admin looking at somebody else's, with no buttons", async () => {
    serve(handoff({ assignment: { mine: false } }));
    open();
    await loaded();
    expect(screen.getByText("التسليم ده لمستخدم تاني: للقراءة بس.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "استلمت" })).toBeNull();
    expect(screen.queryByRole("button", { name: "رفض" })).toBeNull();
  });
});
