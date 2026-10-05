import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DayStatusJson, HrHistoryRow, HrPerformance, HrPerformanceBoard, HrRankRow, Role } from "../api/types";
import { jsonResponse, renderWithProviders } from "../test/helpers";
import { openHr as open, reads, serveHr, type Handler } from "../test/hr";
import { HrPerformancePage } from "./HrPerformancePage";

afterEach(() => vi.unstubAllGlobals());

const serve = (who: Role, routes: Record<string, Handler>) => serveHr(who, routes);

const good: DayStatusJson = { value: "good", tone: "ok", ar: "كويس", en: "Good" };
const fair: DayStatusJson = { value: "fair", tone: "wait", ar: "مقبول", en: "Fair" };
const poor: DayStatusJson = { value: "poor", tone: "dead", ar: "ضعيف", en: "Poor" };
const unknown: DayStatusJson = { value: "unknown", tone: "", ar: "مابتتقاسش", en: "Not measured" };

const FACE = "/files/avatars/2026/10/dddddddddddddddd.jpg";

function row(id: number, name: string, over: Partial<HrRankRow> = {}): HrRankRow {
  return {
    rank: null,
    id,
    name,
    initials: name.slice(0, 2).toUpperCase(),
    avatar: null,
    words: 0,
    target: 1000,
    score: 0,
    band: poor,
    projects: 0,
    ...over,
  };
}

function board(over: Partial<HrPerformanceBoard> = {}): HrPerformanceBoard {
  return {
    ok: true,
    year: 2026,
    month: 10,
    periods: [{ year: 2026, month: 10 }, { year: 2026, month: 9 }],
    podium: [
      row(7, "Dan", { rank: 1, words: 1200, score: 120, band: good, projects: 9, avatar: FACE }),
      row(8, "Adam", { rank: 2, words: 900, score: 90, band: good, projects: 7 }),
      row(9, "Bob", { rank: 3, words: 750, score: 75, band: fair, projects: 5 }),
    ],
    rest: [
      row(10, "Cara", { rank: 4, words: 600, score: 60, band: fair, projects: 6 }),
      row(11, "Eve", { rank: 5, words: 300, score: 30, band: poor, projects: 2 }),
      row(12, "Zed", { rank: null, words: 0, score: 0, band: poor }),
      row(13, "Noor", { rank: null, words: 5000, target: 0, score: null, band: unknown, projects: 3 }),
    ],
    ...over,
  };
}

const page = (data: HrPerformanceBoard = board()) => ({ "/api/v1/hr/performance/board/": () => jsonResponse(data) });

