import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DayStatusJson, HrBoard, HrBoardRow, HrDay, HrReport, Role } from "../api/types";
import { ToastProvider } from "../components/Toasts";
import { jsonResponse, renderWithProviders } from "../test/helpers";
import { field, openHr, reads, serveHr, stampOf, type Handler } from "../test/hr";
import { HrAttendancePage } from "./HrAttendancePage";

afterEach(() => vi.unstubAllGlobals());

const present: DayStatusJson = { value: "present", tone: "ok", ar: "حاضر", en: "Present" };
const absent: DayStatusJson = { value: "unexcused", tone: "dead", ar: "غياب بدون إذن", en: "Unexcused" };

function row(id: number, name: string, over: Partial<HrBoardRow> = {}): HrBoardRow {
  return {
    id,
    user: { id: id + 100, name },
    date: "2026-10-03",
    work_mode: { value: "office", ar: "من المكتب", en: "Office" },
    schedule: "9 AM - 5 PM",
    check_in: stampOf("9:05 AM", "9:05 AM"),
    check_out: stampOf("5:01 PM", "5:01 PM"),
    is_open: false,
    work_minutes: 476,
    status: present,
    late_minutes: 0,
    early_leave_minutes: 0,
    short_minutes: 0,
    overtime_minutes: 0,
    off_site: false,
    extra_started_at: null,
    checkout_missed: false,
    needs_review: false,
    ...over,
  };
}

function board(over: Partial<HrBoard> = {}): HrBoard {
  return {
    ok: true,
    view: "day",
    date: "2026-10-03",
    first_day: "2026-10-03",
    last_day: "2026-10-03",
    flagged_count: 2,
    totals: { present: 2, late: 1, off_site: 1, open: 1, minutes: 900, overtime: 15 },
    truncated: false,
    rows: [
      row(1, "Sam"),
      row(2, "Nada", {
        check_out: null,
        is_open: true,
        late_minutes: 20,
        early_leave_minutes: 5,
        short_minutes: 30,
        overtime_minutes: 15,
        off_site: true,
        extra_started_at: stampOf("5:30 PM", "5:30 PM"),
        needs_review: true,
        work_minutes: 424,
      }),
      row(3, "Omar", { status: absent, check_in: null, check_out: null, work_mode: null, schedule: "", work_minutes: 0, checkout_missed: true }),
    ],
    missing: [{ user: { id: 9, name: "Hala" }, schedule: "Morning" }],
    options: {
      people: [
        { id: 101, name: "Sam" },
        { id: 102, name: "Nada" },
      ],
      roles: [
        { value: "translator", ar: "مترجم", en: "Translator" },
        { value: "operation", ar: "أوبريشن", en: "Operation" },
      ],
      day_modes: [
        { value: "office", ar: "من المكتب", en: "Office" },
        { value: "remote", ar: "عن بُعد", en: "Remote" },
      ],
      statuses: [present, absent],
      shifts: ["الصبح", "المساء"],
    },
    ...over,
  };
}

function dayJson(over: Partial<HrDay> = {}): HrDay {
  return {
    ok: true,
    day: {
      ...row(5, "Sam", { needs_review: true, checkout_missed: true }),
      review_reason: "Odd place",
      scheduled_start: stampOf("9:00 AM", "9:00 AM"),
      scheduled_end: stampOf("5:00 PM", "5:00 PM"),
      scheduled_minutes: 480,
      grace_minutes: 10,
    },
    events: [
      { kind: { value: "check_in", ar: "حضور", en: "Check in" }, at: stampOf("2026-10-03 9:05 AM", "2026-10-03 9:05 AM"), within_geofence: true, distance_m: 40, accuracy_m: 12, office: "المقر", device: "Phone", ip: "10.1.2.3" },
      { kind: { value: "check_out", ar: "انصراف", en: "Check out" }, at: stampOf("2026-10-03 5:01 PM", "2026-10-03 5:01 PM"), within_geofence: false, distance_m: 900, accuracy_m: null, office: "", device: "", ip: "" },
      { kind: { value: "extra_start", ar: "بداية اكسترا تايم", en: "Extra time start" }, at: null, within_geofence: null, distance_m: null, accuracy_m: null, office: "", device: "", ip: "" },
    ],
    edits: [{ actor: "Mona", field: "note", old: "", new: "Traffic", reason: "Told us", at: stampOf("2026-10-03 6:00 PM", "2026-10-03 6:00 PM") }],
    conf: { grace_minutes: 10 },
    form: [
      field("status", "Status", {
        kind: "select",
        value: "present",
        label_ar: "الحالة",
        label_en: "Status",
        choices: [
          { value: "present", label: "Present", label_ar: "حاضر", label_en: "Present" },
          { value: "unexcused", label: "Unexcused absence", label_ar: "غياب بدون إذن", label_en: "Unexcused absence" },
        ],
      }),
      field("check_in", "Check in", { kind: "datetime", value: "2026-10-03T09:05", label_ar: "حضور", label_en: "Check in" }),
      field("absence_reason", "Absence reason", { label_ar: "سبب الغياب", label_en: "Absence reason" }),
      field("reason", "Reason", { required: true, label_ar: "سبب التعديل (مطلوب)", label_en: "Reason for the change (required)", hint_ar: "السبب هو اللي بيخلي الرقم دليل.", hint_en: "The reason makes the figure evidence." }),
    ],
    ...over,
  };
}

