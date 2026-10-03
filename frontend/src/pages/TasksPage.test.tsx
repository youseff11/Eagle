import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { OpsTaskRow, Role, TasksResponse } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { TasksPage } from "./TasksPage";

afterEach(() => vi.unstubAllGlobals());

const URL = "/api/v1/tasks/";

const STATUSES = [
  { value: "new", tone: "new", ar: "جديدة", en: "New" },
  { value: "in_progress", tone: "work", ar: "شغل جاري", en: "In progress" },
  { value: "delivered", tone: "done", ar: "تم التسليم", en: "Delivered" },
];

function row(code: string, over: Partial<OpsTaskRow> = {}): OpsTaskRow {
  return {
    code,
    title: `Title of ${code}`,
    origin: { value: "whatsapp", icon: "message", ar: "واتساب", en: "WhatsApp" },
    priority: { value: "high", ar: "عالية", en: "High" },
    client: "CL-0001",
    status: STATUSES[1]!,
    team_lead: "Mona",
    translator: "Sam",
    due: { ar: "10-30 5:30 م", en: "10-30 5:30 PM" },
    due_state: "ok",
    ...over,
  };
}

function list(over: Partial<TasksResponse> = {}): TasksResponse {
  return {
    ok: true,
    status: "",
    counters: { new: 3, open: 7, review: 2, ready: 1 },
    statuses: STATUSES,
    tasks: [row("TSK-00001"), row("TSK-00002", { team_lead: null, translator: null, status: STATUSES[0]!, due: null, due_state: "none" })],
    ...over,
  };
}

function serve(body: (url: URL) => Response, role: Role = "operation") {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role, is_admin: role === "admin" })),
    [URL]: body,
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function open(route = "/tasks", lang: "ar" | "en" = "ar") {
  return renderWithProviders(
    <Routes>
      <Route path="/tasks" element={<TasksPage />} />
      <Route path="/tasks/new" element={<div>new task page</div>} />
      <Route path="/tasks/:code" element={<div>one task page</div>} />
      <Route path="/" element={<div>home page</div>} />
    </Routes>,
    { route, lang },
  );
}

