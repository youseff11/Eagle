import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { KpiCounts, KpiResponse, KpiRow } from "../api/b2b";
import type { Role } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { SalesPerformancePage } from "./SalesPerformancePage";

afterEach(() => vi.unstubAllGlobals());

function counts(over: Partial<KpiCounts> = {}): KpiCounts {
  return {
    new_leads: 4,
    contacted: 3,
    whatsapp: 5,
    failed: 2,
    failed_reasons: [
      { key: "marketing_limit", ar: "حد ميتا للتسويق", en: "Meta's marketing limit", count: 1 },
      { key: "not_on_whatsapp", ar: "مالوش واتساب", en: "No WhatsApp", count: 1 },
    ],
    emails: 2,
    calls: 1,
    replies: 1,
    visits: 1,
    won: 1,
    lost: 1,
    follow_ups_on_time: 2,
    follow_ups_late: 1,
    follow_ups_missed: 0,
    overdue_now: 0,
    holding: 9,
    untouched: 6,
    quotations: 3,
    quotes_accepted: 1,
    revenue: { EUR: "100.00", USD: "1250.50" },
    conversion_rate: 50,
    follow_up_rate: 67,
    ...over,
  };
}

const row = (id: number, name: string, over: Partial<KpiCounts> = {}): KpiRow => ({ person: { id, name, active: true }, ...counts(over) });

function answer(over: Partial<KpiResponse> = {}): KpiResponse {
  return { ok: true, from: "2026-10-01", to: "2026-10-10", team: false, rows: [row(7, "Seller")], total: counts(), ...over };
}

function serve(who: Role, kpis: (url: URL) => Response) {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role: who, is_admin: who === "admin" })),
    "/api/v1/b2b/kpis/": (url) => kpis(url),
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function open(route = "/sales-performance") {
  return renderWithProviders(
    <Routes>
      <Route path="/sales-performance" element={<SalesPerformancePage />} />
      <Route path="/" element={<div>home page</div>} />
    </Routes>,
    { route },
  );
}

