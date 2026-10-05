import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { LeadBoard, LeadHome, LeadPerson, OpsTaskRow, Role } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { LeadBoardPage } from "./LeadBoardPage";
import { LeadHomePage } from "./LeadHomePage";

afterEach(() => vi.unstubAllGlobals());

const stamp = (text: string) => ({ ar: `${text} PM`, en: `${text} PM` });
const STATUS = (value: string, ar: string, en: string, tone = "work") => ({ value, tone, ar, en });

function person(id: number, name: string, over: Partial<LeadPerson> = {}): LeadPerson {
  return { id, name, initials: name.slice(0, 2).toUpperCase(), languages: "EN→AR", rating: 4.5, state: "free", ...over };
}

function row(code: string, over: Partial<OpsTaskRow> = {}): OpsTaskRow {
  return {
    code,
    title: `Title of ${code}`,
    origin: { value: "whatsapp", icon: "message", ar: "واتساب", en: "WhatsApp" },
    priority: { value: "high", ar: "عالية", en: "High" },
    client: "CL-0001",
    status: STATUS("in_progress", "شغل جاري", "In progress"),
    team_lead: "Mona",
    translator: "Sam",
    due: stamp("10-30 5:30"),
    due_state: "ok",
    ...over,
  };
}

function home(over: Partial<LeadHome> = {}): LeadHome {
  return {
    ok: true,
    counters: { open: 3, free: 1, busy: 2, offline: 1 },
    tasks: [
      row("TSK-00001"),
      row("TSK-00002", { translator: null, status: STATUS("lead_accepted", "استلمها الليدر", "Lead accepted", "new"), due_state: "soon" }),
      row("TSK-00003", { status: STATUS("under_review", "تحت المراجعة", "Under review", "review"), due_state: "late" }),
    ],
    team: [
      { ...person(11, "Sam", { state: "busy" }), seen: stamp("5:30") },
      { ...person(12, "Nada", { state: "off", rating: 3.25 }), seen: { ar: "من ساعتين", en: "2 h ago" } },
    ],
    closed: [{ code: "TSK-00009", status: STATUS("delivered", "اتسلّمت", "Delivered", "done") }],
    ...over,
  };
}

function serveHome(body: () => LeadHome | Response, who: Role = "team_lead") {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role: who, is_admin: who === "admin" })),
    // The board's own address starts like the home's: the tests that follow the link must not be answered with the home.
    "/api/v1/lead/translators/": () => jsonResponse({ ok: false, error: "not_found" }, 404),
    "/api/v1/lead/": () => {
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
      <Route path="/lead" element={<LeadHomePage />} />
      <Route path="/lead/translators" element={<LeadBoardPage />} />
      <Route path="/tasks/:code" element={<div>one task page</div>} />
      <Route path="/" element={<div>home page</div>} />
    </Routes>,
    { route, lang },
  );
}