describe("the performance board", () => {
  it("puts the best three on a podium: the ordinals, the names, the score and the words", async () => {
    serve("hr", page());
    const { container } = open("/hr/performance");
    await screen.findByText("Dan");
    const podium = container.querySelector('[data-board="podium"]') as HTMLElement;
    const spots = [...podium.querySelectorAll("[data-rank]")] as HTMLElement[];
    expect(spots.map((spot) => spot.getAttribute("data-rank"))).toEqual(["1", "2", "3"]);
    expect(spots.map((spot) => within(spot).getByText(/^(1st|2nd|3rd)$/).textContent)).toEqual(["1st", "2nd", "3rd"]);
    // The step each stands on (its height and its place on the podium) follows its rank.
    spots.forEach((spot, index) => expect(spot).toHaveClass(`podium__spot--${index + 1}`));
    expect(spots[0]).toHaveTextContent("Dan");
    expect(spots[0]).toHaveTextContent("120%");
    expect(spots[0]).toHaveTextContent("1,200 كلمة");
    expect(spots[0]).toHaveTextContent("9 مشروع");
    expect(spots[2]).toHaveTextContent("75%");
  });

  it("draws a translator's picture on the podium and the initials for one who has none", async () => {
    serve("hr", page());
    const { container } = open("/hr/performance");
    await screen.findByText("Dan");
    const spots = [...container.querySelectorAll("[data-rank]")] as HTMLElement[];
    expect(spots[0]!.querySelector("img")).toHaveAttribute("src", FACE);
    expect(spots[1]!.querySelector("img")).toBeNull();
    expect(within(spots[1]!).getByText("AD")).toBeInTheDocument();
  });

  it("lists everybody else with their rank, a bar, the words against the target and the projects", async () => {
    serve("hr", page());
    const { container } = open("/hr/performance");
    await screen.findByText("Cara");
    const rest = container.querySelector('[data-board="rest"]') as HTMLElement;
    const cara = rest.querySelector('[data-user="10"]') as HTMLElement;
    expect(within(cara).getByText("4")).toBeInTheDocument();
    expect(cara.querySelector(".meter--fair i")).toHaveStyle({ width: "60%" });
    expect(cara).toHaveTextContent("60%");
    expect(cara).toHaveTextContent("600");
    expect(cara).toHaveTextContent("/ 1,000");
    expect(within(cara).getByText("6", { selector: "td.mono:last-child" })).toBeInTheDocument();
    expect((rest.querySelector('[data-user="11"]') as HTMLElement).querySelector(".meter--poor i")).toHaveStyle({ width: "30%" });
  });

  it("gives no rank to somebody who delivered nothing, and says 'not measured' where there is no target - never a zero", async () => {
    serve("hr", page());
    const { container } = open("/hr/performance");
    await screen.findByText("Zed");
    const zed = container.querySelector('[data-user="12"]') as HTMLElement;
    expect(within(zed).getByText("—")).toBeInTheDocument();
    expect(zed).toHaveTextContent("0%");
    const noor = container.querySelector('[data-user="13"]') as HTMLElement;
    expect(within(noor).getByText("مابتتقاسش")).toHaveClass("chip");
    expect(noor.querySelector(".meter--empty")).not.toBeNull();
    expect(noor).not.toHaveTextContent("0%");
    expect(noor).toHaveTextContent("5,000");
  });

  it("opens a translator's own page, in the same month, from the podium and from the list", async () => {
    serve("hr", page());
    const { container } = open("/hr/performance?period=2026-9");
    await screen.findByText("Dan");
    const spot = container.querySelector('[data-rank="2"]') as HTMLElement;
    expect(spot).toHaveAttribute("href", "/hr/performance?user=8&period=2026-9");
    const name = within(container.querySelector('[data-user="10"]') as HTMLElement).getByRole("link");
    expect(name).toHaveAttribute("href", "/hr/performance?user=10&period=2026-9");
  });

  it("links without a month when none was asked for", async () => {
    serve("hr", page());
    const { container } = open("/hr/performance");
    await screen.findByText("Dan");
    expect(container.querySelector('[data-rank="1"]')).toHaveAttribute("href", "/hr/performance?user=7");
  });

  it("goes to a person's page when their name is pressed", async () => {
    const person: HrPerformance = {
      ok: true, year: 2026, month: 10, periods: [{ year: 2026, month: 10 }], people: [{ id: 10, name: "Cara" }], person: { id: 10, name: "Cara" },
      report: null, history: [],
    };
    const served = serve("hr", { ...page(), "/api/v1/hr/performance/": () => jsonResponse(person) });
    open("/hr/performance");
    await screen.findByText("Cara");
    await userEvent.click(screen.getByRole("link", { name: /Cara/ }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/hr/performance?user=10"));
    await waitFor(() => expect(reads(served, "/api/v1/hr/performance/?")).toContain("/api/v1/hr/performance/?user=10"));
  });

  it("moves to another month through the address", async () => {
    const served = serve("hr", page());
    open("/hr/performance");
    await screen.findByText("Dan");
    await userEvent.selectOptions(screen.getByLabelText("الشهر"), "2026-9");
    await waitFor(() => expect(reads(served, "/api/v1/hr/performance/board/")).toContain("/api/v1/hr/performance/board/?period=2026-9"));
    expect(screen.getByTestId("where")).toHaveTextContent("/hr/performance?period=2026-9");
  });

  it("says there is no ranking yet when nothing was delivered, and still lists everybody", async () => {
    serve("hr", page(board({ podium: [], rest: [row(10, "Cara"), row(11, "Eve")] })));
    const { container } = open("/hr/performance");
    expect(await screen.findByText(/مفيش ترتيب/)).toBeInTheDocument();
    expect(container.querySelector('[data-board="podium"]')).toBeNull();
    expect(container.querySelector('[data-board="rest"]')).toHaveTextContent("Cara");
  });

  it("shows a shorter podium when only two have delivered, in their own places", async () => {
    serve("hr", page(board({ podium: board().podium.slice(0, 2), rest: [] })));
    const { container } = open("/hr/performance");
    await screen.findByText("Dan");
    expect([...container.querySelectorAll("[data-rank]")].map((spot) => spot.getAttribute("data-rank"))).toEqual(["1", "2"]);
    expect(container.querySelector('[data-board="rest"]')).toBeNull();
  });

  it("says there are no translators when there are none", async () => {
    serve("hr", page(board({ podium: [], rest: [] })));
    open("/hr/performance");
    expect(await screen.findByText("مفيش مترجمين.")).toBeInTheDocument();
  });

  it("speaks English with the same ordinals", async () => {
    serve("hr", page());
    const { container } = renderWithProviders(<HrPerformancePage />, { route: "/hr/performance", lang: "en" });
    await screen.findByText("Dan");
    expect(screen.getByRole("heading", { name: "Performance" })).toBeInTheDocument();
    expect(container.querySelector('[data-rank="1"]')).toHaveTextContent("1,200 words");
    expect(within(container.querySelector('[data-user="13"]') as HTMLElement).getByText("Not measured")).toBeInTheDocument();
    expect(screen.getByText("The rest")).toBeInTheDocument();
  });

  it("is HR's and the admin's: anybody else goes home and nothing is asked of the server", async () => {
    for (const who of ["accounting", "operation", "translator", "team_lead"] as const) {
      const served = serve(who, page());
      const view = open("/hr/performance");
      expect(await screen.findByText("home page")).toBeInTheDocument();
      expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/performance"))).toBe(false);
      view.unmount();
    }
  });
});

describe("a translator's record", () => {
  const month = (over: Partial<HrHistoryRow> = {}): HrHistoryRow => ({ year: 2026, month: 10, words: 0, target: 1000, score: 0, band: poor, projects: 0, ...over });
  const person = (history: HrHistoryRow[]): HrPerformance => ({
    ok: true,
    year: 2026,
    month: 10,
    periods: [{ year: 2026, month: 10 }, { year: 2026, month: 9 }],
    people: [{ id: 7, name: "Dan" }],
    person: { id: 7, name: "Dan" },
    report: {
      weights: { productivity: 40, quality: 30, deadline: 20, attendance: 10 },
      parts: {
        productivity: { score: 90, band: good, words: 900, target: 1000 },
        quality: { score: null, band: unknown, reviewer_avg: null, reviewed: 0, complaints: 0, violations: 0 },
        deadline: { score: null, band: unknown, late: 0, total: 0 },
        attendance: { score: null, band: unknown, present: 0, scheduled: 0, late_days: 0 },
      },
      overall: 90,
      band: good,
      projects: 7,
      returned_projects: 0,
      revision_rate: 0,
    },
    history,
  });
  const six = [
    month({ words: 900, score: 90, band: good, projects: 7 }),
    month({ month: 9, words: 500, score: 50, band: poor, projects: 3 }),
    month({ month: 8, words: 0, score: 0 }),
    month({ month: 7, words: 1100, score: 110, band: good, projects: 8 }),
    month({ month: 6, words: 700, score: 70, band: fair, projects: 5 }),
    month({ month: 5, words: 0, score: null, band: unknown }),
  ];
  const detail = (data: HrPerformance) => ({ "/api/v1/hr/performance/": () => jsonResponse(data) });

  it("lists the last six months with their words, score and projects, the month being looked at marked", async () => {
    serve("hr", detail(person(six)));
    const { container } = open("/hr/performance?user=7");
    await screen.findByText("سجل الإنتاجية");
    const card = container.querySelector('[data-card="history"]') as HTMLElement;
    expect([...card.querySelectorAll("tbody tr")].map((tr) => tr.getAttribute("data-month"))).toEqual(["2026-10", "2026-9", "2026-8", "2026-7", "2026-6", "2026-5"]);
    const now = card.querySelector('[data-month="2026-10"]') as HTMLElement;
    expect(now).toHaveClass("is-current");
    expect(now).toHaveTextContent("900");
    expect(now).toHaveTextContent("90%");
    expect(now.querySelector("a")).toBeNull();
    const july = card.querySelector('[data-month="2026-7"]') as HTMLElement;
    expect(july).toHaveTextContent("1,100");
    expect(july).toHaveTextContent("110%");
    expect(july).toHaveTextContent("8");
  });

  it("opens an earlier month of the same person from its row, and draws a month with no target as not measured", async () => {
    serve("hr", detail(person(six)));
    const { container } = open("/hr/performance?user=7");
    await screen.findByText("سجل الإنتاجية");
    const card = container.querySelector('[data-card="history"]') as HTMLElement;
    expect(within(card.querySelector('[data-month="2026-9"]') as HTMLElement).getByRole("link")).toHaveAttribute("href", "/hr/performance?user=7&period=2026-9");
    const empty = card.querySelector('[data-month="2026-5"]') as HTMLElement;
    expect(empty.querySelector(".meter--empty")).not.toBeNull();
    expect(empty).toHaveTextContent("—");
  });

  it("has a way back to the ranking in the same month", async () => {
    serve("hr", detail(person(six)));
    open("/hr/performance?user=7&period=2026-9");
    const back = await screen.findByRole("link", { name: /الترتيب/ });
    expect(back).toHaveAttribute("href", "/hr/performance?period=2026-9");
  });

  it("has no record card when there is no history to show", async () => {
    serve("hr", detail(person([])));
    const { container } = open("/hr/performance?user=7");
    await screen.findByText("المؤشرات");
    expect(container.querySelector('[data-card="history"]')).toBeNull();
  });
});
