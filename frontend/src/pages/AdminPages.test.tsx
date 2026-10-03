import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AdminAudit, AdminOverview, Role } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { AdminAuditPage } from "./AdminAuditPage";
import { AdminOverviewPage } from "./AdminOverviewPage";

afterEach(() => vi.unstubAllGlobals());

const stamp = (text: string) => ({ ar: `${text} م`, en: `${text} PM` });
const STATUS = (value: string, ar: string, en: string, tone = "work") => ({ value, tone, ar, en });

function overview(over: Partial<AdminOverview> = {}): AdminOverview {
  return {
    ok: true,
    counters: { new: 4, open: 7, delivered: 21, clients: 9 },
    blocked: [
      {
        id: 31,
        code: "CL-0003",
        channel: "email",
        at: stamp("10-02 4:10"),
        body: "What is your price per page",
        sender: "buyer@example.com",
        keyword: "price",
        files: [{ id: 5, url: "/files/rates.pdf", name: "rates.pdf", size: "12 KB", image: false, audio: false, length: "" }],
      },
    ],
    pending: [{ id: 2, task: "TSK-00007", assignee: "Sam", seconds_left: 42 }],
    late: [{ code: "TSK-00004", translator: "Nada", deadline: stamp("10-01 2:00") }, { code: "TSK-00005", translator: null, deadline: stamp("10-01 3:00") }],
    recent: [
      {
        code: "TSK-00009",
        title: "Contract",
        origin: { value: "email", icon: "mail", ar: "إيميل", en: "E-mail" },
        status: STATUS("new", "جديد", "New", "new"),
      },
    ],
    ...over,
  };
}

function audit(over: Partial<AdminAudit> = {}): AdminAudit {
  return {
    ok: true,
    only: "",
    rows: [
      { id: 12, at: stamp("2026-10-02 4:10"), actor: "Mona", action: "client.identity.view", target: "CL-0001", detail: "client_detail", ip: "203.0.113.7", path: "/clients/CL-0001/" },
      { id: 11, at: stamp("2026-10-02 4:00"), actor: null, action: "system.sweep", target: "", detail: "", ip: "", path: "" },
    ],
    ...over,
  };
}

function serve(
  who: Role,
  body: () => AdminOverview | Response,
  auditBody: (only: string) => AdminAudit | Response = (only) => audit({ only: only as AdminAudit["only"] }),
) {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role: who, is_admin: who === "admin" })),
    "/api/v1/admin/audit/": (url) => {
      const answer = auditBody(url.searchParams.get("only") ?? "");
      return answer instanceof Response ? answer : jsonResponse(answer);
    },
    "/api/v1/admin/overview/": () => {
      const answer = body();
      return answer instanceof Response ? answer : jsonResponse(answer);
    },
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function open(route: string, lang: "ar" | "en" = "ar") {
  return renderWithProviders(
    <Routes>
      <Route path="/admin" element={<AdminOverviewPage />} />
      <Route path="/admin/audit" element={<AdminAuditPage />} />
      <Route path="/tasks/:code" element={<div>one task page</div>} />
      <Route path="/" element={<div>home page</div>} />
    </Routes>,
    { route, lang },
  );
}

