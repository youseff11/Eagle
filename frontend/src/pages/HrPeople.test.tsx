import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  DayStatusJson,
  HrComplaints,
  HrEmployee,
  HrPerformance,
  HrProbation,
  HrRegister,
  HrSalaryPlans,
  HrSalaryRequest,
  HrSalaryRequests,
  Role,
} from "../api/types";
import { jsonResponse } from "../test/helpers";
import { field, openHr as open, reads, serveHr, stampOf, type Handler } from "../test/hr";

afterEach(() => vi.unstubAllGlobals());

const serve = (who: Role, routes: Record<string, Handler>) => serveHr(who, routes);

const confirmed: DayStatusJson = { value: "active", tone: "ok", ar: "مثبّت", en: "Confirmed" };
const onProbation: DayStatusJson = { value: "probation", tone: "wait", ar: "تحت الاختبار", en: "Probation" };
const pendingReview: DayStatusJson = { value: "pending", tone: "wait", ar: "مستني", en: "Pending" };
const good: DayStatusJson = { value: "good", tone: "ok", ar: "كويس", en: "Good" };
const unknown: DayStatusJson = { value: "unknown", tone: "", ar: "مابتتقاسش", en: "Not measured" };

function register(over: Partial<HrRegister> = {}): HrRegister {
  return {
    ok: true,
    rows: [
      { id: 11, code: "EMP-0042", name: "Sam", role: { value: "translator", ar: "مترجم", en: "Translator" }, department: "اللغويات", employment: { value: "full_time", ar: "دوام كامل", en: "Full time" }, joining_date: "2025-01-05", status: confirmed },
      { id: 12, code: "", name: "Nada", role: { value: "operation", ar: "أوبريشن", en: "Operation" }, department: null, employment: { value: "part_time", ar: "دوام جزئي", en: "Part time" }, joining_date: null, status: onProbation },
    ],
    options: { departments: [{ id: 3, label: "اللغويات" }], statuses: [confirmed, onProbation] },
    ...over,
  };
}

describe("HrEmployeesPage", () => {
  const page = (data: HrRegister = register()) => ({ "/api/v1/hr/employees/": () => jsonResponse(data) });

  it("lists everybody active with a link to the file", async () => {
    serve("hr", page());
    const { container } = open("/hr/employees");
    await screen.findByText("السجل");
    const first = container.querySelector('[data-person="11"]') as HTMLElement;
    expect(within(first).getByRole("link", { name: "EMP-0042" })).toHaveAttribute("href", "/hr/employees/11");
    expect(first).toHaveTextContent("اللغويات");
    expect(within(first).getByText("مثبّت")).toHaveClass("badge--ok");
    const second = container.querySelector('[data-person="12"]') as HTMLElement;
    expect(within(second).getByRole("link", { name: "—" })).toHaveAttribute("href", "/hr/employees/12");
    expect(within(second).getByText("تحت الاختبار")).toHaveClass("badge--wait");
  });

  it("filters by department and status through the address, and forwards only those", async () => {
    const served = serve("hr", page());
    const user = userEvent.setup();
    open("/hr/employees?evil=1");
    await screen.findByText("السجل");
    expect(reads(served, "/api/v1/hr/employees/")[0]).toBe("/api/v1/hr/employees/");
    await user.selectOptions(screen.getByLabelText("القسم"), "3");
    await user.selectOptions(screen.getByLabelText("الحالة"), "probation");
    await waitFor(() => expect(reads(served, "/api/v1/hr/employees/").some((url) => url.includes("department=3") && url.includes("status=probation"))).toBe(true));
  });

  it("says when nobody is there", async () => {
    serve("hr", page(register({ rows: [] })));
    open("/hr/employees");
    expect(await screen.findByText("مفيش موظفين.")).toBeInTheDocument();
  });

  it("is HR's and the admin's", async () => {
    const served = serve("operation", page());
    open("/hr/employees");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/"))).toBe(false);
  });
});

function employee(over: Partial<HrEmployee> = {}): HrEmployee {
  return {
    ok: true,
    person: {
      id: 11,
      name: "Sam",
      role: { value: "translator", ar: "مترجم", en: "Translator" },
      status: onProbation,
      code: "EMP-0042",
      job_title: "Translator",
      department: "اللغويات",
      manager: "Mona",
      languages: "AR/EN",
      joining_date: "2025-01-05",
      employment: { value: "full_time", ar: "دوام كامل", en: "Full time" },
      work_mode: { value: "office", ar: "من المكتب", en: "Office" },
      probation_start: "2026-09-01",
      probation_end: "2026-11-30",
      phone: "01000000000",
      attendance_enabled: true,
    },
    summary: { scheduled_days: 22, present_days: 18, office_days: 12, remote_days: 6, leave_days: 1, absent_days: 2, late_days: 3, work_minutes: 9000, overtime_minutes: 90 },
    shifts: [{ id: 1, weekday: { value: 0, ar: "الاتنين", en: "Monday" }, template: "الصبح", start: stampOf("9:00 ص", "9:00 AM"), end: stampOf("5:00 م", "5:00 PM"), crosses_midnight: false, minutes: 480, work_mode: null, is_active: true }],
    picker: {
      current: 3,
      has_custom: false,
      templates: [{ id: 3, label: "الصبح", start: stampOf("9:00 ص", "9:00 AM"), end: stampOf("5:00 م", "5:00 PM") }],
      days: [
        { num: 5, ar: "السبت", en: "Saturday", checked: true },
        { num: 0, ar: "الاتنين", en: "Monday", checked: true },
        { num: 4, ar: "الجمعة", en: "Friday", checked: false },
      ],
    },
    work_mode_card: { work_mode: { value: "office", ar: "من المكتب", en: "Office" }, is_hybrid: false, offices: [{ label: "المقر", radius_meters: 200 }], pinned_days: 0, policy_reject: false },
    probation: [{ stage: { value: "day_30", ar: "مراجعة 30 يوم", en: "30-day review" }, due_date: "2026-10-01", outcome: pendingReview }],
    leave: [{ id: 1, kind: { value: "annual", ar: "إجازة اعتيادية", en: "Annual leave" }, is_permission: false, start_date: "2026-10-12", end_date: "2026-10-13", days: 2, minutes: 0, start_time: null, end_time: null, status: { value: "approved", tone: "ok", ar: "اتوافق عليه", en: "Approved" }, is_open: false, reason: "", decision_note: "" }],
    plan: { current: { id: 5, name: "Plan A", overrides: ["daily_target_words", "extra_word_rate"] }, options: [{ id: 5, name: "Plan A" }, { id: 6, name: "Plan B" }] },
    application: { code: "CAN-0007", applied_on: "2025-01-01" },
    salary: [{ effective_from: "2025-01-01", amount: "3500.50" }],
    can: { edit: false, shift: true, plan: false },
    ...over,
  };
}