describe("TasksPage", () => {
  it("shows the four numbers, and a row for every task the way the classic table does", async () => {
    serve(() => jsonResponse(list()));
    const { container } = open();
    expect(await screen.findByText("TSK-00001")).toBeInTheDocument();
    const kpis = Array.from(container.querySelectorAll(".kpi")).map((k) => k.textContent);
    expect(kpis).toEqual(["3جديدة — محتاجة توزيع", "7شغالة دلوقتي", "2تحت المراجعة", "1جاهزة للتسليم"]);
    const first = container.querySelector('[data-task="TSK-00001"]') as HTMLElement;
    expect(within(first).getByText(/Title of TSK-00001/)).toBeInTheDocument();
    expect(within(first).getByText("واتساب")).toBeInTheDocument();
    expect(within(first).getByText("عالية")).toHaveClass("badge--prio-high");
    expect(within(first).getByText("CL-0001")).toHaveClass("mono");
    expect(within(first).getByText("شغل جاري").closest(".badge")).toHaveClass("badge--work");
    expect(within(first).getByText("Mona")).toBeInTheDocument();
    expect(within(first).getByText("Sam")).toBeInTheDocument();
    expect(within(first).getByText("10-30 5:30 م")).toHaveClass("deadline--ok");
  });

  it("says nobody and nothing for what is not there yet", async () => {
    serve(() => jsonResponse(list()));
    const { container } = open();
    await screen.findByText("TSK-00002");
    const second = container.querySelector('[data-task="TSK-00002"]') as HTMLElement;
    const cells = Array.from(second.querySelectorAll("td")).map((c) => c.textContent);
    expect(cells.slice(4, 7)).toEqual(["—", "—", "—"]);
    expect(second.querySelectorAll("td")[6]).toHaveClass("deadline--none");
  });

  it("opens a task as a route of this app, made from its code", async () => {
    serve(() => jsonResponse(list({ tasks: [row("TSK-00001"), row("TSK-<img>")] })));
    open();
    await screen.findByText("TSK-00001");
    const links = screen.getAllByRole("link", { name: "افتح" });
    expect(links.map((l) => l.getAttribute("href"))).toEqual(["/tasks/TSK-00001", "/tasks/TSK-%3Cimg%3E"]);
    await userEvent.click(links[0]!);
    expect(await screen.findByText("one task page")).toBeInTheDocument();
  });

  it("has a way to a new task", async () => {
    serve(() => jsonResponse(list()));
    open();
    await userEvent.click(await screen.findByRole("link", { name: /تاسك جديدة/ }));
    expect(await screen.findByText("new task page")).toBeInTheDocument();
  });

  it("draws the words as text, never as markup", async () => {
    serve(() => jsonResponse(list({ tasks: [row("TSK-00001", { title: "<img src=x onerror=alert(1)>", client: "<b>x</b>" })] })));
    const { container } = open();
    expect(await screen.findByText(/<img src=x onerror=alert\(1\)>/)).toBeInTheDocument();
    expect(container.querySelector("tbody img, tbody b")).toBeNull();
  });

  it("has a tab for all, for open, and for every status, with this one selected", async () => {
    serve(() => jsonResponse(list()));
    open();
    await screen.findByText("TSK-00001");
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual(["الكل", "المفتوحة", "جديدة", "شغل جاري", "تم التسليم"]);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(tabs[1]).toHaveAttribute("aria-selected", "false");
  });

  it("asks for the tab that is clicked, and says which is on", async () => {
    const mocked = serve((url) => jsonResponse(list({ status: url.searchParams.get("status") ?? "", tasks: [row("TSK-00009")] })));
    open();
    await screen.findByText("TSK-00009");
    await userEvent.click(screen.getByRole("tab", { name: "المفتوحة" }));
    await waitFor(() => expect(mocked.calls.some((c) => c.url === `${URL}?status=open`)).toBe(true));
    expect(screen.getByRole("tab", { name: "المفتوحة" })).toHaveAttribute("aria-selected", "true");
    await userEvent.click(screen.getByRole("tab", { name: "تم التسليم" }));
    await waitFor(() => expect(mocked.calls.some((c) => c.url === `${URL}?status=delivered`)).toBe(true));
    await userEvent.click(screen.getByRole("tab", { name: "الكل" }));
    await waitFor(() => expect(mocked.calls.filter((c) => c.url === URL).length).toBeGreaterThan(1));
  });

  it("opens on the tab the address names", async () => {
    const mocked = serve(() => jsonResponse(list({ status: "open" })));
    open("/tasks?status=open");
    await screen.findByText("TSK-00001");
    expect(mocked.calls.some((c) => c.url === `${URL}?status=open`)).toBe(true);
    expect(screen.getByRole("tab", { name: "المفتوحة" })).toHaveAttribute("aria-selected", "true");
  });

  it("does not send what is not a status: the address is the person's to type", async () => {
    const mocked = serve(() => jsonResponse(list()));
    open("/tasks?status=%3Cscript%3E");
    await screen.findByText("TSK-00001");
    expect(mocked.calls.filter((c) => c.url.startsWith(URL)).map((c) => c.url)).toEqual([URL]);
  });

  it("says there are no tasks when there are none", async () => {
    serve(() => jsonResponse(list({ tasks: [] })));
    open();
    expect(await screen.findByText("مفيش تاسكات.")).toBeInTheDocument();
  });

  it("speaks English when asked", async () => {
    serve(() => jsonResponse(list()));
    open("/tasks", "en");
    expect(await screen.findByText("Currently open")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Open" })).toBeInTheDocument();
    expect(screen.getByText("10-30 5:30 PM")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /New task/ })).toBeInTheDocument();
  });

  it("is for the operation and the admin: anybody else is sent home without asking", async () => {
    const mocked = serve(() => jsonResponse(list()), "translator");
    open();
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(mocked.calls.some((c) => c.url.startsWith(URL))).toBe(false);
  });

  it("answers the admin", async () => {
    serve(() => jsonResponse(list()), "admin");
    open();
    expect(await screen.findByText("TSK-00001")).toBeInTheDocument();
  });

  it("says it could not load on a server failure, and not a half page", async () => {
    serve(() => jsonResponse({ ok: false, error: "server" }, 500));
    open();
    expect(await screen.findByRole("alert")).toHaveTextContent("حصلت مشكلة في التحميل.");
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("says it is loading before the answer comes", async () => {
    serve(() => new Promise<Response>(() => undefined) as unknown as Response);
    open();
    await waitFor(() => expect(screen.getByText("بيحمّل...")).toBeInTheDocument());
  });
});