describe("SalesPerformancePage", () => {
  it("shows a Sales person their own numbers", async () => {
    serve("sales", () => jsonResponse(answer()));
    const { container } = open();
    await screen.findByText("Seller");
    expect(screen.getByText("أرقامك انت في الفترة اللي تختارها.")).toBeInTheDocument();
    expect(container.querySelector('[data-kpi="new_leads"] .kpi__value')).toHaveTextContent("4");
    expect(container.querySelector('[data-kpi="conversion_rate"] .kpi__value')).toHaveTextContent("50%");
    expect(container.querySelector('[data-person="7"]')).toHaveTextContent("Seller");
    expect(container.querySelector('[data-person="total"]')).toBeNull();
  });

  it("shows the revenue one currency at a time, never added together", async () => {
    serve("sales", () => jsonResponse(answer()));
    const { container } = open();
    await screen.findByText("Seller");
    const revenue = container.querySelector('[data-kpi="revenue"] .kpi__value') as HTMLElement;
    expect(revenue).toHaveTextContent("100.00 EUR");
    expect(revenue).toHaveTextContent("1,250.50 USD");
    expect(container.querySelector('[data-kpi="quotations"] .kpi__value')).toHaveTextContent("3");
  });

  it("shows the WhatsApp messages that failed, next to the ones that went", async () => {
    serve("sales", () => jsonResponse(answer()));
    const { container } = open();
    await screen.findByText("Seller");
    const headers = Array.from(container.querySelectorAll("thead th")).map((th) => th.textContent);
    const at = headers.indexOf("رسايل فشلت");
    expect(at).toBe(headers.indexOf("وصلهم واتساب") + 1);
    expect(container.querySelectorAll('[data-person="7"] td')[at]).toHaveTextContent("2");
  });

  it("lists why the messages failed, for a Sales person alone", async () => {
    serve("sales", () => jsonResponse(answer()));
    const { container } = open();
    expect(await screen.findByText("ليه الرسايل فشلت")).toBeInTheDocument();
    const card = container.querySelector("#failed-reasons") as HTMLElement;
    expect(Array.from(card.querySelectorAll("thead th")).map((th) => th.textContent)).toEqual(["السبب", "العدد"]);
    expect(card.querySelector('[data-reason="marketing_limit"]')).toHaveTextContent("حد ميتا للتسويق1");
  });

  it("lists each reason per Sales person and for the team", async () => {
    const theirs = counts({ failed: 3, failed_reasons: [{ key: "not_on_whatsapp", ar: "مالوش واتساب", en: "No WhatsApp", count: 3 }] });
    const total = counts({
      failed: 5,
      failed_reasons: [
        { key: "not_on_whatsapp", ar: "مالوش واتساب", en: "No WhatsApp", count: 4 },
        { key: "other:(#131000) Something went wrong", ar: "(#131000) Something went wrong", en: "(#131000) Something went wrong", count: 1 },
      ],
    });
    const mine = counts({
      failed: 2,
      failed_reasons: [
        { key: "not_on_whatsapp", ar: "مالوش واتساب", en: "No WhatsApp", count: 1 },
        { key: "other:(#131000) Something went wrong", ar: "(#131000) Something went wrong", en: "(#131000) Something went wrong", count: 1 },
      ],
    });
    serve("sales", () => jsonResponse(answer({ team: true, rows: [{ person: { id: 7, name: "Seller", active: true }, ...mine }, { person: { id: 8, name: "Other", active: true }, ...theirs }], total })));
    const { container } = open();
    await screen.findByText("ليه الرسايل فشلت");
    const card = container.querySelector("#failed-reasons") as HTMLElement;
    expect(Array.from(card.querySelectorAll("thead th")).map((th) => th.textContent)).toEqual(["السبب", "Seller", "Other", "الفريق كله"]);
    const cells = (key: string) => Array.from(card.querySelectorAll(`[data-reason="${key}"] td`)).map((td) => td.textContent);
    expect(cells("not_on_whatsapp")).toEqual(["مالوش واتساب", "1", "3", "4"]);
    // A reason Sales has none of reads 0, and one the server does not know keeps Meta's words.
    expect(cells("other:(#131000) Something went wrong")).toEqual(["(#131000) Something went wrong", "1", "0", "1"]);
  });

  it("shows no reasons card when nothing failed", async () => {
    serve("sales", () => jsonResponse(answer({ rows: [row(7, "Seller", { failed: 0, failed_reasons: [] })], total: counts({ failed: 0, failed_reasons: [] }) })));
    open();
    await screen.findByText("Seller");
    expect(screen.queryByText("ليه الرسايل فشلت")).toBeNull();
  });

  it("writes «مش متقاس» for a rate with nothing to measure, never 0%", async () => {
    serve("sales", () => jsonResponse(answer({ rows: [row(7, "Seller", { conversion_rate: null, won: 0, lost: 0 })], total: counts({ conversion_rate: null }) })));
    const { container } = open();
    await screen.findByText("Seller");
    expect(container.querySelector('[data-kpi="conversion_rate"]')).toHaveTextContent("مش متقاس");
    expect(container.querySelector('[data-kpi="conversion_rate"]')).not.toHaveTextContent("0%");
  });

  it("shows the manager every Sales person and the team's total", async () => {
    serve("sales", () => jsonResponse(answer({ team: true, rows: [row(7, "Seller"), row(8, "Other", { won: 0 })], total: counts({ won: 1 }) })));
    const { container } = open();
    expect(await screen.findByText("كل Sales")).toBeInTheDocument();
    expect(container.querySelector('[data-person="8"]')).toHaveTextContent("Other");
    expect(container.querySelector('[data-person="total"]')).toHaveTextContent("الفريق كله");
  });

  it("asks for the period chosen, and keeps it in the address", async () => {
    const user = userEvent.setup();
    const mocked = serve("sales", (url) => jsonResponse(answer({ from: url.searchParams.get("from") ?? "2026-10-01", to: url.searchParams.get("to") ?? "2026-10-10" })));
    open();
    await user.click(await screen.findByRole("button", { name: "الشهر اللي فات" }));
    await waitFor(() => expect(mocked.calls.some((call) => /\/api\/v1\/b2b\/kpis\/\?from=\d{4}-\d{2}-01&to=\d{4}-\d{2}-\d{2}$/.test(call.url))).toBe(true));
  });

  it("reads a period from the address", async () => {
    const mocked = serve("sales", () => jsonResponse(answer({ from: "2026-09-01", to: "2026-09-30" })));
    open("/sales-performance?from=2026-09-01&to=2026-09-30");
    await screen.findByText("Seller");
    expect(mocked.calls.some((call) => call.url === "/api/v1/b2b/kpis/?from=2026-09-01&to=2026-09-30")).toBe(true);
    expect(screen.getByLabelText("من")).toHaveValue("2026-09-01");
  });

  it("says so when the period is refused", async () => {
    serve("sales", () => jsonResponse({ ok: false, error: "bad_period" }, 400));
    open("/sales-performance?from=2026-10-09&to=2026-10-01");
    expect(await screen.findByRole("alert")).toHaveTextContent("الفترة دي مش مظبوطة");
  });

  it("sends anybody else home without asking", async () => {
    const mocked = serve("operation", () => jsonResponse(answer()));
    open();
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(mocked.calls.some((call) => call.url.startsWith("/api/v1/b2b/"))).toBe(false);
  });
});