function report(over: Partial<HrReport> = {}): HrReport {
  return {
    ok: true,
    year: 2026,
    month: 10,
    periods: [
      { year: 2026, month: 10 },
      { year: 2026, month: 9 },
    ],
    people: [
      { id: 101, name: "Sam" },
      { id: 102, name: "Nada" },
    ],
    person: { id: 101, name: "Sam" },
    summary: {
      scheduled_days: 22,
      present_days: 18,
      office_days: 12,
      remote_days: 6,
      leave_days: 1,
      excused_days: 1,
      absent_days: 2,
      late_days: 3,
      late_minutes: 41,
      early_leave_minutes: 15,
      short_minutes: 126,
      work_minutes: 9000,
      break_minutes: 300,
      overtime_minutes: 90,
      needs_review: 2,
      days: [
        { date: "2026-10-01", status: present, work_mode: { value: "office", ar: "من المكتب", en: "Office" }, check_in: stampOf("9:05 AM", "9:05 AM"), check_out: stampOf("5:00 PM", "5:00 PM"), break_minutes: 30, work_minutes: 450, late_minutes: 5, short_minutes: 0, overtime_minutes: 0 },
        { date: "2026-10-02", status: absent, work_mode: null, check_in: null, check_out: null, break_minutes: 0, work_minutes: 0, late_minutes: 0, short_minutes: 480, overtime_minutes: 0 },
      ],
    },
    ...over,
  };
}

function serve(who: Role, over: Record<string, Handler> = {}) {
  return serveHr(who, {
    "/api/v1/hr/attendance/": () => jsonResponse(board()),
    "/api/v1/hr/report/": () => jsonResponse(report()),
    ...over,
  });
}

const open = openHr;

