import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  AccountsLine,
  AccountsLineRow,
  AccountsOverview,
  AccountsRules,
  AccountsSalary,
  AccountsSheet,
  AccountsViolation,
  AccountsViolations,
  FormField,
  Role,
} from "../api/types";
import { ToastProvider } from "../components/Toasts";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { AccountsAttendancePage } from "./AccountsAttendancePage";
import { AccountsLinePage } from "./AccountsLinePage";
import { AccountsOverviewPage } from "./AccountsOverviewPage";
import { AccountsRulesPage } from "./AccountsRulesPage";
import { AccountsSalaryPage } from "./AccountsSalaryPage";
import { AccountsViolationsPage } from "./AccountsViolationsPage";

afterEach(() => vi.unstubAllGlobals());

type Handler = (url: URL, init: RequestInit | undefined) => Response | Promise<Response>;

const labelled = (value: string, ar: string, en: string, tone = "ok") => ({ value, ar, en, tone });

function field(name: string, label: string, over: Partial<FormField> = {}): FormField {
  return { name, label, kind: "text", required: false, help: "", disabled: false, ltr: false, value: "", ...over };
}

function lineRow(id: number, name: string, over: Partial<AccountsLineRow> = {}): AccountsLineRow {
  return {
    id,
    user: { id: id + 100, name, username: name.toLowerCase(), initials: name.slice(0, 2).toUpperCase() },
    base_salary: "3000.00",
    worked_days: 20,
    working_days: 22,
    leave_days: 1,
    extra_leave_days: 0,
    unexcused_days: 0,
    total_words: 26000,
    below_alert: false,
    production_bonus: "150.00",
    bonus_total: "0.00",
    pending_bonus: "0.00",
    deductions: "0.00",
    net: "3150.00",
    ...over,
  };
}

function violation(id: number, over: Partial<AccountsViolation> = {}): AccountsViolation {
  return {
    id,
    user: "Sam",
    date: "2026-10-02",
    kind: { value: "quality", ar: "خطأ في الترجمة", en: "Translation error" },
    task: null,
    reason: "A mistake on page 3",
    penalty_days: "1.00",
    penalty_amount: "0.00",
    escalated: false,
    status: "pending",
    decided_by: null,
    ...over,
  };
}

function overview(over: Partial<AccountsOverview> = {}): AccountsOverview {
  return {
    ok: true,
    year: 2026,
    month: 10,
    periods: [
      { year: 2026, month: 10 },
      { year: 2026, month: 9 },
    ],
    period: { id: 7, label: "2026-10", status: { value: "draft", ar: "مسودة", en: "Draft" } },
    totals: { net: "6300.00", words: 52000, deductions: "100.00", alerts: 1 },
    lines: [lineRow(1, "Sam"), lineRow(2, "Nada", { below_alert: true, extra_leave_days: 2, unexcused_days: 1, pending_bonus: "300.00", deductions: "100.00" })],
    pending_violations: [violation(5, { escalated: true, task: "TSK-00009" })],
    missing_salary: [{ id: 41, name: "Newbie", username: "newbie", initials: "NE" }],
    unsettled_tasks: [{ code: "TSK-00004", translator: "Sam" }, { code: "TSK-00005", translator: null }],
    can: { line: true, task: true },
    ...over,
  };
}

function serve(who: Role, over: Record<string, Handler> = {}) {
  const sent: { url: string; body: unknown }[] = [];
  const record = (url: URL, init: RequestInit | undefined, answer: unknown, status = 200) => {
    sent.push({ url: url.pathname, body: init?.body ? JSON.parse(String(init.body)) : null });
    return jsonResponse(answer, status);
  };
  const defaults: Record<string, Handler> = {
    "/api/v1/me/": () => jsonResponse(me({ role: who, is_admin: who === "admin" })),
    "/api/v1/accounts/overview/": () => jsonResponse(overview()),
    "/api/v1/accounts/recalculate/": (url, init) => record(url, init, { ok: true }),
    "/api/v1/accounts/periods/7/approve/": (url, init) => record(url, init, { ok: true }),
    "/api/v1/accounts/violations/5/approve/": (url, init) => record(url, init, { ok: true }),
    "/api/v1/accounts/violations/5/reject/": (url, init) => record(url, init, { ok: true }),
  };
  // `mockFetch` answers with the first prefix that matches, so the most specific door has to come first.
  const merged = { ...defaults, ...over };
  const routes = Object.fromEntries(Object.entries(merged).sort(([a], [b]) => b.length - a.length));
  const mocked = mockFetch(routes);
  vi.stubGlobal("fetch", mocked.fn);
  return { ...mocked, sent, record };
}

function Where() {
  const where = useLocation();
  return <div data-testid="where">{where.pathname + where.search}</div>;
}

function open(route: string, lang: "ar" | "en" = "ar") {
  return renderWithProviders(
    <ToastProvider>
      <Routes>
        <Route path="/accounts" element={<AccountsOverviewPage />} />
        <Route path="/accounts/lines/:id" element={<AccountsLinePage />} />
        <Route path="/accounts/attendance" element={<AccountsAttendancePage />} />
        <Route path="/accounts/violations" element={<AccountsViolationsPage />} />
        <Route path="/accounts/rules" element={<AccountsRulesPage />} />
        <Route path="/accounts/salary/:id" element={<AccountsSalaryPage />} />
        <Route path="/tasks/:code" element={<div>one task page</div>} />
        <Route path="/" element={<div>home page</div>} />
      </Routes>
      <Where />
    </ToastProvider>,
    { route, lang },
  );
}

const reads = (served: ReturnType<typeof serve>, prefix: string) =>
  served.calls.filter((call) => call.url.startsWith(prefix) && call.init?.method !== "POST").map((call) => call.url);

