import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { HrDevice, HrDevices, HrOffices, HrOvertime, HrSchedules, HrShifts, Role } from "../api/types";
import { jsonResponse } from "../test/helpers";
import { field, openHr as open, reads, serveHr, stampOf, type Handler } from "../test/hr";

afterEach(() => vi.unstubAllGlobals());

const serve = (who: Role, routes: Record<string, Handler>) => serveHr(who, routes);

const WEEKDAYS = [
  { value: "", label: "---------", label_ar: "— اختار —", label_en: "— Choose —" },
  { value: "0", label: "Monday", label_ar: "الاتنين", label_en: "Monday" },
  { value: "2", label: "Wednesday", label_ar: "الأربع", label_en: "Wednesday" },
];

function schedules(over: Partial<HrSchedules> = {}): HrSchedules {
  return {
    ok: true,
    people: [
      { id: 11, name: "Sam" },
      { id: 12, name: "Nada" },
    ],
    person: { id: 11, name: "Sam", employment: { value: "full_time", ar: "دوام كامل", en: "Full time" }, work_mode: { value: "office", ar: "من المكتب", en: "Office" }, schedule_kind: "Fixed" },
    shifts: [
      { id: 1, weekday: { value: 0, ar: "الاتنين", en: "Monday" }, template: "الصبح", start: stampOf("9:00 AM", "9:00 AM"), end: stampOf("5:00 PM", "5:00 PM"), crosses_midnight: false, minutes: 480, work_mode: null, is_active: true },
      { id: 2, weekday: { value: 2, ar: "الأربع", en: "Wednesday" }, template: null, start: stampOf("10:00 PM", "10:00 PM"), end: stampOf("6:00 AM", "6:00 AM"), crosses_midnight: true, minutes: 300, work_mode: { value: "remote", ar: "عن بُعد", en: "Remote" }, is_active: false },
    ],
    overrides: [
      { id: 7, date: "2026-10-05", is_day_off: true, label: "", work_mode: null, reason: "Wedding" },
      { id: 8, date: "2026-10-06", is_day_off: false, label: "الصبح", work_mode: null, reason: "" },
    ],
    preview: [
      { date: "2026-10-03", working: true, label: "الصبح", start: stampOf("9:00 AM", "9:00 AM"), end: stampOf("5:00 PM", "5:00 PM"), mode: { value: "office", ar: "من المكتب", en: "Office" }, source: "roster" },
      { date: "2026-10-04", working: false, label: "", start: null, end: null, mode: null, source: "roster" },
    ],
    templates: [
      { id: 3, label: "الصبح", is_active: true, start: stampOf("9:00 AM", "9:00 AM"), end: stampOf("5:00 PM", "5:00 PM") },
      { id: 4, label: "القديم", is_active: false, start: stampOf("1:00 PM", "1:00 PM"), end: stampOf("9:00 PM", "9:00 PM") },
    ],
    shift_form: [
      field("weekday", "Weekday", { kind: "select", value: "", label_ar: "اليوم", label_en: "Weekday", choices: WEEKDAYS }),
      field("template", "Shift template", { kind: "select", value: "", label_ar: "شيفت جاهز", label_en: "Shift template", choices: [{ value: "", label: "— جدول مخصص —" }, { value: "3", label: "الصبح" }] }),
      field("start_time", "From", { kind: "time", label_ar: "من", label_en: "From" }),
      field("end_time", "To", { kind: "time", label_ar: "إلى", label_en: "To" }),
    ],
    override_form: [
      field("date", "Date", { kind: "date", label_ar: "تاريخ الاستثناء", label_en: "Override date" }),
      field("is_day_off", "Day off", { kind: "checkbox", value: false, label_ar: "أجازة", label_en: "Day off" }),
      field("reason", "Reason", { label_ar: "السبب", label_en: "Reason" }),
    ],
    template_form: [
      field("name_ar", "Name", { label_ar: "اسم الشيفت", label_en: "Shift name", hint_ar: "اختياري", hint_en: "Optional" }),
      field("start_time", "From", { kind: "time", label_ar: "بداية الشيفت", label_en: "Shift start" }),
      field("end_time", "To", { kind: "time", label_ar: "نهاية الشيفت", label_en: "Shift end" }),
    ],
    ...over,
  };
}

const page = (data: HrSchedules = schedules()) => ({ "/api/v1/hr/schedules/": () => jsonResponse(data) });

