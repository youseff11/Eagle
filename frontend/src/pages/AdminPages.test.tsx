import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AdminOverview, Role } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { AdminOverviewPage } from "./AdminOverviewPage";

afterEach(() => vi.unstubAllGlobals());

const stamp = (text: string) => ({ ar: `${text} PM`, en: `${text} PM` });
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

function serve(who: Role, body: () => AdminOverview | Response) {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role: who, is_admin: who === "admin" })),
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
    expect(within(letter).getByText("10-02 4:10 PM")).toBeInTheDocument();
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
    expect(within(late).getByText("10-01 2:00 PM")).toHaveClass("badge--dead");
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