describe("AccountsOverviewPage", () => {
  it("shows the four numbers and the translators' lines with money as it was written", async () => {
    serve("accounting");
    const { container } = open("/accounts");
    await screen.findByText("كشف الشهر");
    expect(Array.from(container.querySelectorAll(".kpi")).map((one) => one.textContent)).toEqual([
      "الصافي6300.00",
      "إجمالي الكلمات52000",
      "خصومات معتمدة100.00",
      "تحت حد التنبيه1",
    ]);
    const sam = container.querySelector('[data-line="1"]') as HTMLElement;
    expect(within(sam).getByText("3000.00")).toHaveClass("mono");
    expect(within(sam).getByText("3150.00")).toBeInTheDocument();
    expect(within(sam).getByText("20")).toBeInTheDocument();
  });

  it("marks what needs a second look: extra leave, absence, the alert line and a bonus awaiting release", async () => {
    serve("accounting");
    const { container } = open("/accounts");
    await screen.findByText("Nada");
    const nada = container.querySelector('[data-line="2"]') as HTMLElement;
    expect(within(nada).getByText("+2")).toHaveClass("badge--dead");
    expect(within(nada).getByText(/غياب 1/)).toHaveClass("badge--dead");
    expect(within(nada).getByText("26000")).toHaveClass("deadline--late");
    expect(within(nada).getByText(/مستنية 300.00/)).toHaveClass("badge--wait");
  });

  it("opens a payslip's detail only for who may (the admin), as the classic page does", async () => {
    serve("admin");
    const { container } = open("/accounts");
    await screen.findByText("كشف الشهر");
    expect(within(container.querySelector('[data-line="1"]') as HTMLElement).getByRole("link", { name: "التفاصيل" })).toHaveAttribute("href", "/accounts/lines/1");
  });

  it("offers no detail link to accounting", async () => {
    serve("accounting", { "/api/v1/accounts/overview/": () => jsonResponse(overview({ can: { line: false, task: false } })) });
    open("/accounts");
    await screen.findByText("كشف الشهر");
    expect(screen.queryByRole("link", { name: "التفاصيل" })).toBeNull();
    expect(screen.getByText("TSK-00004").closest("a")).toBeNull();
  });

  it("names the translators with no salary, linking to their salary page", async () => {
    serve("accounting");
    const { container } = open("/accounts");
    await screen.findByText("كشف الشهر");
    const note = container.querySelector('[data-note="salary"]') as HTMLElement;
    expect(within(note).getByRole("link", { name: "Newbie" })).toHaveAttribute("href", "/accounts/salary/41");
  });

  it("lists the jobs whose words nobody settled, as links to the task for the admin", async () => {
    serve("admin");
    const { container } = open("/accounts");
    await screen.findByText("كشف الشهر");
    const note = container.querySelector('[data-note="words"]') as HTMLElement;
    expect(within(note).getByRole("link", { name: /TSK-00004/ })).toHaveAttribute("href", "/tasks/TSK-00004");
    expect(note).toHaveTextContent("TSK-00005 —");
  });

  it("says a month that was never run has not been computed", async () => {
    serve("accounting", { "/api/v1/accounts/overview/": () => jsonResponse(overview({ period: null, totals: null, lines: [], missing_salary: [], unsettled_tasks: [] })) });
    const { container } = open("/accounts");
    expect(await screen.findByText(/الشهر ده لسه ماتحسبش/)).toBeInTheDocument();
    expect(container.querySelector(".kpi")).toBeNull();
  });

  it("runs the month it shows and says it was computed", async () => {
    const served = serve("accounting");
    const user = userEvent.setup();
    open("/accounts");
    await screen.findByText("كشف الشهر");
    await user.click(screen.getByRole("button", { name: /احسب الشهر/ }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/accounts/recalculate/")).toBe(true));
    expect(served.sent.find((post) => post.url === "/api/v1/accounts/recalculate/")!.body).toEqual({ period: "2026-10" });
    expect(await screen.findByText("اتحسب")).toBeInTheDocument();
  });

  it("says a locked month was not run again, in the server's words", async () => {
    serve("accounting", {
      "/api/v1/accounts/recalculate/": () => jsonResponse({ ok: false, error: "period_locked", message: "الشهر مقفول - مش بيتحسب تاني." }, 409),
    });
    const user = userEvent.setup();
    open("/accounts");
    await screen.findByText("كشف الشهر");
    await user.click(screen.getByRole("button", { name: /احسب الشهر/ }));
    expect(await screen.findByText("الشهر مقفول - مش بيتحسب تاني.")).toBeInTheDocument();
  });

  it("approves a draft month", async () => {
    const served = serve("accounting");
    const user = userEvent.setup();
    const { container } = open("/accounts");
    await screen.findByText("كشف الشهر");
    await user.click(container.querySelector(".card__head .btn--ok") as HTMLElement);
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/accounts/periods/7/approve/")).toBe(true));
    expect(served.sent.find((post) => post.url === "/api/v1/accounts/periods/7/approve/")!.body).toEqual({ lock: false });
  });

  it("locks an approved month only after the question is answered yes", async () => {
    const served = serve("accounting", {
      "/api/v1/accounts/overview/": () => jsonResponse(overview({ period: { id: 7, label: "2026-10", status: { value: "approved", ar: "معتمد", en: "Approved" } } })),
    });
    const user = userEvent.setup();
    open("/accounts");
    await user.click(await screen.findByRole("button", { name: "قفل الشهر" }));
    expect(served.sent.some((post) => post.url.includes("/approve/"))).toBe(false);
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "إلغاء" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(served.sent.some((post) => post.url.includes("/approve/"))).toBe(false);
    await user.click(screen.getByRole("button", { name: "قفل الشهر" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "اقفل الشهر" }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/accounts/periods/7/approve/")).toBe(true));
    expect(served.sent.find((post) => post.url === "/api/v1/accounts/periods/7/approve/")!.body).toEqual({ lock: true });
  });

  it("offers nothing to do to a locked month", async () => {
    serve("accounting", {
      "/api/v1/accounts/overview/": () => jsonResponse(overview({ period: { id: 7, label: "2026-10", status: { value: "locked", ar: "مقفول", en: "Locked" } } })),
    });
    const { container } = open("/accounts");
    expect(await screen.findByText("مقفول")).toHaveClass("badge--dead");
    expect(screen.queryByRole("button", { name: "قفل الشهر" })).toBeNull();
    expect(container.querySelector(".card__head .btn--ok")).toBeNull();
  });

  it("approves and rejects a waiting deduction from the sheet", async () => {
    const served = serve("accounting");
    const user = userEvent.setup();
    const { container } = open("/accounts");
    await screen.findByText("كشف الشهر");
    const row = container.querySelector('[data-violation="5"]') as HTMLElement;
    expect(within(row).getByText("تصعيد للمدير")).toHaveClass("badge--dead");
    await user.click(within(row).getByRole("button", { name: "اعتماد" }));
    await user.click(within(row).getByRole("button", { name: "رفض" }));
    await waitFor(() => expect(served.sent.map((post) => post.url)).toEqual(["/api/v1/accounts/violations/5/approve/", "/api/v1/accounts/violations/5/reject/"]));
  });

  it("says why a deduction could not be decided", async () => {
    serve("accounting", {
      "/api/v1/accounts/violations/5/approve/": () => jsonResponse({ ok: false, error: "already_decided", message: "اتقرر فيها قبل كده." }, 409),
    });
    const user = userEvent.setup();
    const { container } = open("/accounts");
    await screen.findByText("كشف الشهر");
    await user.click(within(container.querySelector('[data-violation="5"]') as HTMLElement).getByRole("button", { name: "اعتماد" }));
    expect(await screen.findByText("اتقرر فيها قبل كده.")).toBeInTheDocument();
  });

  it("asks for another month through the address and reads that one", async () => {
    const served = serve("accounting");
    const user = userEvent.setup();
    open("/accounts");
    await screen.findByText("كشف الشهر");
    await user.selectOptions(screen.getByLabelText("الشهر"), "2026-9");
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/accounts?period=2026-9"));
    await waitFor(() => expect(reads(served, "/api/v1/accounts/overview/")).toContain("/api/v1/accounts/overview/?period=2026-9"));
  });

  it("does not ask again when the window is focused", async () => {
    const served = serve("accounting");
    open("/accounts");
    await screen.findByText("كشف الشهر");
    window.dispatchEvent(new Event("focus"));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(reads(served, "/api/v1/accounts/overview/")).toHaveLength(1);
  });

  it("sends anybody else home and asks the server for nothing", async () => {
    for (const who of ["operation", "translator", "hr", "sales"] as const) {
      const served = serve(who);
      const view = open("/accounts");
      expect(await screen.findByText("home page"), who).toBeInTheDocument();
      expect(served.calls.some((call) => call.url.startsWith("/api/v1/accounts/")), who).toBe(false);
      view.unmount();
    }
  });

  it("says so when the sheet cannot be read", async () => {
    serve("accounting", { "/api/v1/accounts/overview/": () => jsonResponse({ ok: false, error: "server" }, 500) });
    open("/accounts");
    expect(await screen.findByRole("alert")).toHaveTextContent("حصلت مشكلة في التحميل.");
  });
});

function fullLine(over: Partial<AccountsLine["line"]> = {}): AccountsLine {
  return {
    ok: true,
    line: {
      ...lineRow(9, "Sam"),
      period: { id: 7, label: "2026-10", status: { value: "draft", ar: "مسودة", en: "Draft" } },
      label: "2026-10",
      day_value: "136.36",
      target_words: 30000,
      under_target_days: 2,
      overtime_bonus: "0.00",
      overtime_minutes: 90,
      discipline_bonus: "0.00",
      discipline_bonus_earned: true,
      target_bonus: "200.00",
      target_bonus_earned: true,
      bonuses_approved: false,
      gross: "3350.00",
      scheduled_days: 22,
      office_days: 12,
      remote_days: 8,
      late_days: 3,
      late_minutes: 41,
      early_leave_minutes: 15,
      short_minutes: 126,
      work_minutes: 9000,
      ...over,
    },
    days: [
      { date: "2026-10-01", status: labelled("present", "حاضر", "Present"), secondary: true, difficult: false, words: 1200, target: 1000, bonus: "50.00" },
      { date: "2026-10-02", status: labelled("leave", "إجازة", "Leave", "info"), secondary: false, difficult: true, words: 0, target: 1000, bonus: "0.00" },
    ],
    deductions: [
      { date: "2026-10-03", kind: { value: "quality", ar: "خطأ في الترجمة", en: "Translation error" }, reason: "Error", days: "1.00", amount: "136.36", status: "applied" },
      { date: "2026-10-04", kind: { value: "unexcused", ar: "غياب بدون إذن", en: "Absence" }, reason: "Absent", days: "1.00", amount: "136.36", status: "pending" },
    ],
    conf: { monthly_leave_allowance: 4, discipline_bonus: "100.00", target_bonus: "200.00" },
    can: { salary: true, release: true },
  };
}

describe("AccountsLinePage", () => {
  const line = (data: AccountsLine = fullLine()) => ({ "/api/v1/accounts/lines/9/bonus/": undefined as never, "/api/v1/accounts/lines/9/": () => jsonResponse(data) });

  it("draws the payslip the way it was frozen: the four numbers, the days and the deductions", async () => {
    serve("admin", { "/api/v1/accounts/lines/9/": () => jsonResponse(fullLine()) });
    const { container } = open("/accounts/lines/9");
    await screen.findByRole("heading", { level: 1 });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Sam");
    expect(Array.from(container.querySelectorAll(".kpi")).map((one) => one.textContent)).toEqual([
      "الراتب الأساسي3000.00",
      "بونص الإنتاج اليومي150.00",
      "خصومات معتمدة0.00",
      "الصافي3150.00",
    ]);
    const first = container.querySelector('[data-day="2026-10-01"]') as HTMLElement;
    expect(within(first).getByText("حاضر")).toHaveClass("badge--ok");
    expect(within(first).getByText("لغة تانية")).toHaveClass("chip");
    expect(within(container.querySelector('[data-day="2026-10-02"]') as HTMLElement).getByText("ملف صعب")).toBeInTheDocument();
    expect(within(container.querySelector('[data-deduction="applied"]') as HTMLElement).getByText("مطبق")).toHaveClass("badge--dead");
    expect(within(container.querySelector('[data-deduction="pending"]') as HTMLElement).getByText("مستنية اعتماد")).toHaveClass("badge--wait");
    expect(screen.getByText("خطأ في الترجمة")).toBeInTheDocument();
  });

  it("explains how the net was reached, with the bonuses that are earned and not yet released", async () => {
    serve("admin", { "/api/v1/accounts/lines/9/": () => jsonResponse(fullLine()) });
    const { container } = open("/accounts/lines/9");
    await screen.findByText("ملخص الحساب");
    const summary = (screen.getByText("ملخص الحساب").closest(".card") as HTMLElement).textContent ?? "";
    expect(summary).toContain("136.36 = 3000.00 / 22");
    expect(summary).toContain("1:30");
    expect(summary).toContain("100.00 مستنية");
    expect(summary).toContain("+ 200.00");
    expect(container.textContent).toContain("2:06");
    expect(container.textContent).toContain("150:00");
  });

  it("offers the salary history and the release only to who may", async () => {
    serve("admin", { "/api/v1/accounts/lines/9/": () => jsonResponse(fullLine()) });
    const view = open("/accounts/lines/9");
    expect(await screen.findByRole("link", { name: "سجل الراتب" })).toHaveAttribute("href", "/accounts/salary/109");
    expect(screen.getByRole("button", { name: /اصرف المكافآت/ })).toBeInTheDocument();
    view.unmount();
    serve("translator", { "/api/v1/accounts/lines/9/": () => jsonResponse({ ...fullLine(), can: { salary: false, release: false } }) });
    open("/accounts/lines/9");
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("link", { name: "سجل الراتب" })).toBeNull();
    expect(screen.queryByRole("button", { name: /اصرف المكافآت/ })).toBeNull();
  });

  it("releases the bonuses only after the question, then reads the payslip again", async () => {
    const served = serve("admin", {
      "/api/v1/accounts/lines/9/bonus/": (url, init) => (served.record(url, init, { ok: true }), jsonResponse({ ok: true })),
      "/api/v1/accounts/lines/9/": () => jsonResponse(fullLine()),
    });
    const user = userEvent.setup();
    open("/accounts/lines/9");
    await user.click(await screen.findByRole("button", { name: /اصرف المكافآت/ }));
    expect(served.sent).toEqual([]);
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "اصرفهم" }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/accounts/lines/9/bonus/")).toBe(true));
    await waitFor(() => expect(reads(served, "/api/v1/accounts/lines/9/").length).toBe(2));
  });

  it("keeps the question open with the reason when the release is refused", async () => {
    serve("admin", {
      "/api/v1/accounts/lines/9/bonus/": () => jsonResponse({ ok: false, error: "period_locked", message: "الشهر مقفول." }, 409),
      "/api/v1/accounts/lines/9/": () => jsonResponse(fullLine()),
    });
    const user = userEvent.setup();
    open("/accounts/lines/9");
    await user.click(await screen.findByRole("button", { name: /اصرف المكافآت/ }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "اصرفهم" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("الشهر مقفول.");
  });

  it("says a payslip that is not the person's is not there, without saying whose it is", async () => {
    serve("translator", { "/api/v1/accounts/lines/9/": () => jsonResponse({ ok: false, error: "not_found" }, 404) });
    open("/accounts/lines/9");
    expect(await screen.findByRole("alert")).toHaveTextContent("الصفحة دي مش موجودة.");
  });

  it("does not ask for a payslip that is not a number", async () => {
    const served = serve("admin");
    open("/accounts/lines/abc");
    expect(await screen.findByRole("alert")).toHaveTextContent("الصفحة دي مش موجودة.");
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/accounts/lines/"))).toBe(false);
  });

  void line;
});

function sheet(over: Partial<AccountsSheet> = {}): AccountsSheet {
  return {
    ok: true,
    year: 2026,
    month: 10,
    periods: [
      { year: 2026, month: 10 },
      { year: 2026, month: 9 },
    ],
    people: [
      { id: 11, name: "Sam" },
      { id: 12, name: "Nada" },
    ],
    person: { id: 11, name: "Sam", username: "sam", initials: "SA" },
    days: [
      { id: 1, date: "2026-10-01", status: labelled("present", "حاضر", "Present"), check_in: { ar: "9:00 ص", en: "9:00 AM" }, check_out: { ar: "5:00 م", en: "5:00 PM" }, late_minutes: 4, words: 900, under_floor: true, absence_reason: "", note: "Short day" },
      { id: 2, date: "2026-10-02", status: labelled("unexcused", "غياب بدون إذن", "Unexcused", "dead"), check_in: null, check_out: null, late_minutes: 0, words: 0, under_floor: false, absence_reason: "No call. ", note: "" },
    ],
    words: 900,
    leave_used: 5,
    conf: { monthly_leave_allowance: 4, monthly_target_words: 26000, daily_target_words: 1000 },
    form: [
      field("date", "Date", { kind: "date" }),
      field("status", "Status", { kind: "select", value: "present", choices: [{ value: "present", label: "Present" }, { value: "unexcused", label: "Unexcused absence" }] }),
      field("check_in", "Check in", { kind: "datetime" }),
      field("words", "Words", { kind: "number", value: "0" }),
      field("absence_reason", "Absence reason"),
    ],
    ...over,
  };
}

describe("AccountsAttendancePage", () => {
  it("draws one translator's month: the numbers, the days with their times and notes, and the days under the floor", async () => {
    serve("admin", { "/api/v1/accounts/attendance/": () => jsonResponse(sheet()) });
    const { container } = open("/accounts/attendance");
    await screen.findByText("2026-10-01");
    expect(Array.from(container.querySelectorAll(".kpi")).map((one) => one.textContent)).toEqual([
      "كلمات الشهر900",
      "إجازات مستخدمة5 / 4",
      "التارجت الشهري26000",
      "الحد اليومي1000",
    ]);
    expect(container.querySelector(".kpi--danger")).toHaveTextContent("إجازات مستخدمة");
    const first = container.querySelector('[data-day="2026-10-01"]') as HTMLElement;
    expect(within(first).getByText("9:00 ص")).toBeInTheDocument();
    expect(within(first).getByText("900")).toHaveClass("deadline--late");
    expect(within(first).getByText("Short day")).toBeInTheDocument();
    const second = container.querySelector('[data-day="2026-10-02"]') as HTMLElement;
    expect(within(second).getByText("غياب بدون إذن")).toHaveClass("badge--dead");
    expect(within(second).getAllByText("—")).toHaveLength(2);
  });

  it("re-derives the words from the job log once for each person and month, then reads the sheet again", async () => {
    let refreshes = 0;
    const served = serve("admin", {
      "/api/v1/accounts/attendance/refresh/": (url, init) => (refreshes++, served.record(url, init, { ok: true })),
      "/api/v1/accounts/attendance/": () => jsonResponse(sheet()),
    });
    open("/accounts/attendance");
    await screen.findByText("2026-10-01");
    await waitFor(() => expect(refreshes).toBe(1));
    expect(served.sent.find((post) => post.url === "/api/v1/accounts/attendance/refresh/")!.body).toEqual({ user: 11, period: "2026-10" });
    await waitFor(() => expect(reads(served, "/api/v1/accounts/attendance/").length).toBe(2));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(refreshes).toBe(1);
  });

  it("moves to another person or month through the address", async () => {
    const served = serve("admin", { "/api/v1/accounts/attendance/": () => jsonResponse(sheet()) });
    const user = userEvent.setup();
    open("/accounts/attendance");
    await screen.findByText("2026-10-01");
    await user.selectOptions(screen.getByLabelText("المترجم"), "12");
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/accounts/attendance?user=12"));
    await user.selectOptions(screen.getByLabelText("الشهر"), "2026-9");
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/accounts/attendance?period=2026-9&user=12"));
    await waitFor(() => expect(reads(served, "/api/v1/accounts/attendance/")).toContain("/api/v1/accounts/attendance/?period=2026-9&user=12"));
  });

  it("records a day with the form's own boxes, sending what was typed and the person", async () => {
    const served = serve("admin", { "/api/v1/accounts/attendance/": () => jsonResponse(sheet()), "/api/v1/accounts/attendance/save/": (url, init) => served.record(url, init, { ok: true, id: 3 }) });
    const user = userEvent.setup();
    open("/accounts/attendance");
    await screen.findByText("2026-10-01");
    expect(screen.getByLabelText("Date")).toHaveAttribute("type", "date");
    expect(screen.getByLabelText("Check in")).toHaveAttribute("type", "datetime-local");
    const save = screen.getByRole("button", { name: "احفظ" });
    expect(save).toBeDisabled();
    await user.type(screen.getByLabelText("Date"), "2026-10-05");
    await user.selectOptions(screen.getByLabelText("Status"), "unexcused");
    await user.type(screen.getByLabelText("Absence reason"), "No call");
    await user.click(save);
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/accounts/attendance/save/")).toBe(true));
    expect(served.sent.find((post) => post.url === "/api/v1/accounts/attendance/save/")!.body).toEqual({
      user: 11,
      values: { date: "2026-10-05", status: "unexcused", absence_reason: "No call" },
    });
  });

  it("shows the form's refusal beside its box and keeps what was typed", async () => {
    serve("admin", {
      "/api/v1/accounts/attendance/": () => jsonResponse(sheet()),
      "/api/v1/accounts/attendance/save/": () => jsonResponse({ ok: false, error: "invalid", errors: { absence_reason: ["سبب الغياب مطلوب."] } }, 400),
    });
    const user = userEvent.setup();
    open("/accounts/attendance");
    await screen.findByText("2026-10-01");
    await user.type(screen.getByLabelText("Date"), "2026-10-05");
    await user.selectOptions(screen.getByLabelText("Status"), "unexcused");
    await user.click(screen.getByRole("button", { name: "احفظ" }));
    expect(await screen.findByText("سبب الغياب مطلوب.")).toBeInTheDocument();
    expect(screen.getByLabelText("Date")).toHaveValue("2026-10-05");
  });

  it("says there is nobody to record for when there is no translator", async () => {
    serve("admin", { "/api/v1/accounts/attendance/": () => jsonResponse(sheet({ people: [], person: null, days: [] })) });
    open("/accounts/attendance");
    expect(await screen.findByText("مفيش أيام مسجلة في الشهر ده.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "احفظ" })).toBeDisabled();
  });

  it("sends anybody else home and asks the server for nothing", async () => {
    const served = serve("translator");
    open("/accounts/attendance");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/accounts/"))).toBe(false);
  });
});

function violations(over: Partial<AccountsViolations> = {}): AccountsViolations {
  return {
    ok: true,
    pending: [violation(5, { task: "TSK-00009" })],
    decided: [violation(6, { status: "approved", decided_by: "Mona" }), violation(7, { status: "rejected", decided_by: "Mona", user: "Nada" })],
    conf: { quality_penalty_days: "1.00", unexcused_penalty_days: "2.00", low_output_penalty_days: "0.50", extra_leave_penalty_days: "1.00", target_miss_penalty: "250.00" },
    form: [
      field("user", "Translator", { kind: "select", value: "", choices: [{ value: "", label: "---------" }, { value: "11", label: "Sam" }] }),
      field("task", "Task", { kind: "select", value: "", choices: [{ value: "", label: "---------" }, { value: "3", label: "TSK-00003" }] }),
      field("date", "Date", { kind: "date" }),
      field("penalty_days", "Days", { kind: "number" }),
      field("reason", "Reason"),
    ],
    ...over,
  };
}

describe("AccountsViolationsPage", () => {
  it("lists what waits and what was decided, with who decided", async () => {
    serve("accounting", { "/api/v1/accounts/violations/": () => jsonResponse(violations()) });
    const { container } = open("/accounts/violations");
    await screen.findByText("A mistake on page 3");
    const waiting = container.querySelector('[data-table="pending"]') as HTMLElement;
    expect(within(waiting).getByText("TSK-00009")).toHaveClass("mono");
    const decided = container.querySelector('[data-table="decided"]') as HTMLElement;
    expect(within(decided.querySelector('[data-violation="6"]') as HTMLElement).getByText("مطبق")).toHaveClass("badge--dead");
    expect(within(decided.querySelector('[data-violation="7"]') as HTMLElement).getByText("مرفوض")).toHaveClass("badge--info");
    expect(within(decided).getAllByText("Mona")).toHaveLength(2);
  });

  it("shows the default penalties, with days only where they are days", async () => {
    serve("accounting", { "/api/v1/accounts/violations/": () => jsonResponse(violations()) });
    open("/accounts/violations");
    const card = (await screen.findByText("القيم الافتراضية")).closest(".card") as HTMLElement;
    expect(within(card).getByText("خطأ ترجمة").parentElement).toHaveTextContent("1.00 يوم");
    expect(within(card).getByText("التارجت مااتحققش").parentElement).toHaveTextContent("250.00");
    expect(within(card).getByText("التارجت مااتحققش").parentElement).not.toHaveTextContent("يوم");
  });

  it("approves and rejects", async () => {
    const served = serve("accounting", {
      "/api/v1/accounts/violations/": () => jsonResponse(violations()),
      "/api/v1/accounts/violations/5/approve/": (url, init) => served.record(url, init, { ok: true }),
      "/api/v1/accounts/violations/5/reject/": (url, init) => served.record(url, init, { ok: true }),
    });
    const user = userEvent.setup();
    const { container } = open("/accounts/violations");
    await screen.findByText("A mistake on page 3");
    const row = (container.querySelector('[data-table="pending"]') as HTMLElement).querySelector('[data-violation="5"]') as HTMLElement;
    await user.click(within(row).getByRole("button", { name: "اعتماد" }));
    await user.click(within(row).getByRole("button", { name: "رفض" }));
    await waitFor(() => expect(served.sent.map((post) => post.url)).toEqual(["/api/v1/accounts/violations/5/approve/", "/api/v1/accounts/violations/5/reject/"]));
  });

  it("proposes a deduction with the form's boxes", async () => {
    const served = serve("accounting", {
      "/api/v1/accounts/violations/": () => jsonResponse(violations()),
      "/api/v1/accounts/violations/create/": (url, init) => served.record(url, init, { ok: true, id: 9 }),
    });
    const user = userEvent.setup();
    open("/accounts/violations");
    await screen.findByText("A mistake on page 3");
    const submit = screen.getByRole("button", { name: "سجل" });
    expect(submit).toBeDisabled();
    await user.selectOptions(screen.getByLabelText("Translator"), "11");
    await user.selectOptions(screen.getByLabelText("Task"), "3");
    await user.type(screen.getByLabelText("Date"), "2026-10-04");
    await user.type(screen.getByLabelText("Days"), "1");
    await user.type(screen.getByLabelText("Reason"), "Wrong term");
    await user.click(submit);
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/accounts/violations/create/")).toBe(true));
    expect(served.sent.find((post) => post.url === "/api/v1/accounts/violations/create/")!.body).toEqual({
      values: { user: "11", task: "3", date: "2026-10-04", penalty_days: "1", reason: "Wrong term" },
    });
  });

  it("labels the tasks by code and shows the form's refusal beside the box", async () => {
    serve("accounting", {
      "/api/v1/accounts/violations/": () => jsonResponse(violations()),
      "/api/v1/accounts/violations/create/": () => jsonResponse({ ok: false, error: "invalid", errors: { penalty_days: ["حدد خصم بالأيام أو بالمبلغ."] } }, 400),
    });
    const user = userEvent.setup();
    open("/accounts/violations");
    await screen.findByText("A mistake on page 3");
    expect(within(screen.getByLabelText("Task")).getByRole("option", { name: "TSK-00003" })).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Translator"), "11");
    await user.click(screen.getByRole("button", { name: "سجل" }));
    expect(await screen.findByText("حدد خصم بالأيام أو بالمبلغ.")).toBeInTheDocument();
  });

  it("sends anybody else home", async () => {
    const served = serve("sales");
    open("/accounts/violations");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/accounts/"))).toBe(false);
  });
});

function salary(over: Partial<AccountsSalary> = {}): AccountsSalary {
  return {
    ok: true,
    person: { id: 11, name: "Sam", username: "sam", initials: "SA" },
    records: [
      { id: 2, effective_from: "2026-01-01", amount: "3500.00", note: "Raise", by: "Mona" },
      { id: 1, effective_from: "2020-01-01", amount: "3000.00", note: "", by: null },
    ],
    lines: [{ id: 9, label: "2026-09", base_salary: "3500.00", words: 25000, net: "3650.00" }],
    can: { line: true, set: true },
    form: [field("amount", "Salary", { kind: "number" }), field("effective_from", "Effective from", { kind: "date" }), field("note", "Note")],
    ...over,
  };
}

describe("AccountsSalaryPage", () => {
  it("lists the salaries newest first and the months computed on them", async () => {
    serve("accounting", { "/api/v1/accounts/salary/11/": () => jsonResponse(salary({ can: { line: false, set: false } })) });
    const { container } = open("/accounts/salary/11");
    await screen.findByText("Raise");
    const rows = Array.from((container.querySelector('[data-table="salaries"]') as HTMLElement).querySelectorAll("tbody tr")).map((row) => row.textContent);
    expect(rows[0]).toContain("2026-01-01");
    expect(rows[1]).toContain("2020-01-01");
    expect(within(container.querySelector('[data-table="months"]') as HTMLElement).queryByRole("link")).toBeNull();
  });

  it("links a month to its payslip for who may open one", async () => {
    serve("admin", { "/api/v1/accounts/salary/11/": () => jsonResponse(salary()) });
    open("/accounts/salary/11");
    expect(await screen.findByRole("link", { name: "التفاصيل" })).toHaveAttribute("href", "/accounts/lines/9");
  });

  it("says a person with no salary computes to zero", async () => {
    serve("accounting", { "/api/v1/accounts/salary/11/": () => jsonResponse(salary({ records: [], lines: [] })) });
    open("/accounts/salary/11");
    expect(await screen.findByText(/السطر هيطلع بصفر/)).toBeInTheDocument();
    expect(screen.getByText("لسه مفيش شهور محسوبة.")).toBeInTheDocument();
  });

  it("gives accounting the history and no form: the owner alone sets a salary", async () => {
    serve("accounting", { "/api/v1/accounts/salary/11/": () => jsonResponse(salary({ can: { line: false, set: false } })) });
    const { container } = open("/accounts/salary/11");
    await screen.findByText("Raise");
    expect(container.querySelector('[data-card="new-salary"]')).toBeNull();
    expect(screen.queryByLabelText("Salary")).toBeNull();
    expect(container.querySelector('[data-note="owner-sets"]')).not.toBeNull();
  });

  it("adds a salary and starts the form clean again", async () => {
    const served = serve("admin", {
      "/api/v1/accounts/salary/11/save/": (url, init) => served.record(url, init, { ok: true, id: 3 }),
      "/api/v1/accounts/salary/11/": () => jsonResponse(salary()),
    });
    const user = userEvent.setup();
    open("/accounts/salary/11");
    await screen.findByText("Raise");
    const submit = screen.getByRole("button", { name: "سجل" });
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText("Salary"), "4000");
    await user.type(screen.getByLabelText("Effective from"), "2026-11-01");
    await user.click(submit);
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/accounts/salary/11/save/")).toBe(true));
    expect(served.sent.find((post) => post.url === "/api/v1/accounts/salary/11/save/")!.body).toEqual({ values: { amount: "4000", effective_from: "2026-11-01" } });
    await waitFor(() => expect(screen.getByLabelText("Salary")).toHaveValue(null));
  });

  it("shows the form's refusal beside its box", async () => {
    serve("admin", {
      "/api/v1/accounts/salary/11/save/": () => jsonResponse({ ok: false, error: "invalid", errors: { amount: ["Enter a number."] } }, 400),
      "/api/v1/accounts/salary/11/": () => jsonResponse(salary()),
    });
    const user = userEvent.setup();
    open("/accounts/salary/11");
    await screen.findByText("Raise");
    await user.type(screen.getByLabelText("Effective from"), "2026-11-01");
    await user.click(screen.getByRole("button", { name: "سجل" }));
    expect(await screen.findByText("Enter a number.")).toBeInTheDocument();
  });

  it("says a person that is not there is not there", async () => {
    serve("accounting", { "/api/v1/accounts/salary/11/": () => jsonResponse({ ok: false, error: "not_found" }, 404) });
    open("/accounts/salary/11");
    expect(await screen.findByRole("alert")).toHaveTextContent("الصفحة دي مش موجودة.");
  });
});

function rules(over: Partial<AccountsRules> = {}): AccountsRules {
  return {
    ok: true,
    fields: [
      field("daily_hours", "Daily hours", { kind: "number", value: "8.00", label_ar: "ساعات اليوم", label_en: "Hours a day" }),
      field("working_days_per_month", "Days", { kind: "number", value: 22, label_ar: "أيام العمل في الشهر", label_en: "Working days a month", hint_ar: "قيمة اليوم = الراتب ÷ الرقم ده.", hint_en: "A day is worth the salary divided by this." }),
      field("monthly_target_words", "Target", { kind: "number", value: 26000, label_ar: "التارجت الشهري", label_en: "Monthly target" }),
      field("bonuses_need_approval", "Bonuses", { kind: "checkbox", value: true, label_ar: "المكافأتين محتاجين اعتماد المدير قبل الصرف", label_en: "The two bonuses need the manager to release them" }),
      field("weight_quality", "Quality", { kind: "number", value: 1, label_ar: "الجودة", label_en: "Quality" }),
    ],
    sections: [
      { key: "month", icon: "calendar", ar: "الشهر واليوم", en: "The month and the day", fields: ["daily_hours", "working_days_per_month", "monthly_target_words"] },
      { key: "bonuses", icon: "star", ar: "المكافآت", en: "Bonuses", fields: ["bonuses_need_approval"] },
      { key: "performance", icon: "chart", ar: "أوزان تقييم الأداء", en: "Performance weights", note_ar: "دي نِسَب مش مجموع.", note_en: "These are ratios.", fields: ["weight_quality"] },
    ],
    tiers: {
      primary: [{ id: 1, min_words: 1000, max_words: 1500, bonus: "10.00" }, { id: 2, min_words: 1500, max_words: null, bonus: "25.00" }],
      secondary: [],
    },
    tier_form: [
      field("scale", "Scale", { kind: "select", value: "primary", choices: [{ value: "primary", label: "Primary language" }, { value: "secondary", label: "Secondary language" }] }),
      field("min_words", "Above", { kind: "number" }),
      field("max_words", "Up to", { kind: "number" }),
      field("bonus", "Bonus", { kind: "number" }),
    ],
    check: { working_days: 22, daily_target_words: 1000, monthly_target_words: 26000 },
    ...over,
  };
}

describe("AccountsRulesPage", () => {
  it("draws the sections with the classic page's words and notes", async () => {
    serve("admin", { "/api/v1/accounts/rules/": () => jsonResponse(rules()) });
    const { container } = open("/accounts/rules");
    await screen.findByText("الشهر واليوم");
    expect(Array.from(container.querySelectorAll("[data-section]")).map((one) => one.getAttribute("data-section"))).toEqual(["month", "bonuses", "performance"]);
    expect(screen.getByLabelText("ساعات اليوم")).toHaveValue(8);
    expect(screen.getByText("قيمة اليوم = الراتب ÷ الرقم ده.")).toHaveClass("helptext");
    expect(screen.getByLabelText("المكافأتين محتاجين اعتماد المدير قبل الصرف")).toBeChecked();
    expect(screen.getByText("دي نِسَب مش مجموع.")).toBeInTheDocument();
  });

  it("sends only the boxes that changed", async () => {
    const served = serve("admin", {
      "/api/v1/accounts/rules/save/": (url, init) => served.record(url, init, { ok: true }),
      "/api/v1/accounts/rules/": () => jsonResponse(rules()),
    });
    const user = userEvent.setup();
    open("/accounts/rules");
    await screen.findByText("الشهر واليوم");
    const save = screen.getByRole("button", { name: "حفظ" });
    expect(save).toBeDisabled();
    await user.clear(screen.getByLabelText("ساعات اليوم"));
    await user.type(screen.getByLabelText("ساعات اليوم"), "7");
    await user.click(screen.getByLabelText("المكافأتين محتاجين اعتماد المدير قبل الصرف"));
    await user.click(save);
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/accounts/rules/save/")).toBe(true));
    expect(served.sent.find((post) => post.url === "/api/v1/accounts/rules/save/")!.body).toEqual({ values: { daily_hours: "7", bonuses_need_approval: false } });
  });

  it("shows what the form refused beside the box, with nothing saved", async () => {
    serve("admin", {
      "/api/v1/accounts/rules/save/": () => jsonResponse({ ok: false, error: "invalid", errors: { monthly_target_words: ["أكبر من 22 يوم × 1000 كلمة = 22000."] } }, 400),
      "/api/v1/accounts/rules/": () => jsonResponse(rules()),
    });
    const user = userEvent.setup();
    open("/accounts/rules");
    await screen.findByText("الشهر واليوم");
    await user.clear(screen.getByLabelText("التارجت الشهري"));
    await user.type(screen.getByLabelText("التارجت الشهري"), "99999");
    await user.click(screen.getByRole("button", { name: "حفظ" }));
    expect(await screen.findByText(/أكبر من 22 يوم/)).toBeInTheDocument();
    expect(screen.getByLabelText("التارجت الشهري")).toHaveValue(99999);
  });

  it("lists the bands by scale and removes one", async () => {
    const served = serve("admin", {
      "/api/v1/accounts/rules/tiers/2/delete/": (url, init) => served.record(url, init, { ok: true, deleted: 1 }),
      "/api/v1/accounts/rules/": () => jsonResponse(rules()),
    });
    const user = userEvent.setup();
    const { container } = open("/accounts/rules");
    await screen.findByText("شرائح بونص الإنتاج اليومي");
    const primary = container.querySelector('[data-tiers="primary"]') as HTMLElement;
    expect(within(primary.querySelector('[data-tier="2"]') as HTMLElement).getByText("—")).toBeInTheDocument();
    expect(within(container.querySelector('[data-tiers="secondary"]') as HTMLElement).getByText("مفيش شرائح.")).toBeInTheDocument();
    await user.click(within(primary.querySelector('[data-tier="2"]') as HTMLElement).getByRole("button", { name: "شيل" }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/accounts/rules/tiers/2/delete/")).toBe(true));
  });

  it("adds a band and shows the form's refusal when it ends where it starts", async () => {
    const served = serve("admin", {
      "/api/v1/accounts/rules/tiers/add/": (url, init) => served.record(url, init, { ok: true, id: 3 }),
      "/api/v1/accounts/rules/": () => jsonResponse(rules()),
    });
    const user = userEvent.setup();
    open("/accounts/rules");
    await screen.findByText("شرائح بونص الإنتاج اليومي");
    await user.type(screen.getByLabelText("Above"), "3000");
    await user.type(screen.getByLabelText("Up to"), "3500");
    await user.type(screen.getByLabelText("Bonus"), "75");
    await user.click(screen.getByRole("button", { name: /ضيف شريحة/ }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/accounts/rules/tiers/add/")).toBe(true));
    expect(served.sent.find((post) => post.url === "/api/v1/accounts/rules/tiers/add/")!.body).toEqual({ values: { min_words: "3000", max_words: "3500", bonus: "75" } });
  });

  it("shows the check that the target can be reached", async () => {
    serve("admin", { "/api/v1/accounts/rules/": () => jsonResponse(rules()) });
    open("/accounts/rules");
    const card = (await screen.findByText("اتأكد إن الأرقام متسقة")).closest(".card") as HTMLElement;
    expect(card).toHaveTextContent("22 × 1000");
    expect(card).toHaveTextContent("26000");
  });

  it("is the admin's alone: accounting is sent home and asks the server for nothing", async () => {
    const served = serve("accounting");
    open("/accounts/rules");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/accounts/"))).toBe(false);
  });
});
