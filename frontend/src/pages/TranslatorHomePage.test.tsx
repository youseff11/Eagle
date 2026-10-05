import { screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DeskTask, Role, TranslatorHomeResponse } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders, type Routes as FetchRoutes } from "../test/helpers";
import { TranslatorHomePage } from "./TranslatorHomePage";

afterEach(() => vi.unstubAllGlobals());

function task(code: string, overrides: Partial<DeskTask> = {}): DeskTask {
  return {
    code,
    title: `Title of ${code}`,
    status: { value: "in_progress", tone: "work", ar: "شغل جاري", en: "In progress" },
    priority: { value: "high", ar: "عالية", en: "High" },
    origin: { value: "whatsapp", icon: "message", ar: "واتساب", en: "WhatsApp" },
    client: "CL-0001",
    source_lang: "English",
    target_lang: "Arabic",
    due: { ar: "2026-10-02 5:30 PM", en: "2026-10-02 5:30 PM" },
    due_state: "ok",
    can_ask_more_time: true,
    url: `/tasks/${code}/`,
    ...overrides,
  };
}

function desk(overrides: Partial<TranslatorHomeResponse> = {}): TranslatorHomeResponse {
  return {
    ok: true,
    rating: 4.875,
    open: [task("TSK-00001")],
    done: [{ code: "TSK-00009", status: { value: "delivered", tone: "done", ar: "تم التسليم", en: "Delivered" }, url: "/tasks/TSK-00009/" }],
    rating_events: [{ delta: "-0.125", reason_ar: "ما ردّش في الوقت", reason_en: "Missed the window" }],
    ...overrides,
  };
}

function serve(body: TranslatorHomeResponse | Response, extra: FetchRoutes = {}, role: Role = "translator") {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role, is_admin: role === "admin" })),
    "/api/v1/translator/home/": () => (body instanceof Response ? body : jsonResponse(body)),
    ...extra,
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