describe("AdminOverviewPage", () => {
  it("shows the four numbers the way the classic overview does", async () => {
    serve("admin", () => overview());
    const { container } = open("/admin");
    await screen.findByText("TSK-00009");
    expect(Array.from(container.querySelectorAll(".kpi")).map((one) => one.textContent)).toEqual([
      "4تاسكات جديدة",
      "7شغالة",
      "21اتسلمت",
      "9عملاء",
    ]);
    expect(container.querySelector(".kpi--warn")).toHaveTextContent("شغالة");
    expect(container.querySelector(".kpi--ok")).toHaveTextContent("اتسلمت");
  });

  it("lists a letter held back with its client's code, words, file, sender and the word that held it", async () => {
    serve("admin", () => overview());
    const { container } = open("/admin");
    await screen.findByText("TSK-00009");
    const letter = container.querySelector('[data-letter="31"]') as HTMLElement;
    expect(letter).toHaveClass("is-blocked");
    expect(within(letter).getByText("CL-0003")).toHaveClass("mono");
    expect(within(letter).getByText("What is your price per page")).toBeInTheDocument();
    expect(within(letter).getByText("10-02 4:10 م")).toBeInTheDocument();
    expect(within(letter).getByRole("link", { name: /rates\.pdf/ })).toHaveAttribute("href", "/files/rates.pdf");
    expect(within(letter).getByText("buyer@example.com · price")).toBeInTheDocument();
  });

  it("opens a held letter's file only from this site", async () => {
    const hostile = overview().blocked[0]!;
    serve("admin", () => overview({ blocked: [{ ...hostile, files: [{ ...hostile.files[0]!, url: "https://elsewhere.example/x.pdf" }] }] }));
    const { container } = open("/admin");
    await screen.findByText("TSK-00009");
    const letter = container.querySelector('[data-letter="31"]') as HTMLElement;
    expect(within(letter).queryByRole("link")).toBeNull();
    expect(within(letter).getByText("rates.pdf")).toBeInTheDocument();
  });

  it("says when nothing is held back, nothing waits, nothing is late and there are no tasks", async () => {
    serve("admin", () => overview({ blocked: [], pending: [], late: [], recent: [], counters: { new: 0, open: 0, delivered: 0, clients: 0 } }));
    open("/admin");
    expect(await screen.findByText("مفيش رسايل محجوبة.")).toBeInTheDocument();
    expect(screen.getByText("كله في ميعاده.")).toBeInTheDocument();
    expect(screen.getAllByText("مفيش.")).toHaveLength(2);
  });

  it("lists the hand-offs waiting, with the seconds left, and opens the task in the app", async () => {
    serve("admin", () => overview());
    const user = userEvent.setup();
    open("/admin");
    const link = await screen.findByRole("link", { name: "TSK-00007" });
    expect(link).toHaveAttribute("href", "/tasks/TSK-00007");
    expect(screen.getByText("Sam")).toBeInTheDocument();
    expect(screen.getByText("42s")).toHaveClass("badge--wait");
    await user.click(link);
    expect(await screen.findByText("one task page")).toBeInTheDocument();
  });

  it("lists the late tasks with the translator or a dash, and the date", async () => {
    serve("admin", () => overview());
    open("/admin");
    const late = (await screen.findByText("تاسكات عدّت الديدلاين")).closest(".card") as HTMLElement;
    expect(within(late).getByText("Nada")).toBeInTheDocument();
    expect(within(late).getByText("—")).toBeInTheDocument();
    expect(within(late).getByText("10-01 2:00 م")).toHaveClass("badge--dead");
  });

  it("lists the newest tasks with where each came from and where it stands", async () => {
    serve("admin", () => overview());
    open("/admin");
    const latest = (await screen.findByText("آخر التاسكات")).closest(".card") as HTMLElement;
    expect(within(latest).getByText("Contract")).toBeInTheDocument();
    expect(within(latest).getByText("إيميل")).toBeInTheDocument();
    expect(within(latest).getByText("جديد").closest(".badge")).toHaveClass("badge--new");
  });

  it("speaks English when the page is in English", async () => {
    serve("admin", () => overview());
    open("/admin", "en");
    expect(await screen.findByText("Hidden from Operation")).toBeInTheDocument();
    expect(screen.getByText("Late tasks")).toBeInTheDocument();
    expect(screen.getByText("10-02 4:10 PM")).toBeInTheDocument();
  });

  it("sends anybody who is not the admin home, and asks the server for nothing", async () => {
    const mocked = serve("operation", () => overview());
    open("/admin");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(mocked.calls.some((call) => call.url.startsWith("/api/v1/admin/"))).toBe(false);
  });

  it("says so when the board cannot be read", async () => {
    serve("admin", () => jsonResponse({ ok: false, error: "server" }, 500));
    open("/admin");
    expect(await screen.findByRole("alert")).toHaveTextContent("حصلت مشكلة في التحميل.");
  });
});