describe("LeadHomePage", () => {
  it("shows the four numbers the way the classic board does", async () => {
    serveHome(() => home());
    const { container } = open("/lead");
    await screen.findByText("TSK-00001");
    expect(Array.from(container.querySelectorAll(".kpi")).map((one) => one.textContent)).toEqual([
      "3تاسكات مفتوحة",
      "1مترجمين فاضيين",
      "2مشغولين",
      "1أوفلاين",
    ]);
  });

  it("lists the tasks with the client as a code, who has it and the client's date", async () => {
    serveHome(() => home());
    const { container } = open("/lead");
    await screen.findByText("TSK-00001");
    const first = container.querySelector('[data-task="TSK-00001"]') as HTMLElement;
    expect(within(first).getByText("CL-0001")).toHaveClass("mono");
    expect(within(first).getByText("واتساب")).toBeInTheDocument();
    expect(within(first).getByText("شغل جاري").closest(".badge")).toHaveClass("badge--work");
    expect(within(first).getByText("Sam")).toBeInTheDocument();
    expect(within(first).getByText("10-30 5:30 PM")).toHaveClass("deadline--ok");
    const second = container.querySelector('[data-task="TSK-00002"]') as HTMLElement;
    expect(within(second).getByText("—", { selector: "td" })).toBeInTheDocument();
    expect(within(second).getByText("10-30 5:30 PM")).toHaveClass("deadline--soon");
  });

  it("says on each button what the leader does next: hand it out, review it, or open it", async () => {
    serveHome(() => home());
    const { container } = open("/lead");
    await screen.findByText("TSK-00001");
    const button = (code: string) => within(container.querySelector(`[data-task="${code}"]`) as HTMLElement).getByRole("link");
    expect(button("TSK-00001")).toHaveTextContent("افتح");
    expect(button("TSK-00001")).not.toHaveClass("btn--primary");
    expect(button("TSK-00002")).toHaveTextContent("وزّع على مترجم");
    expect(button("TSK-00002")).toHaveClass("btn--primary");
    expect(button("TSK-00003")).toHaveTextContent("راجع الترجمة");
    expect(button("TSK-00003")).toHaveClass("btn--primary");
  });

  it("opens a task on its page in the app", async () => {
    serveHome(() => home());
    const user = userEvent.setup();
    const { container } = open("/lead");
    await screen.findByText("TSK-00001");
    const link = within(container.querySelector('[data-task="TSK-00002"]') as HTMLElement).getByRole("link");
    expect(link.getAttribute("href")).toBe("/tasks/TSK-00002");
    await user.click(link);
    expect(await screen.findByText("one task page")).toBeInTheDocument();
  });

  it("says there are no open tasks", async () => {
    serveHome(() => home({ tasks: [], counters: { open: 0, free: 0, busy: 0, offline: 0 } }));
    open("/lead");
    expect(await screen.findByText("مفيش تاسكات مفتوحة.")).toBeInTheDocument();
  });

  it("shows the team with their state, how long ago they were here when they are away, and their rating", async () => {
    serveHome(() => home());
    const { container } = open("/lead");
    await screen.findByText("Sam", { selector: "div" });
    const sam = container.querySelector('[data-member="11"]') as HTMLElement;
    expect(within(sam).getByText("مشغول")).toBeInTheDocument();
    expect(within(sam).getByText("EN→AR")).toHaveClass("mono");
    expect(within(sam).getByText("4.50")).toBeInTheDocument();
    const nada = container.querySelector('[data-member="12"]') as HTMLElement;
    expect(within(nada).getByText("أوفلاين")).toBeInTheDocument();
    expect(within(nada).getByText("من ساعتين")).toBeInTheDocument();
  });

  it("points at the full board", async () => {
    serveHome(() => home());
    const user = userEvent.setup();
    open("/lead");
    const link = await screen.findByRole("link", { name: "اللوحة الكاملة" });
    expect(link.getAttribute("href")).toBe("/lead/translators");
    await user.click(link);
  });

  it("says nobody is assigned to the leader, when nobody is", async () => {
    serveHome(() => home({ team: [] }));
    open("/lead");
    expect(await screen.findByText("مفيش مترجمين تحتك.")).toBeInTheDocument();
  });

  it("lists what was closed lately, each a link to its task", async () => {
    serveHome(() => home());
    open("/lead");
    const link = await screen.findByRole("link", { name: "TSK-00009" });
    expect(link.getAttribute("href")).toBe("/tasks/TSK-00009");
    expect(screen.getByText("اتسلّمت")).toBeInTheDocument();
  });

  it("says nothing was closed yet", async () => {
    serveHome(() => home({ closed: [] }));
    open("/lead");
    expect(await screen.findByText("لسه مفيش.")).toBeInTheDocument();
  });

  it("sends everybody else home without asking", async () => {
    for (const who of ["operation", "translator", "hr", "accounting", "reviewer", "sales"] as Role[]) {
      const mocked = serveHome(() => home(), who);
      const { unmount } = open("/lead");
      expect(await screen.findByText("home page")).toBeInTheDocument();
      expect(mocked.calls.filter((call) => call.url.startsWith("/api/v1/lead/")), who).toEqual([]);
      unmount();
    }
  });

  it("says it could not load, and speaks English too", async () => {
    serveHome(() => jsonResponse({ ok: false, error: "boom" }, 500));
    const first = open("/lead");
    expect(await screen.findByText("حصلت مشكلة في التحميل.")).toBeInTheDocument();
    first.unmount();
    serveHome(() => home());
    open("/lead", "en");
    expect(await screen.findByText("Team leader board")).toBeInTheDocument();
    expect(await screen.findByText("Assign a translator")).toBeInTheDocument();
    expect(screen.getByText("My team")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------------------------------------------------
// Who is free
// ---------------------------------------------------------------------------------------------------------------------

function boardRow(id: number, name: string, over: Partial<LeadBoard["team"][number]> = {}): LeadBoard["team"][number] {
  return {
    ...person(id, name),
    awaiting_answer: false,
    load: 0,
    load_percent: 0,
    words: 0,
    tasks: [],
    next_due: null,
    next_due_state: "none",
    ...over,
  };
}

function board(over: Partial<LeadBoard> = {}): LeadBoard {
  return {
    ok: true,
    counters: { free: 1, busy: 1, shift: 1, offline: 0, open: 5 },
    waiting: [{ code: "TSK-00020", due: stamp("10-30 5:30"), due_state: "soon" }],
    team: [
      boardRow(11, "Nada"),
      boardRow(12, "Sam", { state: "busy", load: 5, load_percent: 100, words: 1200, tasks: ["TSK-00001", "TSK-00002", "TSK-00003"], next_due: stamp("10-29 1:00"), next_due_state: "late", awaiting_answer: true }),
      boardRow(13, "Ola", { state: "shift", rating: 3.2 }),
    ],
    ...over,
  };
}

function serveBoard(body: () => LeadBoard | Response, who: Role = "team_lead") {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role: who, is_admin: who === "admin" })),
    "/api/v1/lead/translators/": () => {
      const answer = body();
      return answer instanceof Response ? answer : jsonResponse(answer);
    },
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

describe("LeadBoardPage", () => {
  it("answers the one question with the four numbers, and what 'free' means", async () => {
    serveBoard(() => board());
    const { container } = open("/lead/translators");
    await screen.findByText("Nada");
    expect(Array.from(container.querySelectorAll(".kpi")).map((one) => one.textContent)).toEqual([
      "1فاضيين دلوقتي",
      "1مشغولين",
      "1في الشيفت — مش فاتح",
      "0أوفلاين",
    ]);
    expect(screen.getByText("«فاضي» يعني فاتح إيجل دلوقتي ومفيش تاسك شغّالة عنده ولا عرض مستني رده.")).toBeInTheDocument();
  });

  it("says the tasks that wait for a translator, each a link with its date", async () => {
    serveBoard(() => board());
    open("/lead/translators");
    const link = await screen.findByRole("link", { name: /TSK-00020/ });
    expect(link).toHaveClass("deadline--soon");
    expect(link).toHaveTextContent("10-30 5:30 PM");
    expect(link.getAttribute("href")).toBe("/tasks/TSK-00020");
    expect(screen.getByText("تاسكات مستنية توزيع")).toBeInTheDocument();
  });

  it("says nothing about waiting tasks when none wait", async () => {
    serveBoard(() => board({ waiting: [] }));
    open("/lead/translators");
    await screen.findByText("Nada");
    expect(screen.queryByText("تاسكات مستنية توزيع")).toBeNull();
  });

  it("holds the evidence for each person: the load, the words, what they work on, the nearest deadline", async () => {
    serveBoard(() => board());
    const { container } = open("/lead/translators");
    await screen.findByText("Sam");
    const sam = container.querySelector('[data-member="12"]') as HTMLElement;
    expect(sam).toHaveClass("tstate--busy");
    expect(within(sam).getByText("5", { selector: ".mono" })).toBeInTheDocument();
    expect((sam.querySelector(".load__fill") as HTMLElement).style.width).toBe("100%");
    expect(within(sam).getByText(/1200/)).toBeInTheDocument();
    expect(within(sam).getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual(["/tasks/TSK-00001", "/tasks/TSK-00002", "/tasks/TSK-00003"]);
    // Five tasks: three are named and the rest are counted.
    expect(within(sam).getByText("+2")).toHaveClass("chip");
    expect(within(sam).getByText("10-29 1:00 PM")).toHaveClass("deadline--late");
    expect(within(sam).getByText("مستني يرد على عرض تاسك")).toBeInTheDocument();
  });

  it("says nothing is on somebody who is free, and gives them no deadline", async () => {
    serveBoard(() => board());
    const { container } = open("/lead/translators");
    await screen.findByText("Nada");
    const nada = container.querySelector('[data-member="11"]') as HTMLElement;
    expect(nada).toHaveClass("tstate--free");
    expect(within(nada).getByText("فاضي")).toBeInTheDocument();
    expect(Array.from(nada.querySelectorAll("td")).slice(3, 5).map((cell) => cell.textContent)).toEqual(["—", "—"]);
    expect(within(nada).queryByText(/كلمة/)).toBeNull();
  });

  it("says who is on a shift without Eagle open, and does not say when they were last here (the board is not about that)", async () => {
    serveBoard(() => board());
    const { container } = open("/lead/translators");
    await screen.findByText("Ola");
    const ola = container.querySelector('[data-member="13"]') as HTMLElement;
    expect(within(ola).getByText("في الشيفت — مش فاتح", { selector: ".presence__state" })).toBeInTheDocument();
    expect(ola.querySelector(".presence__seen")).toBeNull();
  });

  it("says nobody is assigned to the leader when nobody is", async () => {
    serveBoard(() => board({ team: [], waiting: [] }));
    open("/lead/translators");
    expect(await screen.findByText("مفيش مترجمين تحتك.")).toBeInTheDocument();
  });

  it("sends everybody else home without asking", async () => {
    for (const who of ["operation", "translator", "hr", "accounting", "reviewer", "sales"] as Role[]) {
      const mocked = serveBoard(() => board(), who);
      const { unmount } = open("/lead/translators");
      expect(await screen.findByText("home page")).toBeInTheDocument();
      expect(mocked.calls.filter((call) => call.url.startsWith("/api/v1/lead/")), who).toEqual([]);
      unmount();
    }
  });

  it("says it could not load, and speaks English", async () => {
    serveBoard(() => jsonResponse({ ok: false, error: "boom" }, 500));
    const first = open("/lead/translators");
    expect(await screen.findByText("حصلت مشكلة في التحميل.")).toBeInTheDocument();
    first.unmount();
    serveBoard(() => board());
    open("/lead/translators", "en");
    expect(await screen.findByText("Who is free, who is busy")).toBeInTheDocument();
    expect(await screen.findByText("Free now")).toBeInTheDocument();
    expect(screen.getByText("Tasks waiting for a translator")).toBeInTheDocument();
  });
});
