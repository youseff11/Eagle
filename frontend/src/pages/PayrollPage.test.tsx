import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PayrollResponse, Role } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { PayrollPage } from "./PayrollPage";

afterEach(() => vi.unstubAllGlobals());

const PAYROLL = "/api/v1/translator/payroll/";

function slip(overrides: Partial<PayrollResponse> = {}): PayrollResponse {
  return {
    ok: true,
    year: 2026,
    month: 10,
    periods: [
      { year: 2026, month: 10 },
      { year: 2026, month: 9 },
      { year: 2026, month: 8 },
    ],
    daily_target_words: 3000,
    line: {
      id: 5,
      base_salary: "5000.00",
      production_bonus: "750.50",
      deductions: "120.00",
      net: "5630.50",
      pending_bonus: "0.00",
      url: "/accounts/line/5/",
    },
    days: [
      { date: "2026-10-01", status: { value: "present", tone: "ok", ar: "حاضر", en: "Present" }, words: 3100 },
      { date: "2026-10-02", status: { value: "leave", tone: "info", ar: "إجازة", en: "Leave" }, words: 0 },
      { date: "2026-10-03", status: { value: "weekly_off", tone: "", ar: "راحة أسبوعية", en: "Weekly off" }, words: 0 },
    ],
    violations: [
      { date: "2026-10-03", kind: { value: "unexcused", ar: "غياب بدون إذن", en: "Absence without permission" }, reason: "No word from you", status: "approved" },
      { date: "2026-10-02", kind: { value: "quality", ar: "خطأ في الترجمة", en: "Translation error" }, reason: "", status: "pending" },
      { date: "2026-10-01", kind: { value: "manual", ar: "تعديل يدوي", en: "Manual adjustment" }, reason: "x", status: "rejected" },
    ],
    ...overrides,
  };
}

function serve(body: PayrollResponse | ((url: URL) => Response), role: Role = "translator") {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role, is_admin: role === "admin" })),
    [PAYROLL]: (url) => (typeof body === "function" ? body(url) : jsonResponse(body)),
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function open(route = "/payroll", lang: "ar" | "en" = "ar") {
  return renderWithProviders(
    <Routes>
      <Route path="/payroll" element={<PayrollPage />} />
      <Route path="/" element={<div>home page</div>} />
    </Routes>,
    { route, lang },
  );
}