describe("HrAttendancePage", () => {
  it("shows the four numbers and every person's day with its times", async () => {
    serve("hr");
    const { container } = open("/hr/attendance");
    await screen.findByText("السجل");
    expect(Array.from(container.querySelectorAll(".kpi")).map((one) => one.textContent)).toEqual(["حاضر2", "تأخير1", "بره النطاق1", "ساعات15:00"]);
    const first = container.querySelector('[data-day="1"]') as HTMLElement;
    expect(within(first).getByText("9:05 AM")).toBeInTheDocument();
    expect(within(first).getByText("5:01 PM")).toBeInTheDocument();
    expect(within(first).getByText("7:56")).toBeInTheDocument();
    expect(within(first).getByRole("link", { name: /عدّل/ })).toHaveAttribute("href", "/hr/attendance/1");
  });

  it("marks lateness, an early leave, a shortfall, overtime, a punch from outside, extra time, an open day and one that was voided", async () => {
    serve("hr");
    const { container } = open("/hr/attendance");
    await screen.findByText("السجل");
    const nada = container.querySelector('[data-day="2"]') as HTMLElement;
    expect(within(nada).getByText("تأخير 20د")).toHaveClass("badge--wait");
    expect(within(nada).getByText("مبكر 5د")).toBeInTheDocument();
    expect(within(nada).getByText("ناقص 30د")).toHaveClass("badge--dead");
    expect(within(nada).getByText("OT 15د")).toHaveClass("badge--ok");
    expect(within(nada).getByText("بره النطاق")).toBeInTheDocument();
    expect(within(nada).getByText(/اكسترا من/)).toHaveTextContent("5:30 PM");
    expect(within(nada).getByText("لسه شغال")).toBeInTheDocument();
    expect(within(nada).getByText("مراجعة")).toHaveClass("badge--wait");
    const omar = container.querySelector('[data-day="3"]') as HTMLElement;
    expect(within(omar).getByText("غياب بدون إذن")).toHaveClass("badge--dead");
    expect(within(omar).getByText("مسجلش انصراف — مش محسوب")).toBeInTheDocument();
    expect(within(omar).getAllByText("—").length).toBeGreaterThanOrEqual(3);
  });

  it("names who was rostered and has no row today", async () => {
    serve("hr");
    const { container } = open("/hr/attendance");
    await screen.findByText("السجل");
    const note = container.querySelector('[data-note="missing"]') as HTMLElement;
    expect(note).toHaveTextContent("Hala");
    expect(note).toHaveTextContent("Morning");
  });

  it("says when there is nothing in the range and when there is more than is shown", async () => {
    serve("hr", { "/api/v1/hr/attendance/": () => jsonResponse(board({ rows: [], missing: [], truncated: true })) });
    const { container } = open("/hr/attendance");
    expect(await screen.findByText("مفيش سجلات في المدى ده.")).toBeInTheDocument();
    expect(container.querySelector('[data-note="truncated"]')).not.toBeNull();
  });

  it("changes the view through the address and asks the door for that one", async () => {
    const served = serve("hr");
    const user = userEvent.setup();
    open("/hr/attendance");
    await screen.findByText("السجل");
    await user.click(screen.getByRole("tab", { name: "أسبوعي" }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/hr/attendance?view=week"));
    await waitFor(() => expect(reads(served, "/api/v1/hr/attendance/")).toContain("/api/v1/hr/attendance/?view=week"));
    await user.click(screen.getByRole("tab", { name: "يومي" }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(/^\/hr\/attendance$/));
  });

  it("filters by person, role, mode, shift and status, each in the address", async () => {
    const served = serve("hr");
    const user = userEvent.setup();
    open("/hr/attendance");
    await screen.findByText("السجل");
    await user.selectOptions(screen.getByLabelText("الموظف"), "102");
    await user.selectOptions(screen.getByLabelText("الدور"), "translator");
    await user.selectOptions(screen.getByLabelText("النظام"), "remote");
    await user.selectOptions(screen.getByLabelText("الشيفت"), "الصبح");
    await user.selectOptions(screen.getByLabelText("الحالة"), "unexcused");
    const where = () => screen.getByTestId("where").textContent ?? "";
    await waitFor(() => expect(where()).toContain("status=unexcused"));
    for (const part of ["user=102", "role=translator", "day_mode=remote", "status=unexcused"]) expect(where()).toContain(part);
    expect(decodeURIComponent(where())).toContain("shift=الصبح");
    await waitFor(() => expect(reads(served, "/api/v1/hr/attendance/").some((url) => url.includes("user=102") && url.includes("status=unexcused"))).toBe(true));
  });

  it("picks a date", async () => {
    const served = serve("hr");
    open("/hr/attendance");
    await screen.findByText("السجل");
    const date = screen.getByLabelText("اليوم");
    expect(date).toHaveValue("2026-10-03");
    fireEvent.change(date, { target: { value: "2026-09-16" } });
    await waitFor(() => expect(reads(served, "/api/v1/hr/attendance/")).toContain("/api/v1/hr/attendance/?date=2026-09-16"));
  });

  it("offers the days that need a look, and turns the filter off again", async () => {
    const served = serve("hr");
    const user = userEvent.setup();
    open("/hr/attendance");
    const button = await screen.findByRole("button", { name: /محتاج مراجعة/ });
    expect(button).toHaveTextContent("2");
    await user.click(button);
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("flagged=1"));
    await waitFor(() => expect(reads(served, "/api/v1/hr/attendance/").some((url) => url.includes("flagged=1"))).toBe(true));
    await user.click(screen.getByRole("button", { name: /محتاج مراجعة/ }));
    await waitFor(() => expect(screen.getByTestId("where")).not.toHaveTextContent("flagged"));
  });

  it("has no review button when nothing is flagged", async () => {
    serve("hr", { "/api/v1/hr/attendance/": () => jsonResponse(board({ flagged_count: 0 })) });
    open("/hr/attendance");
    await screen.findByText("السجل");
    expect(screen.queryByRole("button", { name: /محتاج مراجعة/ })).toBeNull();
  });

  it("forwards only the filters it knows to the door", async () => {
    const served = serve("hr");
    open("/hr/attendance?view=week&evil=1&date=2026-09-16");
    await screen.findByText("السجل");
    const asked = reads(served, "/api/v1/hr/attendance/");
    expect(asked[0]).toBe("/api/v1/hr/attendance/?view=week&date=2026-09-16");
  });

  it("speaks English when asked", async () => {
    serve("hr");
    const { container } = renderWithProviders(
      <ToastProvider>
        <HrAttendancePage />
      </ToastProvider>,
      { route: "/hr/attendance", lang: "en" },
    );
    await screen.findByText("The record");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Attendance board");
    expect(within(container.querySelector('[data-day="1"]') as HTMLElement).getByText("9:05 AM")).toBeInTheDocument();
  });

  it("does not ask again when the window is focused", async () => {
    const served = serve("hr");
    open("/hr/attendance");
    await screen.findByText("السجل");
    window.dispatchEvent(new Event("focus"));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(reads(served, "/api/v1/hr/attendance/")).toHaveLength(1);
  });

  it("is HR's and the admin's: anybody else is sent home and the door is not asked", async () => {
    for (const who of ["operation", "translator", "sales", "accounting", "reviewer", "team_lead"] as const) {
      const served = serve(who);
      const view = open("/hr/attendance");
      expect(await screen.findByText("home page"), who).toBeInTheDocument();
      expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/")), who).toBe(false);
      view.unmount();
    }
    serve("admin");
    open("/hr/attendance");
    expect(await screen.findByText("السجل")).toBeInTheDocument();
  });

  it("says so when the board cannot be read", async () => {
    serve("hr", { "/api/v1/hr/attendance/": () => jsonResponse({ ok: false, error: "server" }, 500) });
    open("/hr/attendance");
    expect(await screen.findByRole("alert")).toHaveTextContent("حصلت مشكلة في التحميل.");
  });
});

describe("HrDayPage", () => {
  const day = (data: HrDay = dayJson()) => ({ "/api/v1/hr/attendance/5/": () => jsonResponse(data) });

  it("draws the punches with where each was made and who made the trail", async () => {
    serve("hr", day());
    const { container } = open("/hr/attendance/5");
    await screen.findByRole("heading", { level: 1 });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Sam");
    const events = container.querySelector('[data-table="events"]') as HTMLElement;
    expect(within(events).getByText("حضور")).toBeInTheDocument();
    expect(within(events).getByText("40م · المقر")).toHaveClass("badge--ok");
    expect(within(events).getByText("900م · بره النطاق")).toHaveClass("badge--dead");
    expect(within(events).getByText("مااتفحصش")).toBeInTheDocument();
    expect(within(events).getByText("بداية اكسترا تايم")).toBeInTheDocument();
    expect(within(events).getByText("10.1.2.3")).toBeInTheDocument();
    const trail = container.querySelector('[data-table="edits"]') as HTMLElement;
    expect(within(trail).getByText("Mona")).toBeInTheDocument();
    expect(within(trail).getByText("Traffic")).toBeInTheDocument();
    expect(within(trail).getByText("Told us")).toBeInTheDocument();
  });

  it("says a day entered by hand has no punches and a day never changed has no trail", async () => {
    serve("hr", day(dayJson({ events: [], edits: [] })));
    open("/hr/attendance/5");
    expect(await screen.findByText("اليوم ده متكتب بالإيد — مفيش تسجيلات.")).toBeInTheDocument();
    expect(screen.getByText("اليوم ده مااتعدلش.")).toBeInTheDocument();
  });

  it("shows the schedule as it stood and why a voided day was voided", async () => {
    serve("hr", day());
    const { container } = open("/hr/attendance/5");
    await screen.findByText("الجدول المجمّد");
    const card = (screen.getByText("الجدول المجمّد").closest(".card") as HTMLElement).textContent ?? "";
    expect(card).toContain("9:00 AM");
    expect(card).toContain("8:00");
    expect(card).toContain("10د");
    expect(container.querySelector('[data-note="missed"]')).not.toBeNull();
  });

  it("starts the form from the day and saves only the boxes that changed, with the reason", async () => {
    const served = serve("hr", {
      ...day(),
      "/api/v1/hr/attendance/5/save/": (url, init) => served.record(url, init, { ok: true, written: ["status", "absence_reason"] }),
    });
    const user = userEvent.setup();
    open("/hr/attendance/5");
    await screen.findByText("عدّل اليوم");
    expect(screen.getByLabelText("حضور")).toHaveAttribute("type", "datetime-local");
    expect(screen.getByLabelText("حضور")).toHaveValue("2026-10-03T09:05");
    expect(within(screen.getByLabelText("الحالة")).getByRole("option", { name: "غياب بدون إذن" })).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "احفظ" });
    expect(save).toBeDisabled();
    await user.selectOptions(screen.getByLabelText("الحالة"), "unexcused");
    await user.type(screen.getByLabelText("سبب الغياب"), "Sick");
    await user.type(screen.getByLabelText("سبب التعديل (مطلوب)"), "Doctor note");
    await user.click(save);
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/attendance/5/save/")).toBe(true));
    expect(served.sent.find((post) => post.url === "/api/v1/hr/attendance/5/save/")!.body).toEqual({
      values: { status: "unexcused", absence_reason: "Sick", reason: "Doctor note" },
    });
    expect(await screen.findByText("2 تعديل")).toBeInTheDocument();
  });

  it("says nothing changed when the engine wrote nothing", async () => {
    serve("hr", {
      ...day(),
      "/api/v1/hr/attendance/5/save/": () => jsonResponse({ ok: true, written: [] }),
    });
    const user = userEvent.setup();
    open("/hr/attendance/5");
    await screen.findByText("عدّل اليوم");
    await user.type(screen.getByLabelText("سبب التعديل (مطلوب)"), "Looked");
    await user.click(screen.getByRole("button", { name: "احفظ" }));
    expect(await screen.findByText("مفيش حاجة اتغيرت")).toBeInTheDocument();
  });

  it("shows the form's refusal beside its box and keeps what was typed", async () => {
    serve("hr", {
      ...day(),
      "/api/v1/hr/attendance/5/save/": () => jsonResponse({ ok: false, error: "invalid", errors: { reason: ["This field is required."], absence_reason: ["سبب الغياب مطلوب."] } }, 400),
    });
    const user = userEvent.setup();
    open("/hr/attendance/5");
    await screen.findByText("عدّل اليوم");
    await user.selectOptions(screen.getByLabelText("الحالة"), "unexcused");
    await user.click(screen.getByRole("button", { name: "احفظ" }));
    expect(await screen.findByText("This field is required.")).toBeInTheDocument();
    expect(screen.getByText("سبب الغياب مطلوب.")).toBeInTheDocument();
    expect(screen.getByLabelText("الحالة")).toHaveValue("unexcused");
  });

  it("shows the engine's refusal in its own words", async () => {
    serve("hr", {
      ...day(),
      "/api/v1/hr/attendance/5/save/": () => jsonResponse({ ok: false, error: "no_reason", message: "لازم تكتب سبب التعديل." }, 409),
    });
    const user = userEvent.setup();
    open("/hr/attendance/5");
    await screen.findByText("عدّل اليوم");
    await user.type(screen.getByLabelText("سبب التعديل (مطلوب)"), "x");
    await user.click(screen.getByRole("button", { name: "احفظ" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("لازم تكتب سبب التعديل.");
  });

  it("marks a flagged day reviewed with the note that was typed", async () => {
    const served = serve("hr", {
      ...day(),
      "/api/v1/hr/attendance/5/clear/": (url, init) => served.record(url, init, { ok: true }),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/attendance/5");
    await screen.findByText("متعلّم للمراجعة");
    expect(container.querySelector('[data-note="flagged"]')).toHaveTextContent("Odd place");
    await user.type(screen.getByLabelText("ملاحظة المراجعة"), "Checked the map");
    await user.click(screen.getByRole("button", { name: "راجعته" }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/attendance/5/clear/")).toBe(true));
    expect(served.sent.find((post) => post.url === "/api/v1/hr/attendance/5/clear/")!.body).toEqual({ reason: "Checked the map" });
  });

  it("offers no review box for a day nobody flagged", async () => {
    serve("hr", day(dayJson({ day: { ...dayJson().day, needs_review: false, checkout_missed: false } })));
    const { container } = open("/hr/attendance/5");
    await screen.findByText("عدّل اليوم");
    expect(screen.queryByRole("button", { name: "راجعته" })).toBeNull();
    expect(container.querySelector('[data-note="missed"]')).toBeNull();
  });

  it("says a day that is not there is not there, and does not ask for one that is not a number", async () => {
    serve("hr", { "/api/v1/hr/attendance/5/": () => jsonResponse({ ok: false, error: "not_found" }, 404) });
    const view = open("/hr/attendance/5");
    expect(await screen.findByRole("alert")).toHaveTextContent("الصفحة دي مش موجودة.");
    view.unmount();
    const served = serve("hr");
    open("/hr/attendance/abc");
    expect(await screen.findByRole("alert")).toHaveTextContent("الصفحة دي مش موجودة.");
    expect(served.calls.some((call) => /attendance\/(abc|NaN)/.test(call.url))).toBe(false);
  });

  it("is HR's and the admin's", async () => {
    const served = serve("sales");
    open("/hr/attendance/5");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/"))).toBe(false);
  });
});

describe("HrReportPage", () => {
  it("draws the month: the four numbers, every day and the summary", async () => {
    serve("hr");
    const { container } = open("/hr/report");
    await screen.findByText("يوم بيوم");
    expect(Array.from(container.querySelectorAll(".kpi")).map((one) => one.textContent)).toEqual(["أيام مجدولة22", "أيام حضور18", "إجمالي الساعات150:00", "أوفرتايم1:30"]);
    const first = container.querySelector('[data-day="2026-10-01"]') as HTMLElement;
    expect(within(first).getByText("9:05 AM")).toBeInTheDocument();
    expect(within(first).getByText("7:30")).toBeInTheDocument();
    expect(within(first).getByText("5")).toHaveClass("deadline--late");
    const second = container.querySelector('[data-day="2026-10-02"]') as HTMLElement;
    expect(within(second).getByText("غياب بدون إذن")).toHaveClass("badge--dead");
    const card = (screen.getByText("الملخص").closest(".card") as HTMLElement).textContent ?? "";
    expect(card).toContain("2:06");
    expect(card).toContain("15د");
    expect(container.querySelector('[data-note="review"]')).toHaveTextContent("2");
  });

  it("moves to another person or month through the address", async () => {
    const served = serve("hr");
    const user = userEvent.setup();
    open("/hr/report");
    await screen.findByText("يوم بيوم");
    await user.selectOptions(screen.getByLabelText("الموظف"), "102");
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/hr/report?user=102"));
    await user.selectOptions(screen.getByLabelText("الشهر"), "2026-9");
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/hr/report?period=2026-9&user=102"));
    await waitFor(() => expect(reads(served, "/api/v1/hr/report/")).toContain("/api/v1/hr/report/?period=2026-9&user=102"));
  });

  it("asks to pick somebody when there is nobody", async () => {
    serve("hr", { "/api/v1/hr/report/": () => jsonResponse(report({ person: null, summary: null, people: [] })) });
    open("/hr/report");
    expect(await screen.findByText("اختار موظف.")).toBeInTheDocument();
  });

  it("says a month with no days has none", async () => {
    serve("hr", { "/api/v1/hr/report/": () => jsonResponse(report({ summary: { ...report().summary!, days: [], needs_review: 0 } })) });
    const { container } = open("/hr/report");
    expect(await screen.findByText("مفيش أيام في الشهر ده.")).toBeInTheDocument();
    expect(container.querySelector('[data-note="review"]')).toBeNull();
  });

  it("is HR's and the admin's", async () => {
    const served = serve("translator");
    open("/hr/report");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/"))).toBe(false);
  });
});