describe("AdminAuditPage", () => {
  it("lists the entries with who, what, on what, the detail and where from", async () => {
    serve("admin", () => overview());
    const { container } = open("/admin/audit");
    await screen.findByText("client.identity.view");
    const row = container.querySelector('[data-entry="12"]') as HTMLElement;
    expect(within(row).getByText("2026-10-02 4:10 م")).toBeInTheDocument();
    expect(within(row).getByText("Mona")).toBeInTheDocument();
    expect(within(row).getByText("CL-0001")).toHaveClass("mono");
    expect(within(row).getByText("client_detail")).toBeInTheDocument();
    expect(within(row).getByText("203.0.113.7")).toBeInTheDocument();
    expect(within(row).getByText("/clients/CL-0001/")).toBeInTheDocument();
  });

  it("calls an entry nobody made 'system'", async () => {
    serve("admin", () => overview());
    const { container } = open("/admin/audit");
    await screen.findByText("system.sweep");
    expect(within(container.querySelector('[data-entry="11"]') as HTMLElement).getByText("system")).toBeInTheDocument();
  });

  it("asks for the whole log first, and a filter in the address asks for that filter", async () => {
    const mocked = serve("admin", () => overview());
    open("/admin/audit?only=denied");
    await screen.findByText("client.identity.view");
    const audits = mocked.calls.filter((call) => call.url.startsWith("/api/v1/admin/audit/")).map((call) => call.url);
    expect(audits).toEqual(["/api/v1/admin/audit/?only=denied"]);
  });

  it("marks the filter that is on and moves to another one with its link", async () => {
    const mocked = serve("admin", () => overview());
    const user = userEvent.setup();
    open("/admin/audit");
    await screen.findByText("client.identity.view");
    expect(screen.getByRole("link", { name: "الكل" })).toHaveClass("btn--primary");
    await user.click(screen.getByRole("link", { name: "محاولات مرفوضة" }));
    await screen.findByText("client.identity.view");
    expect(screen.getByRole("link", { name: "محاولات مرفوضة" })).toHaveClass("btn--primary");
    expect(screen.getByRole("link", { name: "الكل" })).not.toHaveClass("btn--primary");
    expect(mocked.calls.some((call) => call.url === "/api/v1/admin/audit/?only=denied")).toBe(true);
  });

  it("treats a filter that is not one as the whole log, as the classic page does", async () => {
    const mocked = serve("admin", () => overview());
    open("/admin/audit?only=%3Cscript%3E");
    await screen.findByText("client.identity.view");
    expect(mocked.calls.filter((call) => call.url.startsWith("/api/v1/admin/audit/")).map((call) => call.url)).toEqual(["/api/v1/admin/audit/"]);
  });

  it("does not show one filter's rows under another's name while it loads", async () => {
    let release: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => (release = resolve));
    const mocked = mockFetch({
      "/api/v1/me/": () => jsonResponse(me({ role: "admin", is_admin: true })),
      "/api/v1/admin/audit/": async (url) => {
        if (url.searchParams.get("only") === "security") await gate;
        return jsonResponse(audit({ only: (url.searchParams.get("only") ?? "") as AdminAudit["only"] }));
      },
    });
    vi.stubGlobal("fetch", mocked.fn);
    const user = userEvent.setup();
    open("/admin/audit");
    await screen.findByText("client.identity.view");
    await user.click(screen.getByRole("link", { name: "هوية العملاء والصلاحيات" }));
    expect(await screen.findByText("بيحمّل...")).toBeInTheDocument();
    expect(screen.queryByText("client.identity.view")).toBeNull();
    release?.();
    expect(await screen.findByText("client.identity.view")).toBeInTheDocument();
  });

  it("asks again on the refresh button", async () => {
    const mocked = serve("admin", () => overview());
    const user = userEvent.setup();
    open("/admin/audit");
    await screen.findByText("client.identity.view");
    await user.click(screen.getByRole("button", { name: "حدّث" }));
    await vi.waitFor(() => expect(mocked.calls.filter((call) => call.url.startsWith("/api/v1/admin/audit/"))).toHaveLength(2));
  });

  it("says when the log is empty", async () => {
    serve("admin", () => overview(), () => audit({ rows: [] }));
    open("/admin/audit");
    expect(await screen.findByText("السجل فاضي.")).toBeInTheDocument();
  });

  it("sends anybody who is not the admin home, and asks the server for nothing", async () => {
    const mocked = serve("hr", () => overview());
    open("/admin/audit");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(mocked.calls.some((call) => call.url.startsWith("/api/v1/admin/"))).toBe(false);
  });

  it("says so when the log cannot be read", async () => {
    serve("admin", () => overview(), () => jsonResponse({ ok: false, error: "server" }, 500));
    open("/admin/audit");
    expect(await screen.findByRole("alert")).toHaveTextContent("حصلت مشكلة في التحميل.");
  });
});