describe("HrEmployeePage", () => {
  const page = (data: HrEmployee = employee()) => ({ "/api/v1/hr/employees/11/": () => jsonResponse(data) });

  it("draws the person's details and this month's attendance with a way to the full report", async () => {
    serve("hr", page());
    const { container } = open("/hr/employees/11");
    await screen.findByText("البيانات");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Sam");
    const details = (screen.getByText("البيانات").closest(".card") as HTMLElement).textContent ?? "";
    for (const part of ["EMP-0042", "اللغويات", "Mona", "AR/EN", "2025-01-05", "2026-09-01 → 2026-11-30", "01000000000", "دوام كامل"]) expect(details).toContain(part);
    const attendance = container.querySelector('[data-card="attendance"]') as HTMLElement;
    expect(Array.from(attendance.querySelectorAll(".kpi")).map((one) => one.textContent)).toEqual(["أيام حضور18 / 22", "تأخير3", "ساعات150:00", "أوفرتايم1:30"]);
    expect(within(attendance).getByRole("link", { name: "التقرير الكامل" })).toHaveAttribute("href", "/hr/report?user=11");
  });

  it("says attendance is off for an account that does not clock in", async () => {
    serve("hr", page(employee({ summary: null })));
    const { container } = open("/hr/employees/11");
    await screen.findByText("البيانات");
    expect(container.querySelector('[data-note="attendance-off"]')).not.toBeNull();
    expect(container.querySelector('[data-card="attendance"]')).toBeNull();
  });

  it("shows the roster, the probation reviews, recent leave, the application and the salary history", async () => {
    serve("hr", page());
    const { container } = open("/hr/employees/11");
    await screen.findByText("البيانات");
    const roster = container.querySelector('[data-card="roster"]') as HTMLElement;
    expect(roster).toHaveTextContent("9:00 ص–5:00 م");
    expect(within(roster).getByRole("link", { name: /عدّل الجدول/ })).toHaveAttribute("href", "/hr/schedules?user=11");
    expect(container.querySelector('[data-card="probation"]')).toHaveTextContent("مراجعة 30 يوم");
    expect(container.querySelector('[data-card="leave"]')).toHaveTextContent("إجازة اعتيادية");
    expect(within(container.querySelector('[data-card="application"]') as HTMLElement).getByRole("link", { name: "CAN-0007" })).toHaveAttribute("href", "/hr/candidates/CAN-0007");
    expect(container.querySelector('[data-card="salary"]')).toHaveTextContent("3500.50");
  });

  it("offers the edit and the pay plan to the admin only", async () => {
    serve("hr", page());
    const view = open("/hr/employees/11");
    await screen.findByText("البيانات");
    expect(screen.queryByRole("link", { name: /عدّل$/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "اربطه" })).toBeNull();
    view.unmount();
    serve("admin", page(employee({ can: { edit: true, shift: true, plan: true } })));
    open("/hr/employees/11");
    await screen.findByText("البيانات");
    expect(screen.getByRole("link", { name: /عدّل$/ })).toHaveAttribute("href", "/admin/users/11");
    expect(screen.getByRole("button", { name: "اربطه" })).toBeInTheDocument();
  });

  it("assigns a plan, or takes it off", async () => {
    const served = serve("admin", {
      ...page(employee({ can: { edit: true, shift: true, plan: true } })),
      "/api/v1/hr/employees/11/plan/": (url, init) => served.record(url, init, { ok: true }),
    });
    const user = userEvent.setup();
    open("/hr/employees/11");
    await screen.findByText("البيانات");
    const select = screen.getByLabelText("خطة الراتب", { selector: "select" });
    expect(select).toHaveValue("5");
    await user.selectOptions(select, "6");
    await user.click(screen.getByRole("button", { name: "اربطه" }));
    await user.selectOptions(select, "");
    await user.click(screen.getByRole("button", { name: "اربطه" }));
    await waitFor(() => expect(served.sent).toHaveLength(2));
    expect(served.sent.map((post) => post.body)).toEqual([{ plan: 6 }, { plan: null }]);
  });

  it("saves the shift with what was picked", async () => {
    const served = serve("hr", {
      ...page(),
      "/api/v1/hr/employees/11/shift/": (url, init) => served.record(url, init, { ok: true, label: "الصبح" }),
    });
    const user = userEvent.setup();
    open("/hr/employees/11");
    await screen.findByText("الشيفت");
    await user.click(screen.getByRole("checkbox", { name: "الجمعة" }));
    await user.click(screen.getByRole("button", { name: "احفظ الشيفت" }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/employees/11/shift/")).toBe(true));
    expect(served.sent[0]!.body).toEqual({ template: "3", weekdays: [5, 0, 4], new_name: "", new_start: "", new_end: "" });
  });

  it("says in words why a shift choice was refused", async () => {
    serve("hr", {
      ...page(),
      "/api/v1/hr/employees/11/shift/": () => jsonResponse({ ok: false, error: "no_days" }, 400),
    });
    const user = userEvent.setup();
    open("/hr/employees/11");
    await screen.findByText("الشيفت");
    await user.click(screen.getByRole("button", { name: "احفظ الشيفت" }));
    expect(await screen.findByText("اختار أيام الشغل.")).toBeInTheDocument();
  });

  it("saves home or office, and offers hybrid only to somebody already on it", async () => {
    const served = serve("hr", {
      ...page(),
      "/api/v1/hr/employees/11/work-mode/": (url, init) => served.record(url, init, { ok: true }),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/employees/11");
    await screen.findByText("مكان الشغل");
    const card = container.querySelector('[data-card="work-mode"]') as HTMLElement;
    expect(within(card).queryByLabelText(/هجين/)).toBeNull();
    const save = within(card).getByRole("button", { name: "احفظ" });
    expect(save).toBeDisabled();
    await user.click(within(card).getByLabelText(/من البيت/));
    await user.click(save);
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/employees/11/work-mode/")).toBe(true));
    expect(served.sent[0]!.body).toEqual({ work_mode: "remote" });
  });

  it("offers hybrid when the person is on it, and says where punches are checked", async () => {
    const data = employee();
    data.work_mode_card = { ...data.work_mode_card!, work_mode: { value: "hybrid", ar: "هجين", en: "Hybrid" }, is_hybrid: true, pinned_days: 2, policy_reject: true };
    serve("hr", page(data));
    const { container } = open("/hr/employees/11");
    await screen.findByText("مكان الشغل");
    const card = container.querySelector('[data-card="work-mode"]') as HTMLElement;
    expect(within(card).getByLabelText(/^هجين/)).toBeChecked();
    expect(card).toHaveTextContent("المقر");
    expect(card).toHaveTextContent("200 متر");
    expect(card).toHaveTextContent("التسجيل بيترفض");
    expect(card).toHaveTextContent("في 2 يوم");
  });

  it("warns when no office is set, and points to where to set one", async () => {
    const data = employee();
    data.work_mode_card = { ...data.work_mode_card!, offices: [] };
    serve("hr", page(data));
    const { container } = open("/hr/employees/11");
    await screen.findByText("مكان الشغل");
    const note = container.querySelector('[data-note="no-office"]') as HTMLElement;
    expect(within(note).getByRole("link", { name: "سجّل المكتب والنطاق" })).toHaveAttribute("href", "/hr/offices");
  });

  it("says a person that is not there is not there, and does not ask for one that is not a number", async () => {
    serve("hr", { "/api/v1/hr/employees/11/": () => jsonResponse({ ok: false, error: "not_found" }, 404) });
    const view = open("/hr/employees/11");
    expect(await screen.findByRole("alert")).toHaveTextContent("الصفحة دي مش موجودة.");
    view.unmount();
    const served = serve("hr", page());
    open("/hr/employees/abc");
    expect(await screen.findByRole("alert")).toHaveTextContent("الصفحة دي مش موجودة.");
    expect(served.calls.some((call) => /employees\/(abc|NaN)/.test(call.url))).toBe(false);
  });

  it("is HR's and the admin's", async () => {
    const served = serve("translator", page());
    open("/hr/employees/11");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/"))).toBe(false);
  });
});

function probation(over: Partial<HrProbation> = {}): HrProbation {
  return {
    ok: true,
    state: "open",
    rows: [
      { id: 1, user: { id: 11, name: "Sam" }, stage: { value: "day_30", ar: "مراجعة 30 يوم", en: "30-day review" }, due_date: "2026-10-01", overdue: true, outcome: pendingReview, score: null, decided: false, reviewer: null },
      { id: 2, user: { id: 11, name: "Sam" }, stage: { value: "day_60", ar: "مراجعة 60 يوم", en: "60-day review" }, due_date: "2026-10-30", overdue: false, outcome: { value: "confirmed", tone: "ok", ar: "اتثبّت", en: "Confirmed" }, score: 8, decided: true, reviewer: "Mona" },
    ],
    form: [
      field("outcome", "Outcome", { kind: "select", value: "", label_ar: "النتيجة", label_en: "Outcome", choices: [{ value: "", label: "---" }, { value: "confirmed", label: "Confirmed", label_ar: "تثبيت", label_en: "Confirm" }, { value: "extended", label: "Extended", label_ar: "تمديد", label_en: "Extend" }] }),
      field("score", "Score", { kind: "number", label_ar: "التقييم من 10", label_en: "Score out of 10" }),
      field("extend_days", "Extend", { kind: "number", value: 30, label_ar: "تمديد (يوم)", label_en: "Extend (days)" }),
    ],
    on_probation: [
      { id: 11, name: "Sam", department: "اللغويات", probation_end: "2026-11-30", has_reviews: true },
      { id: 13, name: "Omar", department: null, probation_end: null, has_reviews: false },
    ],
    due_count: 1,
    ...over,
  };
}

describe("HrProbationPage", () => {
  const page = (data: HrProbation = probation()) => ({ "/api/v1/hr/probation/": () => jsonResponse(data) });

  it("lists the reviews, marks an overdue one, and says how many have come due", async () => {
    serve("hr", page());
    const { container } = open("/hr/probation");
    await screen.findByText("المراجعات");
    expect(container.querySelector('[data-note="due"]')).toHaveTextContent("1");
    expect(within(container.querySelector('[data-review="1"]') as HTMLElement).getByText("2026-10-01")).toHaveClass("deadline--late");
    const decided = container.querySelector('[data-review="2"]') as HTMLElement;
    expect(decided).toHaveTextContent("8/10");
    expect(decided).toHaveTextContent("Mona");
    expect(within(decided).queryByRole("button")).toBeNull();
  });

  it("changes the list through the address", async () => {
    const served = serve("hr", page());
    const user = userEvent.setup();
    open("/hr/probation");
    await screen.findByText("المراجعات");
    await user.click(screen.getByRole("tab", { name: "المستحقة" }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/hr/probation?state=due"));
    await waitFor(() => expect(reads(served, "/api/v1/hr/probation/")).toContain("/api/v1/hr/probation/?state=due"));
    await user.click(screen.getByRole("tab", { name: "المفتوحة" }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(/^\/hr\/probation$/));
  });

  it("decides a review with the form's boxes, sending only what was changed", async () => {
    const served = serve("hr", {
      ...page(),
      "/api/v1/hr/probation/1/decide/": (url, init) => served.record(url, init, { ok: true }),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/probation");
    await screen.findByText("المراجعات");
    const row = container.querySelector('[data-review="1"]') as HTMLElement;
    expect(within(row).queryByLabelText("النتيجة")).toBeNull();
    await user.click(within(row).getByRole("button", { name: /قرّر/ }));
    const save = within(row).getByRole("button", { name: "احفظ" });
    expect(save).toBeDisabled();
    await user.selectOptions(within(row).getByLabelText("النتيجة"), "confirmed");
    await user.type(within(row).getByLabelText("التقييم من 10"), "9");
    await user.click(save);
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/probation/1/decide/")).toBe(true));
    expect(served.sent[0]!.body).toEqual({ values: { outcome: "confirmed", score: "9" } });
  });

  it("shows the form's refusal, and the engine's refusal in its own words", async () => {
    let engine = false;
    serve("hr", {
      ...page(),
      "/api/v1/hr/probation/1/decide/": () =>
        engine
          ? jsonResponse({ ok: false, error: "refused", message: "المراجعة دي اتقرر فيها بالفعل." }, 409)
          : jsonResponse({ ok: false, error: "invalid", errors: { extend_days: ["اكتب مدة التمديد."] } }, 400),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/probation");
    await screen.findByText("المراجعات");
    const row = container.querySelector('[data-review="1"]') as HTMLElement;
    await user.click(within(row).getByRole("button", { name: /قرّر/ }));
    await user.selectOptions(within(row).getByLabelText("النتيجة"), "extended");
    await user.click(within(row).getByRole("button", { name: "احفظ" }));
    expect(await screen.findByText("اكتب مدة التمديد.")).toBeInTheDocument();
    engine = true;
    await user.click(within(row).getByRole("button", { name: "احفظ" }));
    expect(await within(row).findByRole("alert")).toHaveTextContent("المراجعة دي اتقرر فيها بالفعل.");
  });

  it("opens the reviews for somebody who has none, and only for them", async () => {
    const served = serve("hr", {
      ...page(),
      "/api/v1/hr/probation/open/13/": (url, init) => served.record(url, init, { ok: true, created: 3 }),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/probation");
    await screen.findByText("تحت الاختبار");
    expect(within(container.querySelector('[data-person="11"]') as HTMLElement).queryByRole("button")).toBeNull();
    await user.click(within(container.querySelector('[data-person="13"]') as HTMLElement).getByRole("button", { name: /افتح المراجعات/ }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/probation/open/13/")).toBe(true));
    expect(await screen.findByText("3 مراجعة اتفتحت")).toBeInTheDocument();
  });

  it("says nobody is on probation and no review is there", async () => {
    serve("hr", page(probation({ rows: [], on_probation: [], due_count: 0 })));
    const { container } = open("/hr/probation");
    expect(await screen.findByText("مفيش مراجعات.")).toBeInTheDocument();
    expect(screen.getByText("مفيش حد تحت الاختبار.")).toBeInTheDocument();
    expect(container.querySelector('[data-note="due"]')).toBeNull();
  });

  it("is HR's and the admin's", async () => {
    const served = serve("sales", page());
    open("/hr/probation");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/"))).toBe(false);
  });
});

function performance(over: Partial<HrPerformance> = {}): HrPerformance {
  return {
    ok: true,
    year: 2026,
    month: 10,
    periods: [{ year: 2026, month: 10 }, { year: 2026, month: 9 }],
    people: [{ id: 11, name: "Sam" }, { id: 12, name: "Nada" }],
    person: { id: 11, name: "Sam" },
    report: {
      weights: { productivity: 40, quality: 30, deadline: 20, attendance: 10 },
      parts: {
        productivity: { score: 85, band: good, words: 22000, target: 26000 },
        quality: { score: null, band: unknown, reviewer_avg: null, reviewed: 0, complaints: 0, violations: 0, reason: { ar: "لسه ماتقيّمش حاجة", en: "Nothing has been marked yet" } },
        deadline: { score: 90, band: good, late: 1, total: 10 },
        attendance: { score: 100, band: good, present: 20, scheduled: 20, late_days: 0 },
      },
      overall: 88,
      band: good,
      projects: 10,
      returned_projects: 2,
      revision_rate: 20,
    },
    ...over,
  };
}

describe("HrPerformancePage", () => {
  const page = (data: HrPerformance = performance()) => ({ "/api/v1/hr/performance/": () => jsonResponse(data) });

  it("draws each indicator with its weight, its bar and the figures behind it", async () => {
    serve("hr", page());
    const { container } = open("/hr/performance");
    await screen.findByText("المؤشرات");
    const productivity = container.querySelector('[data-part="productivity"]') as HTMLElement;
    expect(productivity).toHaveTextContent("40%");
    expect(productivity).toHaveTextContent("85%");
    expect(productivity).toHaveTextContent("22000 / 26000");
    expect(productivity.querySelector(".meter--good i")).toHaveStyle({ width: "85%" });
    expect(within(productivity).getByText("كويس")).toHaveClass("badge--ok");
    expect(container.querySelector('[data-part="deadline"]')).toHaveTextContent("1 متأخر من 10");
    expect(container.querySelector('[data-part="attendance"]')).toHaveTextContent("20 / 20 يوم");
  });

  it("draws an indicator with no data as an empty bar that says why, not as zero", async () => {
    serve("hr", page());
    const { container } = open("/hr/performance");
    await screen.findByText("المؤشرات");
    const quality = container.querySelector('[data-part="quality"]') as HTMLElement;
    expect(quality.querySelector(".meter--empty")).not.toBeNull();
    expect(quality).toHaveTextContent("—");
    expect(quality).toHaveTextContent("لسه ماتقيّمش حاجة");
    expect(within(quality).getByText("مابتتقاسش")).toBeInTheDocument();
  });

  it("shows the overall and the month in numbers", async () => {
    serve("hr", page());
    const { container } = open("/hr/performance");
    await screen.findByText("المؤشرات");
    expect(container.querySelector('[data-card="overall"]')).toHaveTextContent("88%");
    const month = (screen.getByText("الشهر في أرقام").closest(".card") as HTMLElement).textContent ?? "";
    expect(month).toContain("10");
    expect(month).toContain("20%");
    expect(screen.getByRole("link", { name: /ملف الموظف/ })).toHaveAttribute("href", "/hr/employees/11");
  });

  it("speaks English when asked", async () => {
    serve("hr", page());
    const { renderWithProviders } = await import("../test/helpers");
    const { HrPerformancePage } = await import("./HrPerformancePage");
    const { container } = renderWithProviders(<HrPerformancePage />, { route: "/hr/performance", lang: "en" });
    await screen.findByText("Indicators");
    expect(container.querySelector('[data-part="quality"]')).toHaveTextContent("Nothing has been marked yet");
  });

  it("moves to another person or month through the address", async () => {
    const served = serve("hr", page());
    const user = userEvent.setup();
    open("/hr/performance");
    await screen.findByText("المؤشرات");
    await user.selectOptions(screen.getByLabelText("الموظف"), "12");
    await user.selectOptions(screen.getByLabelText("الشهر"), "2026-9");
    await waitFor(() => expect(reads(served, "/api/v1/hr/performance/")).toContain("/api/v1/hr/performance/?period=2026-9&user=12"));
  });

  it("asks to pick somebody when there is nobody", async () => {
    serve("hr", page(performance({ person: null, report: null, people: [] })));
    open("/hr/performance");
    expect(await screen.findByText("اختار موظف.")).toBeInTheDocument();
  });

  it("is HR's and the admin's", async () => {
    const served = serve("accounting", page());
    open("/hr/performance");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/"))).toBe(false);
  });
});

function complaints(over: Partial<HrComplaints> = {}): HrComplaints {
  return {
    ok: true,
    rows: [
      { id: 1, date: "2026-10-02", summary: "Late delivery", detail: "x".repeat(120), translator: "Sam", task: "TSK-00009", severity: { value: "high", tone: "dead", ar: "خطيرة", en: "Serious" }, resolved: false },
      { id: 2, date: "2026-10-01", summary: "Wrong term", detail: "", translator: null, task: null, severity: { value: "low", tone: "low", ar: "بسيطة", en: "Minor" }, resolved: true },
    ],
    people: [{ id: 11, name: "Sam" }],
    form: [
      field("summary", "Summary", { label_ar: "الملخص", label_en: "Summary" }),
      field("task", "Task", { kind: "select", value: "", label_ar: "التاسك", label_en: "Task", choices: [{ value: "", label: "---" }, { value: "9", label: "TSK-00009" }] }),
      field("severity", "Severity", { kind: "select", value: "medium", label_ar: "الدرجة", label_en: "Severity", choices: [{ value: "medium", label: "Needs attention", label_ar: "محتاجة انتباه", label_en: "Attention" }, { value: "high", label: "Serious", label_ar: "خطيرة", label_en: "Serious" }] }),
    ],
    ...over,
  };
}

describe("HrComplaintsPage", () => {
  const page = (data: HrComplaints = complaints()) => ({ "/api/v1/hr/complaints/": () => jsonResponse(data) });

  it("lists the complaints with the task by code, a long detail cut, and the severity in words", async () => {
    serve("hr", page());
    const { container } = open("/hr/complaints");
    await screen.findByText("المسجّل");
    const first = container.querySelector('[data-complaint="1"]') as HTMLElement;
    expect(first).toHaveTextContent("Late delivery");
    expect(first).toHaveTextContent("TSK-00009");
    expect(first.textContent).toContain("…");
    expect(within(first).getByText("خطيرة")).toBeInTheDocument();
    const second = container.querySelector('[data-complaint="2"]') as HTMLElement;
    expect(within(second).getByRole("button", { name: /اتقفلت/ })).toBeInTheDocument();
    expect(within(first).getByRole("button", { name: /اقفلها/ })).toBeInTheDocument();
  });

  it("closes a complaint or opens it again", async () => {
    const served = serve("hr", {
      ...page(),
      "/api/v1/hr/complaints/1/resolve/": (url, init) => served.record(url, init, { ok: true, resolved: true }),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/complaints");
    await screen.findByText("المسجّل");
    await user.click(within(container.querySelector('[data-complaint="1"]') as HTMLElement).getByRole("button", { name: /اقفلها/ }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/complaints/1/resolve/")).toBe(true));
  });

  it("logs a complaint with the form's boxes, sending what was filled", async () => {
    const served = serve("hr", {
      ...page(),
      "/api/v1/hr/complaints/create/": (url, init) => served.record(url, init, { ok: true, id: 5 }),
    });
    const user = userEvent.setup();
    open("/hr/complaints");
    await screen.findByText("سجّل شكوى");
    const log = screen.getByRole("button", { name: "سجّل" });
    expect(log).toBeDisabled();
    await user.type(screen.getByLabelText("الملخص"), "Wrong term");
    await user.selectOptions(screen.getByLabelText("التاسك"), "9");
    await user.selectOptions(screen.getByLabelText("الدرجة"), "high");
    await user.click(log);
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/complaints/create/")).toBe(true));
    expect(served.sent[0]!.body).toEqual({ values: { summary: "Wrong term", task: "9", severity: "high" } });
    expect(await screen.findByText("اتسجلت")).toBeInTheDocument();
  });

  it("shows the form's refusal beside its box and keeps what was typed", async () => {
    serve("hr", {
      ...page(),
      "/api/v1/hr/complaints/create/": () => jsonResponse({ ok: false, error: "invalid", errors: { summary: ["This field is required."] } }, 400),
    });
    const user = userEvent.setup();
    open("/hr/complaints");
    await screen.findByText("سجّل شكوى");
    await user.selectOptions(screen.getByLabelText("الدرجة"), "high");
    await user.click(screen.getByRole("button", { name: "سجّل" }));
    expect(await screen.findByText("This field is required.")).toBeInTheDocument();
    expect(screen.getByLabelText("الدرجة")).toHaveValue("high");
  });

  it("filters by translator through the address", async () => {
    const served = serve("hr", page());
    const user = userEvent.setup();
    open("/hr/complaints");
    await screen.findByText("المسجّل");
    await user.selectOptions(screen.getByLabelText("المترجم", { selector: "select" }), "11");
    await waitFor(() => expect(reads(served, "/api/v1/hr/complaints/")).toContain("/api/v1/hr/complaints/?translator=11"));
  });

  it("says there are no complaints, which is good news", async () => {
    serve("hr", page(complaints({ rows: [] })));
    open("/hr/complaints");
    expect(await screen.findByText("مفيش شكاوى — وده خبر كويس.")).toBeInTheDocument();
  });

  it("is HR's and the admin's", async () => {
    const served = serve("reviewer", page());
    open("/hr/complaints");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/"))).toBe(false);
  });
});

function pendingRequest(over: Partial<HrSalaryRequest> = {}): HrSalaryRequest {
  return {
    id: 1,
    user: { id: 11, name: "Sam" },
    current_amount: "3000.00",
    new_amount: "3500.00",
    delta: "500.00",
    effective_from: "2026-11-01",
    reason: "Raise",
    status: "pending",
    requested_by: "Hala",
    decided_by: null,
    ...over,
  };
}

function requests(over: Partial<HrSalaryRequests> = {}): HrSalaryRequests {
  return {
    ok: true,
    people: [{ id: 11, name: "Sam" }, { id: 12, name: "Nada" }],
    person: null,
    current: null,
    form: [
      field("new_amount", "New salary", { kind: "number", step: "0.01", label_ar: "الراتب الجديد", label_en: "New salary" }),
      field("effective_from", "Effective from", { kind: "date", value: "2026-10-04", label_ar: "ساري من", label_en: "Effective from" }),
      field("reason", "Reason", { label_ar: "السبب", label_en: "Reason" }),
    ],
    pending: [pendingRequest()],
    decided: [pendingRequest({ id: 2, status: "approved", decided_by: "Mona" }), pendingRequest({ id: 3, status: "rejected", decided_by: "Mona", delta: "-100.00", new_amount: "2900.00" })],
    can: { decide: false },
    ...over,
  };
}

describe("HrSalaryRequestsPage", () => {
  const page = (data: HrSalaryRequests = requests()) => ({ "/api/v1/hr/salary-requests/": () => jsonResponse(data) });

  it("shows what waits with the change as text, and says it is with the owner when this person is not the owner", async () => {
    serve("hr", page());
    const { container } = open("/hr/salary-requests");
    await screen.findByText("مستني قرار المالك");
    const waiting = container.querySelector('[data-pending="1"]') as HTMLElement;
    expect(waiting).toHaveTextContent("3000.00 → 3500.00");
    expect(within(waiting).getByText("(500.00)")).toHaveClass("deadline--ok");
    expect(waiting).toHaveTextContent("Hala");
    expect(waiting).toHaveTextContent("Raise");
    expect(within(waiting).getByText("مستني المالك")).toHaveClass("badge--wait");
    expect(within(waiting).queryByRole("button", { name: "وافق" })).toBeNull();
  });

  it("lists the decisions with who decided", async () => {
    serve("hr", page());
    const { container } = open("/hr/salary-requests");
    await screen.findByText("اتقرر فيها");
    expect(within(container.querySelector('[data-decided="2"]') as HTMLElement).getByText("اتوافق عليه")).toHaveClass("badge--ok");
    const rejected = container.querySelector('[data-decided="3"]') as HTMLElement;
    expect(within(rejected).getByText("مرفوض")).toHaveClass("badge--dead");
    expect(rejected).toHaveTextContent("Mona");
  });

  it("gives the owner the buttons, and sends the reason only with a rejection", async () => {
    const served = serve("admin", {
      ...page(requests({ can: { decide: true }, pending: [pendingRequest(), pendingRequest({ id: 4, user: { id: 12, name: "Nada" } })] })),
      "/api/v1/hr/salary-requests/1/approve/": (url, init) => served.record(url, init, { ok: true }),
      "/api/v1/hr/salary-requests/4/reject/": (url, init) => served.record(url, init, { ok: true }),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/salary-requests");
    await screen.findByText("مستني قرار المالك");
    const first = container.querySelector('[data-pending="1"]') as HTMLElement;
    await user.type(within(first).getByLabelText("السبب"), "changed my mind");
    await user.click(within(first).getByRole("button", { name: "وافق" }));
    const second = container.querySelector('[data-pending="4"]') as HTMLElement;
    await user.type(within(second).getByLabelText("السبب"), "Not now");
    await user.click(within(second).getByRole("button", { name: "ارفض" }));
    await waitFor(() => expect(served.sent).toHaveLength(2));
    expect(served.sent[0]).toEqual({ url: "/api/v1/hr/salary-requests/1/approve/", body: { note: "" } });
    expect(served.sent[1]).toEqual({ url: "/api/v1/hr/salary-requests/4/reject/", body: { note: "Not now" } });
  });

  it("says in the engine's words why a decision did not go", async () => {
    serve("admin", {
      ...page(requests({ can: { decide: true } })),
      "/api/v1/hr/salary-requests/1/approve/": () => jsonResponse({ ok: false, error: "refused", message: "الطلب ده اتقرر فيه بالفعل." }, 409),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/salary-requests");
    await screen.findByText("مستني قرار المالك");
    await user.click(within(container.querySelector('[data-pending="1"]') as HTMLElement).getByRole("button", { name: "وافق" }));
    expect(await screen.findByText("الطلب ده اتقرر فيه بالفعل.")).toBeInTheDocument();
  });

  it("asks for a person first, then shows their salary and the form", async () => {
    const served = serve("hr", {
      "/api/v1/hr/salary-requests/": (url) =>
        jsonResponse(url.searchParams.get("user") === "11" ? requests({ person: { id: 11, name: "Sam" }, current: "3000.00" }) : requests()),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/salary-requests");
    await screen.findByText("اطلب تغيير");
    expect(screen.queryByLabelText("الراتب الجديد")).toBeNull();
    await user.selectOptions(screen.getByLabelText("الموظف"), "11");
    await waitFor(() => expect(container.querySelector("[data-current]")).toHaveTextContent("3000.00"));
    expect(screen.getByLabelText("الراتب الجديد")).toBeInTheDocument();
    expect(reads(served, "/api/v1/hr/salary-requests/")).toContain("/api/v1/hr/salary-requests/?user=11");
  });

  it("sends the request to the owner with what was typed and the person", async () => {
    const served = serve("hr", {
      "/api/v1/hr/salary-requests/create/": (url, init) => served.record(url, init, { ok: true, id: 9 }),
      "/api/v1/hr/salary-requests/": () => jsonResponse(requests({ person: { id: 11, name: "Sam" }, current: "3000.00" })),
    });
    const user = userEvent.setup();
    open("/hr/salary-requests?user=11");
    await screen.findByText("اطلب تغيير");
    const send = screen.getByRole("button", { name: "ابعت للمالك" });
    expect(send).toBeDisabled();
    await user.type(screen.getByLabelText("الراتب الجديد"), "3500");
    await user.type(screen.getByLabelText("السبب"), "Raise");
    await user.click(send);
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/salary-requests/create/")).toBe(true));
    expect(served.sent[0]!.body).toEqual({ user: 11, values: { new_amount: "3500", reason: "Raise" } });
    expect(await screen.findByText("الطلب اتبعت للمالك")).toBeInTheDocument();
  });

  it("shows the form's refusal and the engine's refusal", async () => {
    let engine = false;
    serve("hr", {
      "/api/v1/hr/salary-requests/create/": () =>
        engine
          ? jsonResponse({ ok: false, error: "refused", message: "فيه طلب تاني لسه مستني للموظف ده." }, 409)
          : jsonResponse({ ok: false, error: "invalid", errors: { new_amount: ["This field is required."] } }, 400),
      "/api/v1/hr/salary-requests/": () => jsonResponse(requests({ person: { id: 11, name: "Sam" }, current: "3000.00" })),
    });
    const user = userEvent.setup();
    open("/hr/salary-requests?user=11");
    await screen.findByText("اطلب تغيير");
    await user.type(screen.getByLabelText("السبب"), "Raise");
    await user.click(screen.getByRole("button", { name: "ابعت للمالك" }));
    expect(await screen.findByText("This field is required.")).toBeInTheDocument();
    engine = true;
    await user.click(screen.getByRole("button", { name: "ابعت للمالك" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("فيه طلب تاني لسه مستني للموظف ده.");
  });

  it("is HR's and the admin's", async () => {
    const served = serve("operation", page());
    open("/hr/salary-requests");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/"))).toBe(false);
  });
});

function plans(over: Partial<HrSalaryPlans> = {}): HrSalaryPlans {
  return {
    ok: true,
    rows: [
      { id: 5, name: "Plan A", note: "Senior", is_active: true, overrides: ["daily_target_words", "extra_word_rate"], extra_word_rate: "0.0500", fixed_allowance: "150.00", members: 2 },
      { id: 6, name: "Plan B", note: "", is_active: false, overrides: [], extra_word_rate: null, fixed_allowance: "0.00", members: 0 },
    ],
    editing: null,
    form: [
      field("name", "Name", { label_ar: "الاسم", label_en: "Name" }),
      field("daily_target_words", "Daily", { kind: "number", label_ar: "التارجت اليومي", label_en: "Daily quota", hint_ar: "الشركة: 3000", hint_en: "Company: 3000" }),
      field("is_active", "Active", { kind: "checkbox", value: true, label_ar: "شغالة", label_en: "Active" }),
    ],
    unassigned: 4,
    ...over,
  };
}

describe("HrSalaryPlansPage", () => {
  const page = (data: HrSalaryPlans = plans()) => ({ "/api/v1/hr/salary-plans/": () => jsonResponse(data) });

  it("lists the plans with what they change and who is on them, and says how many are on the company's rules", async () => {
    serve("admin", page());
    const { container } = open("/hr/salary-plans");
    await screen.findByText("الخطط");
    const first = container.querySelector('[data-plan="5"]') as HTMLElement;
    expect(first).toHaveTextContent("daily_target_words · extra_word_rate");
    expect(first).toHaveTextContent("0.0500");
    expect(first).toHaveTextContent("150.00");
    expect(first).toHaveTextContent("Senior");
    const second = container.querySelector('[data-plan="6"]') as HTMLElement;
    expect(within(second).getByText("مقفولة")).toBeInTheDocument();
    expect(second).toHaveTextContent("شرائح الشركة");
    expect(container.querySelector("[data-unassigned]")).toHaveTextContent("4");
  });

  it("puts the company's own number beside the box it falls back for", async () => {
    serve("admin", page());
    open("/hr/salary-plans");
    await screen.findByText("الخطط");
    expect(screen.getByText("الشركة: 3000")).toHaveClass("helptext");
  });

  it("adds a plan: no id is sent, and the form starts clean again", async () => {
    const served = serve("admin", {
      ...page(),
      "/api/v1/hr/salary-plans/save/": (url, init) => served.record(url, init, { ok: true, id: 7 }),
    });
    const user = userEvent.setup();
    open("/hr/salary-plans");
    await screen.findByText("خطة جديدة", { selector: "h3" });
    const save = screen.getByRole("button", { name: "احفظ" });
    expect(save).toBeDisabled();
    await user.type(screen.getByLabelText("الاسم"), "Plan C");
    await user.type(screen.getByLabelText("التارجت اليومي"), "2500");
    await user.click(save);
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/salary-plans/save/")).toBe(true));
    expect(served.sent[0]!.body).toEqual({ values: { name: "Plan C", daily_target_words: "2500" } });
    await waitFor(() => expect(screen.getByLabelText("الاسم")).toHaveValue(""));
  });

  it("changes a plan by id with only what changed", async () => {
    const served = serve("admin", {
      "/api/v1/hr/salary-plans/": (url) =>
        jsonResponse(url.searchParams.get("edit") === "5" ? plans({ editing: 5, form: plans().form.map((one) => (one.name === "name" ? { ...one, value: "Plan A" } : one)) }) : plans()),
      "/api/v1/hr/salary-plans/save/": (url, init) => served.record(url, init, { ok: true, id: 5 }),
    });
    const user = userEvent.setup();
    open("/hr/salary-plans?edit=5");
    await screen.findByText("تعديل خطة");
    expect(screen.getByLabelText("الاسم")).toHaveValue("Plan A");
    await user.type(screen.getByLabelText("التارجت اليومي"), "2600");
    await user.click(screen.getByRole("button", { name: "احفظ" }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/salary-plans/save/")).toBe(true));
    expect(served.sent[0]!.body).toEqual({ id: 5, values: { daily_target_words: "2600" } });
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(/^\/hr\/salary-plans$/));
  });

  it("shows the form's refusal beside its box", async () => {
    serve("admin", {
      ...page(),
      "/api/v1/hr/salary-plans/save/": () => jsonResponse({ ok: false, error: "invalid", errors: { name: ["Salary plan with this Name already exists."] } }, 400),
    });
    const user = userEvent.setup();
    open("/hr/salary-plans");
    await screen.findByText("الخطط");
    await user.type(screen.getByLabelText("الاسم"), "Plan A");
    await user.click(screen.getByRole("button", { name: "احفظ" }));
    expect(await screen.findByText("Salary plan with this Name already exists.")).toBeInTheDocument();
  });

  it("is the admin's alone: HR is sent home and nothing is asked", async () => {
    const served = serve("hr", page());
    open("/hr/salary-plans");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/"))).toBe(false);
  });
});