describe("HrSchedulesPage", () => {
  it("draws the roster with its hours, a night shift, a mode, and a row that is switched off", async () => {
    serve("hr", page());
    const { container } = open("/hr/schedules");
    await screen.findByText("الجدول الأسبوعي");
    const first = container.querySelector('[data-roster="1"]') as HTMLElement;
    expect(within(first).getByText("الاتنين")).toBeInTheDocument();
    expect(within(first).getByText("9:00 AM – 5:00 PM")).toBeInTheDocument();
    expect(within(first).getByText("8:00")).toBeInTheDocument();
    const night = container.querySelector('[data-roster="2"]') as HTMLElement;
    expect(within(night).getByText("لليوم التالي")).toBeInTheDocument();
    expect(within(night).getByText("عن بُعد")).toBeInTheDocument();
    expect(within(night).getByText("موقوف - مش بيتحسب")).toHaveClass("badge--dead");
    expect(within(first).queryByText("موقوف - مش بيتحسب")).toBeNull();
  });

  it("names the person's kind of work, the one-off days, and the next fortnight as the rules resolve it", async () => {
    serve("hr", page());
    const { container } = open("/hr/schedules");
    await screen.findByText("الجدول الأسبوعي");
    const person = container.querySelector('[data-card="person"]') as HTMLElement;
    expect(person).toHaveTextContent("دوام كامل");
    expect(person).toHaveTextContent("من المكتب");
    expect(person).toHaveTextContent("Fixed");
    expect(within(container.querySelector('[data-override="7"]') as HTMLElement).getByText("أجازة")).toHaveClass("badge--info");
    expect(within(container.querySelector('[data-override="7"]') as HTMLElement).getByText("Wedding")).toBeInTheDocument();
    expect(within(container.querySelector('[data-override="8"]') as HTMLElement).getByText("الصبح")).toHaveClass("mono");
    const working = container.querySelector('[data-plan="2026-10-03"]') as HTMLElement;
    expect(within(working).getByText("9:00 AM – 5:00 PM")).toBeInTheDocument();
    const off = container.querySelector('[data-plan="2026-10-04"]') as HTMLElement;
    expect(within(off).getByText("أجازة")).toHaveClass("muted");
    expect(off).toHaveTextContent("—");
  });

  it("lists the company shifts and marks the closed one", async () => {
    serve("hr", page());
    const { container } = open("/hr/schedules");
    await screen.findByText("الجدول الأسبوعي");
    expect(within(container.querySelector('[data-template="3"]') as HTMLElement).getByText("9:00 AM–5:00 PM")).toBeInTheDocument();
    expect(within(container.querySelector('[data-template="4"]') as HTMLElement).getByText("مقفول")).toBeInTheDocument();
  });

  it("says there is no roster and no override yet", async () => {
    serve("hr", page(schedules({ shifts: [], overrides: [] })));
    open("/hr/schedules");
    expect(await screen.findByText("مفيش جدول للموظف ده لسه.")).toBeInTheDocument();
    expect(screen.getByText("مفيش تعديلات.")).toBeInTheDocument();
  });

  it("changes the person through the address and asks the door for that one", async () => {
    const served = serve("hr", page());
    const user = userEvent.setup();
    open("/hr/schedules");
    await screen.findByText("الجدول الأسبوعي");
    await user.selectOptions(screen.getByLabelText("الموظف"), "12");
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/hr/schedules?user=12"));
    await waitFor(() => expect(reads(served, "/api/v1/hr/schedules/")).toContain("/api/v1/hr/schedules/?user=12"));
  });

  it("adds a roster day with the form's boxes, sending what changed and the person", async () => {
    const served = serve("hr", {
      ...page(),
      "/api/v1/hr/schedules/shift/": (url, init) => served.record(url, init, { ok: true, id: 9 }),
    });
    const user = userEvent.setup();
    open("/hr/schedules");
    await screen.findByText("الجدول الأسبوعي");
    const box = (screen.getByText("ضيف يوم للجدول").closest(".card") as HTMLElement);
    const save = within(box).getByRole("button", { name: "احفظ" });
    expect(save).toBeDisabled();
    expect(within(within(box).getByLabelText("اليوم")).getByRole("option", { name: "الأربع" })).toBeInTheDocument();
    await user.selectOptions(within(box).getByLabelText("اليوم"), "0");
    await user.selectOptions(within(box).getByLabelText("شيفت جاهز"), "3");
    await user.click(save);
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/schedules/shift/")).toBe(true));
    expect(served.sent.find((post) => post.url === "/api/v1/hr/schedules/shift/")!.body).toEqual({ user: 11, values: { weekday: "0", template: "3" } });
    expect(await screen.findByText("اتسجل")).toBeInTheDocument();
  });

  it("shows the form's refusal for a roster day with neither a shift nor times", async () => {
    serve("hr", {
      ...page(),
      "/api/v1/hr/schedules/shift/": () => jsonResponse({ ok: false, error: "invalid", errors: { __all__: ["اختار شيفت جاهز، أو اكتب وقت البداية والنهاية."] } }, 400),
    });
    const user = userEvent.setup();
    open("/hr/schedules");
    await screen.findByText("الجدول الأسبوعي");
    const box = screen.getByText("ضيف يوم للجدول").closest(".card") as HTMLElement;
    await user.selectOptions(within(box).getByLabelText("اليوم"), "0");
    await user.click(within(box).getByRole("button", { name: "احفظ" }));
    expect(await screen.findByText("اختار شيفت جاهز، أو اكتب وقت البداية والنهاية.")).toBeInTheDocument();
    expect(within(box).getByLabelText("اليوم")).toHaveValue("0");
  });

  it("moves one date: a day off, with its reason", async () => {
    const served = serve("hr", {
      ...page(),
      "/api/v1/hr/schedules/override/": (url, init) => served.record(url, init, { ok: true, id: 5 }),
    });
    const user = userEvent.setup();
    open("/hr/schedules");
    await screen.findByText("الجدول الأسبوعي");
    const box = screen.getByText("عدّل يوم واحد").closest(".card") as HTMLElement;
    fireDate(within(box).getByLabelText("تاريخ الاستثناء"), "2026-10-09");
    await user.click(within(box).getByLabelText("أجازة"));
    await user.type(within(box).getByLabelText("السبب"), "Wedding");
    await user.click(within(box).getByRole("button", { name: "احفظ" }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/schedules/override/")).toBe(true));
    expect(served.sent.find((post) => post.url === "/api/v1/hr/schedules/override/")!.body).toEqual({
      user: 11,
      values: { date: "2026-10-09", is_day_off: true, reason: "Wedding" },
    });
  });

  it("adds a company shift from its four boxes", async () => {
    const served = serve("hr", {
      ...page(),
      "/api/v1/hr/schedules/template/": (url, init) => served.record(url, init, { ok: true, id: 6 }),
    });
    const user = userEvent.setup();
    open("/hr/schedules");
    await screen.findByText("الجدول الأسبوعي");
    await user.type(screen.getByLabelText("اسم الشيفت"), "ليلي");
    fireDate(screen.getByLabelText("بداية الشيفت"), "22:00");
    fireDate(screen.getByLabelText("نهاية الشيفت"), "06:00");
    await user.click(screen.getByRole("button", { name: "ضيف شيفت" }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/schedules/template/")).toBe(true));
    expect(served.sent.find((post) => post.url === "/api/v1/hr/schedules/template/")!.body).toEqual({
      values: { name_ar: "ليلي", start_time: "22:00", end_time: "06:00" },
    });
  });

  it("deletes a roster day and a one-off day", async () => {
    const served = serve("hr", {
      ...page(),
      "/api/v1/hr/schedules/shift/1/delete/": (url, init) => served.record(url, init, { ok: true, user: 11 }),
      "/api/v1/hr/schedules/override/7/delete/": (url, init) => served.record(url, init, { ok: true, user: 11 }),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/schedules");
    await screen.findByText("الجدول الأسبوعي");
    await user.click(within(container.querySelector('[data-roster="1"]') as HTMLElement).getByRole("button", { name: "احذف" }));
    await user.click(within(container.querySelector('[data-override="7"]') as HTMLElement).getByRole("button", { name: "احذف" }));
    await waitFor(() => expect(served.sent.map((post) => post.url)).toEqual(["/api/v1/hr/schedules/shift/1/delete/", "/api/v1/hr/schedules/override/7/delete/"]));
  });

  it("says why a delete did not go", async () => {
    serve("hr", {
      ...page(),
      "/api/v1/hr/schedules/shift/1/delete/": () => jsonResponse({ ok: false, error: "not_found" }, 404),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/schedules");
    await screen.findByText("الجدول الأسبوعي");
    await user.click(within(container.querySelector('[data-roster="1"]') as HTMLElement).getByRole("button", { name: "احذف" }));
    expect(await screen.findByText("حصلت مشكلة.")).toBeInTheDocument();
  });

  it("is HR's and the admin's", async () => {
    const served = serve("sales", page());
    open("/hr/schedules");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/"))).toBe(false);
  });
});

/** A date or time box takes its whole value at once (typing it a key at a time is not how a browser fills one). */
function fireDate(input: HTMLElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  setter.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

function shifts(over: Partial<HrShifts> = {}): HrShifts {
  return {
    ok: true,
    rows: [
      { id: 3, label: "الصبح", name: "Morning", name_ar: "الصبح", is_active: true, start: stampOf("9:00 AM", "9:00 AM"), end: stampOf("5:00 PM", "5:00 PM"), crosses_midnight: false, hours: "8", people: 2, overrides: 1, vacancies: 1, in_use: true },
      { id: 4, label: "ليلي", name: "Night", name_ar: "ليلي", is_active: false, start: stampOf("10:00 PM", "10:00 PM"), end: stampOf("6:00 AM", "6:00 AM"), crosses_midnight: true, hours: "8", people: 0, overrides: 0, vacancies: 0, in_use: false },
    ],
    editing: null,
    form: [
      field("name_ar", "Name", { label_ar: "الاسم", label_en: "Name", hint_ar: "اختياري — لو سيبته فاضي بيتسمّى بمواعيده.", hint_en: "Optional" }),
      field("start_time", "From", { kind: "time", label_ar: "من", label_en: "From" }),
      field("end_time", "To", { kind: "time", label_ar: "إلى", label_en: "To" }),
      field("is_active", "Active", { kind: "checkbox", value: true, label_ar: "شغال", label_en: "Active" }),
    ],
    ...over,
  };
}

const shiftsPage = (data: HrShifts = shifts()) => ({ "/api/v1/hr/shifts/": () => jsonResponse(data) });

describe("HrShiftsPage", () => {
  it("says who leans on each shift, and offers a delete only where nobody does", async () => {
    serve("hr", shiftsPage());
    const { container } = open("/hr/shifts");
    await screen.findByText("شيفتات الشركة");
    const used = container.querySelector('[data-shift="3"]') as HTMLElement;
    expect(used).toHaveTextContent("2 موظف");
    expect(used).toHaveTextContent("1 تعديل يوم");
    expect(used).toHaveTextContent("1 وظيفة");
    expect(within(used).queryByRole("button", { name: "احذف" })).toBeNull();
    expect(within(used).getByRole("link", { name: /عدّل/ })).toHaveAttribute("href", "/hr/shifts?edit=3");
    const free = container.querySelector('[data-shift="4"]') as HTMLElement;
    expect(within(free).getByText("مقفول")).toBeInTheDocument();
    expect(within(free).getByText("بيعدّي نص الليل")).toBeInTheDocument();
    expect(within(free).getByRole("button", { name: "احذف" })).toBeInTheDocument();
  });

  it("adds a shift: no id is sent", async () => {
    const served = serve("hr", {
      ...shiftsPage(),
      "/api/v1/hr/shifts/save/": (url, init) => served.record(url, init, { ok: true, id: 9 }),
    });
    const user = userEvent.setup();
    open("/hr/shifts");
    await screen.findByText("شيفت جديد", { selector: "h3" });
    const save = screen.getByRole("button", { name: "احفظ" });
    expect(save).toBeDisabled();
    await user.type(screen.getByLabelText("الاسم"), "المساء");
    fireDate(screen.getByLabelText("من"), "16:00");
    fireDate(screen.getByLabelText("إلى"), "00:00");
    await user.click(save);
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/shifts/save/")).toBe(true));
    expect(served.sent.find((post) => post.url === "/api/v1/hr/shifts/save/")!.body).toEqual({ values: { name_ar: "المساء", start_time: "16:00", end_time: "00:00" } });
  });

  it("changes a shift: its id goes with only the boxes that changed", async () => {
    const served = serve("hr", {
      "/api/v1/hr/shifts/": (url) =>
        jsonResponse(
          url.searchParams.get("edit") === "3"
            ? shifts({ editing: 3, form: shifts().form.map((one) => (one.name === "name_ar" ? { ...one, value: "الصبح" } : one.name === "end_time" ? { ...one, value: "17:00" } : one)) })
            : shifts(),
        ),
      "/api/v1/hr/shifts/save/": (url, init) => served.record(url, init, { ok: true, id: 3 }),
    });
    const user = userEvent.setup();
    open("/hr/shifts?edit=3");
    await screen.findByText("تعديل شيفت");
    expect(screen.getByLabelText("الاسم")).toHaveValue("الصبح");
    fireDate(screen.getByLabelText("إلى"), "18:00");
    await user.click(screen.getByRole("button", { name: "احفظ" }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/shifts/save/")).toBe(true));
    expect(served.sent.find((post) => post.url === "/api/v1/hr/shifts/save/")!.body).toEqual({ id: 3, values: { end_time: "18:00" } });
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(/^\/hr\/shifts$/));
  });

  it("goes back to a blank form for a new shift", async () => {
    serve("hr", {
      "/api/v1/hr/shifts/": (url) =>
        jsonResponse(url.searchParams.get("edit") === "3" ? shifts({ editing: 3 }) : shifts()),
    });
    const user = userEvent.setup();
    open("/hr/shifts?edit=3");
    await screen.findByText("تعديل شيفت");
    await user.click(screen.getByRole("link", { name: /شيفت جديد/ }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "شيفت جديد" })).toBeInTheDocument());
  });

  it("shows the form's refusal beside its box", async () => {
    serve("hr", {
      ...shiftsPage(),
      "/api/v1/hr/shifts/save/": () => jsonResponse({ ok: false, error: "invalid", errors: { __all__: ["بداية الشيفت ونهايته نفس الوقت."] } }, 400),
    });
    const user = userEvent.setup();
    open("/hr/shifts");
    await screen.findByText("شيفتات الشركة");
    fireDate(screen.getByLabelText("من"), "09:00");
    fireDate(screen.getByLabelText("إلى"), "09:00");
    await user.click(screen.getByRole("button", { name: "احفظ" }));
    expect(await screen.findByText("بداية الشيفت ونهايته نفس الوقت.")).toBeInTheDocument();
  });

  it("deletes a shift nobody is on", async () => {
    const served = serve("hr", {
      ...shiftsPage(),
      "/api/v1/hr/shifts/4/delete/": (url, init) => served.record(url, init, { ok: true }),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/shifts");
    await screen.findByText("شيفتات الشركة");
    await user.click(within(container.querySelector('[data-shift="4"]') as HTMLElement).getByRole("button", { name: "احذف" }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/shifts/4/delete/")).toBe(true));
  });

  it("says in the server's words why a shift was kept", async () => {
    serve("hr", {
      ...shiftsPage(),
      "/api/v1/hr/shifts/4/delete/": () => jsonResponse({ ok: false, error: "in_use", message: "الشيفت ده عليه موظفين - اقفله من التعديل." }, 409),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/shifts");
    await screen.findByText("شيفتات الشركة");
    await user.click(within(container.querySelector('[data-shift="4"]') as HTMLElement).getByRole("button", { name: "احذف" }));
    expect(await screen.findByText("الشيفت ده عليه موظفين - اقفله من التعديل.")).toBeInTheDocument();
  });

  it("is HR's and the admin's", async () => {
    const served = serve("translator", shiftsPage());
    open("/hr/shifts");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/"))).toBe(false);
  });
});

function offices(over: Partial<HrOffices> = {}): HrOffices {
  return {
    ok: true,
    offices: [
      { id: 2, label: "المقر", latitude: "30.044400", longitude: "31.235700", radius_meters: 200, is_active: true },
      { id: 3, label: "القديم", latitude: "29.000000", longitude: "30.000000", radius_meters: 50, is_active: false },
    ],
    editing: null,
    form: [
      field("name", "Name", { label_ar: "الاسم", label_en: "Name", ltr: true }),
      field("latitude", "Latitude", { kind: "number", step: "0.000001", label_ar: "Latitude", label_en: "Latitude" }),
      field("longitude", "Longitude", { kind: "number", step: "0.000001", label_ar: "Longitude", label_en: "Longitude" }),
      field("radius_meters", "Radius", { kind: "number", value: 200, label_ar: "النطاق بالمتر", label_en: "Radius (metres)" }),
    ],
    policy: "flag",
    ...over,
  };
}

const officesPage = (data: HrOffices = offices()) => ({ "/api/v1/hr/offices/": () => jsonResponse(data) });

function geo(answer: "fix" | "denied") {
  const getCurrentPosition = vi.fn((ok: (position: unknown) => void, no: () => void) =>
    answer === "fix" ? ok({ coords: { latitude: 30.0444, longitude: 31.2357, accuracy: 12 } }) : no(),
  );
  vi.stubGlobal("navigator", { ...navigator, geolocation: { getCurrentPosition, watchPosition: vi.fn() } });
  return getCurrentPosition;
}

describe("HrOfficesPage", () => {
  it("lists the offices with a link to the map that does not hand the page to it", async () => {
    serve("hr", officesPage());
    const { container } = open("/hr/offices");
    await screen.findByText("المواقع");
    const first = container.querySelector('[data-office="2"]') as HTMLElement;
    expect(first).toHaveTextContent("30.044400, 31.235700");
    const link = within(first).getByRole("link", { name: "على الخريطة" });
    expect(link).toHaveAttribute("href", "https://www.google.com/maps?q=30.044400%2C31.235700");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveAttribute("target", "_blank");
    expect(within(first).getByText("شغال")).toHaveClass("badge--ok");
    expect(within(container.querySelector('[data-office="3"]') as HTMLElement).getByText("مقفول")).toBeInTheDocument();
  });

  it("says no office means no location check, and states the policy", async () => {
    serve("hr", officesPage(offices({ offices: [], policy: "reject" })));
    const { container } = open("/hr/offices");
    expect(await screen.findByText("مفيش مواقع — يعني مفيش فحص موقع على أي حضور.")).toBeInTheDocument();
    expect(container.querySelector('[data-note="policy"]')).toHaveTextContent("رفض الحضور من بره النطاق");
  });

  it("adds an office with the boxes that were filled", async () => {
    const served = serve("hr", {
      ...officesPage(),
      "/api/v1/hr/offices/save/": (url, init) => served.record(url, init, { ok: true, id: 4 }),
    });
    const user = userEvent.setup();
    open("/hr/offices");
    await screen.findByText("المواقع");
    await user.type(screen.getByLabelText("الاسم"), "HQ");
    await user.type(screen.getByLabelText("Latitude"), "30.04");
    await user.type(screen.getByLabelText("Longitude"), "31.23");
    await user.click(screen.getByRole("button", { name: "احفظ" }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/offices/save/")).toBe(true));
    expect(served.sent.find((post) => post.url === "/api/v1/hr/offices/save/")!.body).toEqual({ values: { name: "HQ", latitude: "30.04", longitude: "31.23" } });
  });

  it("shows the form's refusal for a radius that is too small", async () => {
    serve("hr", {
      ...officesPage(),
      "/api/v1/hr/offices/save/": () => jsonResponse({ ok: false, error: "invalid", errors: { radius_meters: ["أقل من 20 متر هيرفض حضور سليم."] } }, 400),
    });
    const user = userEvent.setup();
    open("/hr/offices");
    await screen.findByText("المواقع");
    await user.clear(screen.getByLabelText("النطاق بالمتر"));
    await user.type(screen.getByLabelText("النطاق بالمتر"), "10");
    await user.click(screen.getByRole("button", { name: "احفظ" }));
    expect(await screen.findByText("أقل من 20 متر هيرفض حضور سليم.")).toBeInTheDocument();
    expect(screen.getByLabelText("النطاق بالمتر")).toHaveValue(10);
  });

  it("fills the coordinates from this device once, only when the button is pressed", async () => {
    const reading = geo("fix");
    const user = userEvent.setup();
    serve("hr", officesPage());
    open("/hr/offices");
    await screen.findByText("المواقع");
    expect(reading).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /استخدم موقعي الحالي/ }));
    await waitFor(() => expect(screen.getByLabelText("Latitude")).toHaveValue(30.0444));
    expect(screen.getByLabelText("Longitude")).toHaveValue(31.2357);
    expect(reading).toHaveBeenCalledTimes(1);
  });

  it("says so when the position cannot be read and leaves the boxes alone", async () => {
    geo("denied");
    const user = userEvent.setup();
    serve("hr", officesPage());
    open("/hr/offices");
    await screen.findByText("المواقع");
    await user.click(screen.getByRole("button", { name: /استخدم موقعي الحالي/ }));
    expect(await screen.findByText(/مقدرتش أقرا الموقع/)).toBeInTheDocument();
    expect(screen.getByLabelText("Latitude")).toHaveValue(null);
  });

  it("deletes an office", async () => {
    const served = serve("hr", {
      ...officesPage(),
      "/api/v1/hr/offices/3/delete/": (url, init) => served.record(url, init, { ok: true, deleted: 1 }),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/offices");
    await screen.findByText("المواقع");
    await user.click(within(container.querySelector('[data-office="3"]') as HTMLElement).getByRole("button", { name: "احذف" }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/offices/3/delete/")).toBe(true));
  });

  it("changes an office by id with only what changed", async () => {
    const served = serve("hr", {
      "/api/v1/hr/offices/": (url) =>
        jsonResponse(url.searchParams.get("edit") === "2" ? offices({ editing: 2, form: offices().form.map((one) => (one.name === "name" ? { ...one, value: "المقر" } : one)) }) : offices()),
      "/api/v1/hr/offices/save/": (url, init) => served.record(url, init, { ok: true, id: 2 }),
    });
    const user = userEvent.setup();
    open("/hr/offices?edit=2");
    await screen.findByText("تعديل مكتب");
    await user.clear(screen.getByLabelText("النطاق بالمتر"));
    await user.type(screen.getByLabelText("النطاق بالمتر"), "80");
    await user.click(screen.getByRole("button", { name: "احفظ" }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/offices/save/")).toBe(true));
    expect(served.sent.find((post) => post.url === "/api/v1/hr/offices/save/")!.body).toEqual({ id: 2, values: { radius_meters: "80" } });
  });

  it("is HR's and the admin's", async () => {
    const served = serve("operation", officesPage());
    open("/hr/offices");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/"))).toBe(false);
  });
});

function device(id: number, over: Partial<HrDevice> = {}): HrDevice {
  return {
    id,
    user: "Sam",
    name: "f3a9c1d27b8e",
    fingerprint: "f3a9c1d27b8e",
    browser: "Mozilla/5.0 (Windows NT 10.0)",
    status: "pending",
    decided_by: null,
    first_seen: stampOf("2026-10-02 9:05 AM", "2026-10-02 9:05 AM"),
    last_seen: stampOf("2026-10-03 8:00 AM", "2026-10-03 8:00 AM"),
    ...over,
  };
}

function devices(over: Partial<HrDevices> = {}): HrDevices {
  return {
    ok: true,
    pending: [device(1)],
    decided: [device(2, { status: "approved", decided_by: "Mona", name: "Sam's phone" }), device(3, { status: "rejected", decided_by: "Mona", user: "Nada" })],
    ...over,
  };
}

describe("HrDevicesPage", () => {
  it("lists what waits and what was decided, each browser by the start of its token", async () => {
    serve("hr", { "/api/v1/hr/devices/": () => jsonResponse(devices()) });
    const { container } = open("/hr/devices");
    await screen.findByText("مستنية موافقة");
    const waiting = container.querySelector('[data-table="pending"]') as HTMLElement;
    expect(within(waiting).getByText("f3a9c1d27b8e")).toHaveClass("mono");
    expect(within(waiting).getByText("Mozilla/5.0 (Windows NT 10.0)")).toBeInTheDocument();
    const decided = container.querySelector('[data-table="decided"]') as HTMLElement;
    expect(within(decided.querySelector('[data-device="2"]') as HTMLElement).getByText("معتمد")).toHaveClass("badge--ok");
    expect(within(decided.querySelector('[data-device="2"]') as HTMLElement).getByText("Sam's phone")).toBeInTheDocument();
    expect(within(decided.querySelector('[data-device="3"]') as HTMLElement).getByText("مرفوض")).toHaveClass("badge--dead");
    expect(within(decided).getAllByText("Mona")).toHaveLength(2);
  });

  it("approves and rejects", async () => {
    const served = serve("hr", {
      "/api/v1/hr/devices/": () => jsonResponse(devices({ pending: [device(1), device(4, { user: "Omar" })] })),
      "/api/v1/hr/devices/1/approve/": (url, init) => served.record(url, init, { ok: true }),
      "/api/v1/hr/devices/4/reject/": (url, init) => served.record(url, init, { ok: true }),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/devices");
    await screen.findByText("مستنية موافقة");
    await user.click(within(container.querySelector('[data-table="pending"] [data-device="1"]') as HTMLElement).getByRole("button", { name: "اعتمد" }));
    await user.click(within(container.querySelector('[data-table="pending"] [data-device="4"]') as HTMLElement).getByRole("button", { name: "ارفض" }));
    await waitFor(() => expect(served.sent.map((post) => post.url)).toEqual(["/api/v1/hr/devices/1/approve/", "/api/v1/hr/devices/4/reject/"]));
  });

  it("says nothing is waiting, and nothing is decided", async () => {
    serve("hr", { "/api/v1/hr/devices/": () => jsonResponse(devices({ pending: [], decided: [] })) });
    open("/hr/devices");
    expect(await screen.findByText("مفيش أجهزة مستنية.")).toBeInTheDocument();
    expect(screen.getByText("لسه مفيش.")).toBeInTheDocument();
  });

  it("is HR's and the admin's", async () => {
    const served = serve("accounting", { "/api/v1/hr/devices/": () => jsonResponse(devices()) });
    open("/hr/devices");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/"))).toBe(false);
  });
});

function overtime(over: Partial<HrOvertime> = {}): HrOvertime {
  return {
    ok: true,
    pending: [{ id: 1, user: "Sam", date: "2026-10-02", hours: "1:30", hourly_rate: "12.50", amount: "18.75", status: "pending", decided_by: null }],
    decided: [
      { id: 2, user: "Nada", date: "2026-10-01", hours: "0:30", hourly_rate: "10.00", amount: "5.00", status: "approved", decided_by: "Mona" },
      { id: 3, user: "Omar", date: "2026-09-30", hours: "2:00", hourly_rate: "10.00", amount: "20.00", status: "rejected", decided_by: "Mona" },
    ],
    ...over,
  };
}

describe("HrOvertimePage", () => {
  it("lists the claims with money as it was written", async () => {
    serve("hr", { "/api/v1/hr/overtime/": () => jsonResponse(overtime()) });
    const { container } = open("/hr/overtime");
    await screen.findByText("مستنية اعتماد");
    const waiting = container.querySelector('[data-table="pending"] [data-claim="1"]') as HTMLElement;
    expect(within(waiting).getByText("1:30")).toBeInTheDocument();
    expect(within(waiting).getByText("12.50")).toHaveClass("mono");
    expect(within(waiting).getByText("18.75")).toBeInTheDocument();
    const decided = container.querySelector('[data-table="decided"]') as HTMLElement;
    expect(within(decided.querySelector('[data-claim="2"]') as HTMLElement).getByText("معتمد")).toHaveClass("badge--ok");
    expect(within(decided.querySelector('[data-claim="3"]') as HTMLElement).getByText("مرفوض")).toHaveClass("badge--dead");
  });

  it("approves and rejects", async () => {
    const served = serve("hr", {
      "/api/v1/hr/overtime/": () => jsonResponse(overtime()),
      "/api/v1/hr/overtime/1/approve/": (url, init) => served.record(url, init, { ok: true }),
      "/api/v1/hr/overtime/1/reject/": (url, init) => served.record(url, init, { ok: true }),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/overtime");
    await screen.findByText("مستنية اعتماد");
    const row = container.querySelector('[data-table="pending"] [data-claim="1"]') as HTMLElement;
    await user.click(within(row).getByRole("button", { name: "اعتمد" }));
    await user.click(within(row).getByRole("button", { name: "ارفض" }));
    await waitFor(() => expect(served.sent.map((post) => post.url)).toEqual(["/api/v1/hr/overtime/1/approve/", "/api/v1/hr/overtime/1/reject/"]));
  });

  it("says why a claim could not be decided", async () => {
    serve("hr", {
      "/api/v1/hr/overtime/": () => jsonResponse(overtime()),
      "/api/v1/hr/overtime/1/approve/": () => jsonResponse({ ok: false, error: "already_decided", message: "اتقرر في الطلب ده قبل كده." }, 409),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/overtime");
    await screen.findByText("مستنية اعتماد");
    await user.click(within(container.querySelector('[data-table="pending"] [data-claim="1"]') as HTMLElement).getByRole("button", { name: "اعتمد" }));
    expect(await screen.findByText("اتقرر في الطلب ده قبل كده.")).toBeInTheDocument();
  });

  it("says nothing is waiting", async () => {
    serve("hr", { "/api/v1/hr/overtime/": () => jsonResponse(overtime({ pending: [], decided: [] })) });
    open("/hr/overtime");
    expect(await screen.findByText("مفيش أوفرتايم مستني.")).toBeInTheDocument();
  });

  it("is HR's and the admin's", async () => {
    const served = serve("reviewer", { "/api/v1/hr/overtime/": () => jsonResponse(overtime()) });
    open("/hr/overtime");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/"))).toBe(false);
  });
});