describe("PayrollPage", () => {
  it("shows the month's pay to the cent, and the way to the full breakdown", async () => {
    serve(slip());
    const { container } = open();
    expect(await screen.findByText("5000.00")).toBeInTheDocument();
    expect(screen.getByText("750.50")).toBeInTheDocument();
    expect(screen.getByText("120.00")).toBeInTheDocument();
    expect(screen.getByText("5630.50")).toBeInTheDocument();
    expect(screen.getByText("2026-10", { selector: ".page-head__sub" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /التفاصيل كاملة/ })).toHaveAttribute("href", "/accounts/line/5/");
    // Deductions are drawn as a loss only when there are any.
    expect(container.querySelectorAll(".kpi--danger")).toHaveLength(1);
    expect(container.querySelectorAll(".kpi--ok")).toHaveLength(1);
  });

  it("shows the owner's incentive among the month's figures when there is one, and nothing when there is none", async () => {
    serve(slip({ line: { ...slip().line!, incentive: "250.00" } }));
    open();
    expect(await screen.findByText("الحوافز")).toBeInTheDocument();
    expect(screen.getByText("250.00")).toBeInTheDocument();
    cleanup();
    serve(slip({ line: { ...slip().line!, incentive: "0.00" } }));
    open();
    await screen.findByText("بونص الإنتاج");
    expect(screen.queryByText("الحوافز")).not.toBeInTheDocument();
  });

  it("draws no loss for no deductions, and no waiting bonus for none waiting", async () => {
    serve(slip({ line: { ...slip().line!, deductions: "0.00", pending_bonus: "0.00" } }));
    const { container } = open();
    await screen.findByText("5000.00");
    expect(container.querySelector(".kpi--danger")).toBeNull();
    expect(screen.queryByText(/مكافآت مستنية اعتماد/)).toBeNull();
  });

  it("says a bonus is waiting for approval when one is", async () => {
    serve(slip({ line: { ...slip().line!, pending_bonus: "300.00" } }));
    open();
    const badge = (await screen.findByText(/مكافآت مستنية اعتماد/)).closest(".badge") as HTMLElement;
    expect(within(badge).getByText("300.00")).toBeInTheDocument();
  });

  it("says the month has not been run when there is no line, and still lists the days", async () => {
    serve(slip({ line: null }));
    open();
    expect(await screen.findByText(/الشهر ده لسه ماتحسبش/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /التفاصيل كاملة/ })).toBeNull();
    expect(screen.getByText("2026-10-01")).toBeInTheDocument();
  });

  it("lists the days with the server's own words for each status, and the words written", async () => {
    serve(slip());
    const { container } = open();
    await screen.findByText("2026-10-01");
    const rows = Array.from(container.querySelectorAll("tbody tr")).map((row) => row.textContent);
    expect(rows).toEqual(["2026-10-01حاضر3100", "2026-10-02إجازة0", "2026-10-03راحة أسبوعية0"]);
    expect(screen.getByText("حاضر")).toHaveClass("badge", "badge--ok");
    expect(screen.getByText("إجازة")).toHaveClass("badge--info");
    // A tone that is not one of the badge looks is drawn plain.
    expect(screen.getByText("راحة أسبوعية")).toHaveClass("badge");
    expect(screen.getByText("راحة أسبوعية")).not.toHaveClass("badge--");
    expect(screen.getByText(/3000/)).toBeInTheDocument();
  });

  it("says what each violation is, why, and whether it was applied", async () => {
    serve(slip());
    open();
    expect(await screen.findByText(/غياب بدون إذن/)).toBeInTheDocument();
    expect(screen.getByText("No word from you")).toBeInTheDocument();
    expect(screen.getByText("مطبق")).toBeInTheDocument();
    expect(screen.getByText("مستنية اعتماد")).toBeInTheDocument();
    expect(screen.getByText("مرفوضة")).toBeInTheDocument();
  });

  it("says so when there is nothing to list", async () => {
    serve(slip({ days: [], violations: [] }));
    open();
    expect(await screen.findByText("مفيش أيام مسجلة.")).toBeInTheDocument();
    expect(screen.getByText("مفيش مخالفات.")).toBeInTheDocument();
  });

  it("speaks English when asked", async () => {
    serve(slip());
    open("/payroll", "en");
    expect(await screen.findByText("Base salary")).toBeInTheDocument();
    expect(screen.getByText("Present")).toBeInTheDocument();
    expect(screen.getByText("Absence without permission", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("Applied")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Full breakdown/ })).toBeInTheDocument();
  });

  it("asks for this month when the address names none", async () => {
    const mocked = serve(slip());
    open();
    await screen.findByText("5000.00");
    expect(mocked.calls.filter((c) => c.url.startsWith(PAYROLL)).map((c) => c.url)).toEqual([PAYROLL]);
  });

  it("asks for the month the address names", async () => {
    const mocked = serve(slip({ year: 2026, month: 9 }));
    open("/payroll?period=2026-09");
    expect(await screen.findByText("2026-09", { selector: ".page-head__sub" })).toBeInTheDocument();
    expect(mocked.calls.some((c) => c.url === `${PAYROLL}?period=2026-09`)).toBe(true);
  });

  it("does not send what is not a month: the address is the person's to type, the server is not asked about it", async () => {
    const mocked = serve(slip());
    open("/payroll?period=%3Cscript%3E");
    await screen.findByText("5000.00");
    expect(mocked.calls.filter((c) => c.url.startsWith(PAYROLL)).map((c) => c.url)).toEqual([PAYROLL]);
  });

  it("offers the thirteen months, selects the one shown, and asks again for another", async () => {
    const mocked = serve((url) => jsonResponse(url.searchParams.get("period") === "2026-8" ? slip({ year: 2026, month: 8, line: null }) : slip()));
    open();
    const picker = (await screen.findByRole("combobox", { name: "الشهر" })) as HTMLSelectElement;
    expect(Array.from(picker.options).map((o) => o.textContent)).toEqual(["2026-10", "2026-09", "2026-08"]);
    expect(picker.value).toBe("2026-10");
    await userEvent.selectOptions(picker, "2026-8");
    expect(await screen.findByText(/الشهر ده لسه ماتحسبش/)).toBeInTheDocument();
    expect(mocked.calls.some((c) => c.url === `${PAYROLL}?period=2026-8`)).toBe(true);
    expect((screen.getByRole("combobox", { name: "الشهر" }) as HTMLSelectElement).value).toBe("2026-8");
  });

  it("keeps a month typed by hand that is older than the picker goes", async () => {
    serve(slip({ year: 2023, month: 3 }));
    open("/payroll?period=2023-03");
    const picker = (await screen.findByRole("combobox", { name: "الشهر" })) as HTMLSelectElement;
    expect(picker.value).toBe("2023-3");
    expect(Array.from(picker.options).map((o) => o.textContent)).toContain("2023-03");
  });

  it("draws the way to the breakdown only for an address on this site", async () => {
    serve(slip({ line: { ...slip().line!, url: "https://evil.example/line/5/" } }));
    open();
    await screen.findByText("5000.00");
    expect(screen.queryByRole("link", { name: /التفاصيل كاملة/ })).toBeNull();
  });

  it("is for translators and the admin: anybody else is sent home without a request for it", async () => {
    const mocked = serve(slip(), "operation");
    open();
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(mocked.calls.some((c) => c.url.startsWith(PAYROLL))).toBe(false);
  });

  it("says so when it cannot load, and does not draw a half page", async () => {
    serve(() => jsonResponse({ ok: false, error: "server" }, 500));
    open();
    expect(await screen.findByRole("alert")).toHaveTextContent("حصلت مشكلة في التحميل.");
    expect(screen.queryByText("الراتب الأساسي")).toBeNull();
  });

  it("says it is loading before the answer comes", async () => {
    serve(() => new Promise<Response>(() => undefined) as unknown as Response);
    open();
    await waitFor(() => expect(screen.getByText("بيحمّل...")).toBeInTheDocument());
  });
});