describe("TranslatorHomePage", () => {
  it("lists the open task the way the classic page does, in Arabic", async () => {
    serve(desk());
    const { container } = renderWithProviders(<TranslatorHomePage />, { lang: "ar" });
    expect(await screen.findByText("TSK-00001")).toBeInTheDocument();
    const row = container.querySelector('[data-task="TSK-00001"]') as HTMLElement;
    expect(within(row).getByText("Title of TSK-00001")).toBeInTheDocument();
    expect(within(row).getByText("شغل جاري")).toBeInTheDocument();
    expect(within(row).getByText("عالية")).toBeInTheDocument();
    expect(within(row).getByText("واتساب")).toBeInTheDocument();
    expect(within(row).getByText(/2026-10-02 5:30 PM/)).toBeInTheDocument();
    expect(row).toHaveTextContent("CL-0001 · English → Arabic");
    // The task page is a route of this app now, made from the code.
    expect(within(row).getByRole("link", { name: /افتح التاسك/ })).toHaveAttribute("href", "/tasks/TSK-00001");
    expect(within(row).getByRole("link", { name: /اطلب وقت أطول/ })).toHaveAttribute("href", "/tasks/TSK-00001#more-time");
  });

  it("speaks English when asked, with the server's own English time", async () => {
    serve(desk());
    const { container } = renderWithProviders(<TranslatorHomePage />, { lang: "en" });
    expect(await screen.findByText("TSK-00001")).toBeInTheDocument();
    const row = container.querySelector('[data-task="TSK-00001"]') as HTMLElement;
    expect(within(row).getByText("In progress")).toBeInTheDocument();
    expect(within(row).getByText(/2026-10-02 5:30 PM/)).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: /Ask for more time/ })).toBeInTheDocument();
    expect(screen.getByText("My work")).toBeInTheDocument();
    expect(screen.getByText("Missed the window")).toBeInTheDocument();
    expect(screen.queryByText("ما ردّش في الوقت")).not.toBeInTheDocument();
  });

  it("shows the rating as the classic star readout does", async () => {
    serve(desk({ rating: 4.875 }));
    const { container } = renderWithProviders(<TranslatorHomePage />);
    await screen.findByText("TSK-00001");
    const rating = container.querySelector(".rating") as HTMLElement;
    expect(rating).toHaveAttribute("title", "4.875 / 5");
    expect(rating).toHaveTextContent("4.88/5");
    expect(rating.querySelector(".ic--fill")).not.toBeNull();
  });

  it("offers more time only on a task that is in progress", async () => {
    serve(desk({ open: [task("TSK-00001"), task("TSK-00002", { can_ask_more_time: false })] }));
    renderWithProviders(<TranslatorHomePage />);
    await screen.findByText("TSK-00002");
    expect(screen.getAllByRole("link", { name: /اطلب وقت أطول/ })).toHaveLength(1);
  });

  it("says there is no deadline instead of showing an empty date", async () => {
    serve(desk({ open: [task("TSK-00001", { due: null, due_state: "none" })] }));
    renderWithProviders(<TranslatorHomePage />);
    expect(await screen.findByText("من غير ديدلاين")).toBeInTheDocument();
  });

  it("colours the deadline by the state the server worked out, and does no time arithmetic of its own", async () => {
    serve(desk({ open: [task("TSK-00001", { due_state: "late" }), task("TSK-00002", { due_state: "soon" })] }));
    const { container } = renderWithProviders(<TranslatorHomePage />);
    await screen.findByText("TSK-00002");
    expect(container.querySelector('[data-task="TSK-00001"] .deadline--late')).not.toBeNull();
    expect(container.querySelector('[data-task="TSK-00002"] .deadline--soon')).not.toBeNull();
  });

  it("makes the task link from the code: whatever address the server wrote is never used", async () => {
    serve(
      desk({
        open: [
          task("TSK-00001"),
          task("TSK-00002", { url: "https://evil.example/x" }),
          task("TSK-00003", { url: "javascript:alert(1)" }),
        ],
      }),
    );
    renderWithProviders(<TranslatorHomePage />);
    await screen.findByText("TSK-00003");
    const links = screen.getAllByRole("link", { name: /افتح التاسك/ });
    expect(links.map((link) => link.getAttribute("href"))).toEqual(["/tasks/TSK-00001", "/tasks/TSK-00002", "/tasks/TSK-00003"]);
    expect(screen.getAllByRole("link", { name: /اطلب وقت أطول/ })).toHaveLength(3);
    for (const link of screen.getAllByRole("link")) {
      expect(link.getAttribute("href")).not.toMatch(/evil|javascript/);
    }
  });

  it("falls back to a plain badge for a tone or priority it does not know", async () => {
    serve(
      desk({
        open: [
          task("TSK-00001", {
            status: { value: "x", tone: "bad tone\" onclick=\"x", ar: "حالة", en: "State" },
            priority: { value: "p\" onclick=\"x", ar: "أولوية", en: "Priority" },
          }),
        ],
      }),
    );
    const { container } = renderWithProviders(<TranslatorHomePage />);
    await screen.findByText("TSK-00001");
    expect(container.querySelector(".badge--new")).not.toBeNull();
    expect(container.querySelector('[class*="onclick"]')).toBeNull();
    expect(container.querySelector('[class*="prio-"]')).toBeNull();
  });

  it("says so when there is nothing on the desk, and when there are no penalties or closed tasks", async () => {
    serve(desk({ open: [], done: [], rating_events: [] }));
    renderWithProviders(<TranslatorHomePage />);
    expect(await screen.findByText("مفيش شغل عليك دلوقتي.")).toBeInTheDocument();
    expect(screen.getByText("تقييمك كامل ومفيش خصومات.")).toBeInTheDocument();
    expect(screen.getByText("لسه مفيش.")).toBeInTheDocument();
  });

  it("lists the recently closed tasks with their status", async () => {
    serve(desk());
    renderWithProviders(<TranslatorHomePage />);
    const link = await screen.findByRole("link", { name: "TSK-00009" });
    expect(link).toHaveAttribute("href", "/tasks/TSK-00009");
    expect(screen.getByText("تم التسليم")).toBeInTheDocument();
  });

  it("shows a loading state, then an error that can be read by a screen reader", async () => {
    serve(jsonResponse({ ok: false, error: "server" }, 500));
    renderWithProviders(<TranslatorHomePage />);
    expect(screen.getByText("بيحمّل...")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("حصلت مشكلة في التحميل.");
  });

  it("asks who the person is and then the translator's endpoint, and nothing that names a client", async () => {
    const mocked = serve(desk());
    renderWithProviders(<TranslatorHomePage />);
    await screen.findByText("TSK-00001");
    expect(mocked.calls.map((c) => c.url).sort()).toEqual(["/api/v1/me/", "/api/v1/translator/home/"]);
  });

  it("is for translators and the admin only: anybody else is sent to the home page without asking the server", async () => {
    for (const role of ["operation", "team_lead", "hr", "reviewer", "accounting", "sales"] as const) {
      const mocked = serve(desk(), {}, role);
      const view = renderWithProviders(
        <Routes>
          <Route index element={<div>the home page</div>} />
          <Route path="translator" element={<TranslatorHomePage />} />
        </Routes>,
        { route: "/translator" },
      );
      expect(await screen.findByText("the home page"), role).toBeInTheDocument();
      // Every refusal is written to the audit log: a page that asked would write a row each time.
      expect(mocked.calls.filter((c) => c.url.startsWith("/api/v1/translator/")), role).toEqual([]);
      view.unmount();
    }
  });

  it("opens for the admin too", async () => {
    serve(desk(), {}, "admin");
    renderWithProviders(<TranslatorHomePage />);
    expect(await screen.findByText("TSK-00001")).toBeInTheDocument();
  });

  it("asks nothing until it knows who the person is", async () => {
    const mocked = serve(desk(), { "/api/v1/me/": () => new Promise<Response>(() => undefined) });
    renderWithProviders(<TranslatorHomePage />);
    await waitFor(() => expect(mocked.calls.some((c) => c.url === "/api/v1/me/")).toBe(true));
    expect(mocked.calls.some((c) => c.url.startsWith("/api/v1/translator/"))).toBe(false);
  });

  it("draws an unknown deadline state as no state, never as a class of the server's choosing", async () => {
    serve(desk({ open: [task("TSK-00001", { due_state: 'late" onclick="x' as DeskTask["due_state"] })] }));
    const { container } = renderWithProviders(<TranslatorHomePage />);
    await screen.findByText("TSK-00001");
    expect(container.querySelector(".deadline--none")).not.toBeNull();
    expect(container.querySelector('[class*="onclick"]')).toBeNull();
  });
});
