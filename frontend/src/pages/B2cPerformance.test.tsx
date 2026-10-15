import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { BoardCounts, BoardResponse, BoardRow } from "../api/b2c";
import { ToastProvider } from "../components/Toasts";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { B2cPerformancePage } from "./B2cPerformancePage";

/** The B2C numbers page (15/10/2026): what the server answers is drawn with what each rate is made of, the filters and
 * the period are the address, and the export asks for the same thing. */

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

const none = { value: null, part: 0, whole: 0 };

function counts(over: Partial<BoardCounts> = {}): BoardCounts {
  return {
    new_leads: 3, contacted: 2, calls: 1, messages: 4, planned: 0, submitted: 3, verified: 2, rejected: 1, pending: 0, due: 10,
    qualified: 2, qualified_from_visits: 1, quotations: 1, quotes_waiting: 1, won: 1, lost: 1, follow_ups_on_time: 1,
    follow_ups_late: 0, follow_ups_missed: 1, overdue_now: 1, untouched: 1, holding: 5, open_value: "1500.00", quote_values: {},
    visit_achievement: { value: 20, part: 2, whole: 10 }, verification_rate: { value: 67, part: 2, whole: 3 },
    lead_conversion: { value: 50, part: 1, whole: 2 }, quotation_conversion: { value: 50, part: 1, whole: 2 },
    win_rate: { value: 50, part: 1, whole: 2 }, follow_up_compliance: none, ...over,
  };
}

function row(over: Partial<BoardRow> = {}): BoardRow {
  return { ...counts(), person: { id: 7, name: "Walker", active: true, track: "b2c_field" }, field: true, ...over };
}

function answer(over: Partial<BoardResponse> = {}): BoardResponse {
  return {
    ok: true, from: "2026-10-01", to: "2026-10-15", team: true,
    filters: { people: [{ id: 7, name: "Walker" }], sources: ["Facebook", "Referral"], governorates: ["Cairo"] },
    rows: [row()],
    total: { ...counts(), quote_average: { EGP: "100.00" } },
    stages: [{ value: "new", count: 2 }, { value: "negotiation", count: 1 }],
    sources: [{ value: "Facebook", count: 2, won: 1 }],
    governorates: [{ value: "Cairo", count: 3, verified: 2 }],
    matrix: [{ person: row().person, stages: { new: 2, negotiation: 1 } }],
    untouched: [{ id: 9, company_name: "Delta Co", sheet: 3, person: "Walker", governorate: "Giza", next_follow_up: "" }],
    overdue: [],
    rejected: [{ code: "VIS-0003", company_name: "Nile Trading", sheet: 3, person: "Walker", note: "Not the company", flags: [] }],
    ...over,
  };
}

function serve(body: BoardResponse, who: Record<string, unknown> = { sales_track: "b2c_online", sales_manager: true }) {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role: "sales", ...who })),
    "/api/v1/b2b/targets/": () => jsonResponse({ ok: true, month: "2026-10", can_edit: false, metrics: [], currencies: [], rows: [] }),
    "/api/v1/b2c/board/": () => jsonResponse(body),
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function open(route = "/b2c/performance") {
  return renderWithProviders(
    <ToastProvider>
      <Routes>
        <Route path="/b2c/performance" element={<B2cPerformancePage />} />
        <Route path="/" element={<div>home page</div>} />
      </Routes>
    </ToastProvider>,
    { route },
  );
}

describe("B2cPerformancePage", () => {
  it("draws each rate with what it is made of, and «not measured» when there is nothing to divide", async () => {
    serve(answer());
    open();
    const achievement = await screen.findByText("تحقيق تارجت الزيارات", { selector: ".kpi__label" });
    expect(within(achievement.parentElement as HTMLElement).getByText("(2/10)")).toBeInTheDocument();
    const compliance = screen.getByText("الالتزام بالمتابعات", { selector: ".kpi__label" });
    expect(within(compliance.parentElement as HTMLElement).getByText("مش متقاس")).toBeInTheDocument();
    expect(screen.getByText("100.00 EGP")).toBeInTheDocument();
    expect(screen.getByText("Not the company")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "افتح الشيت" })).toHaveAttribute("href", "/leads/3");
  });

  it("leaves the visit figures out for a team with no field person", async () => {
    serve(answer({ rows: [row({ field: false, person: { id: 8, name: "Caller", active: true, track: "b2c_online" } })] }));
    open();
    await screen.findByText("نسبة الكسب", { selector: ".kpi__label" });
    expect(screen.queryByText("تحقيق تارجت الزيارات", { selector: ".kpi__label" })).toBeNull();
  });

  it("asks again with a filter, and the export asks for the same", async () => {
    const user = userEvent.setup();
    const mocked = serve(answer());
    open("/b2c/performance?from=2026-10-01&to=2026-10-15");
    await user.selectOptions(await screen.findByLabelText("المصدر"), "Facebook");
    await waitFor(() =>
      expect(mocked.calls.map((call) => call.url)).toContain("/api/v1/b2c/board/?from=2026-10-01&to=2026-10-15&source=Facebook"),
    );
    expect(screen.getByRole("link", { name: "نزّل CSV" })).toHaveAttribute(
      "href",
      "/api/v1/b2c/board/export/?from=2026-10-01&to=2026-10-15&source=Facebook",
    );
  });

  it("offers no person filter to a Sales person reading their own numbers", async () => {
    serve(answer({ team: false, filters: { people: [], sources: [], governorates: [] } }), { sales_track: "b2c_field" });
    open();
    await screen.findByText("أرقامك انت في الفترة اللي تختارها.");
    expect(screen.queryByLabelText("الـSales")).toBeNull();
  });

  it("sends a B2B Sales person home", async () => {
    serve(answer(), { sales_track: "b2b" });
    open();
    expect(await screen.findByText("home page")).toBeInTheDocument();
  });
});
