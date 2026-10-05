import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AdminUser, AdminUserNew, DayStatusJson, FormField, HrEmployee, HrRegister, Role } from "../api/types";
import { jsonResponse } from "../test/helpers";
import { field, openHr as open, reads, serveHr, stampOf, type Handler } from "../test/hr";

/**
 * The employee files, with what only the admin does on them: the register's staff columns, the account form, the roster rows
 * typed by hand, the rating penalties and a new person. (HR's own half of the same pages is `HrPeople.test.tsx`.)
 */

afterEach(() => vi.unstubAllGlobals());

const confirmed: DayStatusJson = { value: "active", tone: "ok", ar: "مثبّت", en: "Confirmed" };
const translator = { value: "translator", ar: "مترجم", en: "Translator" };
const operation = { value: "operation", ar: "أوبريشن", en: "Operation" };
const fullTime = { value: "full_time", ar: "دوام كامل", en: "Full time" };

function fileForm(): FormField[] {
  return [
    field("first_name", "First name", { value: "Sam" }),
    field("email", "Email address", { kind: "email", ltr: true, value: "sam@example.com", help: "Where we write to them." }),
    field("role", "Role", {
      kind: "select",
      value: "translator",
      choices: [
        { value: "operation", label: "Operation" },
        { value: "translator", label: "Translator" },
      ],
    }),
    field("is_active", "Active", { kind: "checkbox", value: true }),
    field("rating", "Rating", { kind: "number", value: "5.000", step: "0.125" }),
  ];
}

function adminHalf(over: Partial<AdminUser> = {}): AdminUser {
  return {
    ok: true,
    user: { id: 5, username: "sam", name: "Sam Adel", initials: "SA", role: translator },
    form: fileForm(),
    events: [{ delta: "-0.125", reason: "اتأخر", at: stampOf("10-01 م", "10-01 PM") }],
    ...over,
  };
}

function hrHalf(over: Partial<HrEmployee> = {}): HrEmployee {
  return {
    ok: true,
    person: {
      id: 5,
      name: "Sam Adel",
      exempt: false,
      initials: "SA",
      role: translator,
      status: confirmed,
      code: "EMP-0005",
      job_title: "Translator",
      department: "اللغويات",
      manager: "Mona",
      languages: "AR/EN",
      joining_date: "2025-01-05",
      employment: fullTime,
      work_mode: null,
      probation_start: null,
      probation_end: null,
      phone: "01000000000",
      attendance_enabled: true,
    },
    summary: null,
    shifts: [
      { id: 31, weekday: { value: 0, ar: "الاتنين", en: "Monday" }, template: null, start: stampOf("9:00 AM", "9:00 AM"), end: stampOf("5:00 PM", "5:00 PM"), crosses_midnight: false, minutes: 480, work_mode: null, is_active: true },
    ],
    picker: {
      current: 3,
      has_custom: false,
      templates: [{ id: 3, label: "الشيفت 1", start: stampOf("9:00 AM", "9:00 AM"), end: stampOf("5:00 PM", "5:00 PM") }],
      days: [
        { num: 5, ar: "السبت", en: "Saturday", checked: true },
        { num: 0, ar: "الاتنين", en: "Monday", checked: false },
      ],
    },
    work_mode_card: null,
    probation: [],
    leave: [],
    plan: { current: null, options: [] },
    application: null,
    salary: [],
    can: { edit: true, shift: true, plan: true },
    ...over,
  };
}

function register(): HrRegister {
  return {
    ok: true,
    rows: [
      { id: 5, code: "EMP-0005", name: "Sam Adel", initials: "SA", role: translator, department: "اللغويات", team_lead: "Mona", employment: fullTime, joining_date: "2025-01-05", status: confirmed, state: "busy", seen: stampOf("5:30 PM", "5:30 PM"), shifts: 3, rating: 4.5, username: "sam", mail_alias: "" },
      { id: 6, code: "", name: "Nour Ops", initials: "NO", role: operation, department: null, team_lead: null, employment: fullTime, joining_date: null, status: confirmed, state: "free", seen: stampOf("5:31 PM", "5:31 PM"), shifts: 0, rating: 5, username: "nour", mail_alias: "ops1@example.com" },
      { id: 7, code: "", name: "Old Timer", initials: "OT", role: { value: "hr", ar: "موارد بشرية", en: "HR" }, department: null, team_lead: null, employment: fullTime, joining_date: null, status: confirmed, state: "disabled", seen: stampOf("من يومين", "2 d ago"), shifts: 1, rating: 3.25, username: "old", mail_alias: "" },
    ],
    options: { departments: [], statuses: [confirmed] },
  };
}

function newForm(): FormField[] {
  return [
    field("username", "Username", { ltr: true, required: true }),
    field("password1", "Password", { kind: "password", required: true, ltr: true, saved: false }),
    field("password2", "Password confirmation", { kind: "password", required: true, ltr: true, saved: false }),
    field("role", "Role", { kind: "select", choices: [{ value: "operation", label: "Operation" }, { value: "translator", label: "Translator" }], value: "operation" }),
  ];
}

/** The admin's side of the fake server: both halves of person 5 and every write the admin makes on the file. */
function serve(who: Role, over: Record<string, Handler> = {}) {
  const served: ReturnType<typeof serveHr> = serveHr(who, {
    "/api/v1/hr/employees/5/": () => jsonResponse(hrHalf({ can: { edit: who === "admin", shift: true, plan: who === "admin" } })),
    "/api/v1/hr/employees/": () => jsonResponse(register()),
    "/api/v1/admin/aliases/sync/": (url, init) => served.record(url, init, { ok: true, ran: false }),
    "/api/v1/admin/users/new/": () => jsonResponse({ ok: true, form: newForm() } satisfies AdminUserNew),
    "/api/v1/admin/users/create/": (url, init) => served.record(url, init, { ok: true, id: 41 }),
    "/api/v1/admin/users/5/save/": (url, init) => served.record(url, init, { ok: true }),
    "/api/v1/admin/users/5/shifts/add/": (url, init) => served.record(url, init, { ok: true, id: 90 }),
    "/api/v1/admin/users/5/shifts/31/delete/": (url, init) => served.record(url, init, { ok: true, deleted: 1 }),
    "/api/v1/admin/users/5/": () => jsonResponse(adminHalf()),
    ...over,
  });
  return served;
}

const edit = () => userEvent.click(screen.getByRole("button", { name: /عدّل$/ }));

describe("the register as the staff list", () => {
  it("lists everybody with their role, leader, mail address, shifts and a link to the file from the name", async () => {
    serve("admin");
    const { container } = open("/hr/employees");
    await screen.findByText("Sam Adel");
    const sam = container.querySelector('[data-person="5"]') as HTMLElement;
    expect(within(sam).getByRole("link", { name: "Sam Adel" })).toHaveAttribute("href", "/hr/employees/5");
    expect(within(sam).getByText("EMP-0005 · sam")).toHaveClass("mono");
    expect(within(sam).getByText("مترجم")).toHaveClass("chip");
    expect(within(sam).getByText("Mona")).toBeInTheDocument();
    expect(within(sam).getByText("3")).toHaveClass("mono");
    const nour = container.querySelector('[data-person="6"]') as HTMLElement;
    expect(within(nour).getByText("ops1@example.com")).toBeInTheDocument();
    expect(within(nour).getByText("nour")).toBeInTheDocument();
    expect(within(nour).getAllByText("—").length).toBeGreaterThan(0);
  });

  it("opens a person who has no code from the name", async () => {
    serve("admin");
    const { container } = open("/hr/employees");
    await screen.findByText("Nour Ops");
    expect(within(container.querySelector('[data-person="6"]') as HTMLElement).getByRole("link", { name: "Nour Ops" })).toHaveAttribute("href", "/hr/employees/6");
  });

  it("says who is here, who is busy and who is switched off", async () => {
    serve("admin");
    const { container } = open("/hr/employees");
    await screen.findByText("Sam Adel");
    expect(within(container.querySelector('[data-person="5"]') as HTMLElement).getByText("مشغول")).toBeInTheDocument();
    expect(within(container.querySelector('[data-person="6"]') as HTMLElement).getByText("فاضي")).toBeInTheDocument();
    expect(within(container.querySelector('[data-person="7"]') as HTMLElement).getByText("موقوف")).toHaveClass("badge--dead");
  });

  it("gives the admin the button for a new person and the mail column, and HR neither", async () => {
    serve("admin");
    const admin = open("/hr/employees");
    expect(await screen.findByRole("link", { name: /موظف جديد/ })).toHaveAttribute("href", "/hr/employees/new");
    expect(screen.getByRole("columnheader", { name: "بيستقبل ميلات" })).toBeInTheDocument();
    admin.unmount();

    const hr = register();
    for (const row of hr.rows) {
      delete row.username;
      delete row.mail_alias;
    }
    serve("hr", { "/api/v1/hr/employees/": () => jsonResponse(hr) });
    open("/hr/employees");
    await screen.findByText("Sam Adel");
    expect(screen.queryByRole("link", { name: /موظف جديد/ })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "بيستقبل ميلات" })).toBeNull();
  });

  it("speaks English", async () => {
    serve("admin");
    open("/hr/employees", "en");
    expect(await screen.findByRole("heading", { name: "Employees" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Rating" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Presence" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /New staff member/ })).toBeInTheDocument();
    expect((await screen.findAllByText("Translator")).length).toBeGreaterThan(0);
  });

  it("says so when the list cannot be read", async () => {
    serve("admin", { "/api/v1/hr/employees/": () => jsonResponse({ ok: false, error: "server" }, 500) });
    open("/hr/employees");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("draws a person's picture in the list, and the initials for one who has none", async () => {
    const FACE = "/files/avatars/2026/10/cccccccccccccccc.jpg";
    const list = register();
    list.rows[0]!.avatar = FACE;
    serve("admin", { "/api/v1/hr/employees/": () => jsonResponse(list) });
    const { container } = open("/hr/employees");
    await screen.findByText("Sam Adel");
    const sam = container.querySelector('[data-person="5"]') as HTMLElement;
    expect(sam.querySelector("img")).toHaveAttribute("src", FACE);
    expect(within(sam).queryByText("SA")).toBeNull();
    const nour = container.querySelector('[data-person="6"]') as HTMLElement;
    expect(nour.querySelector("img")).toBeNull();
    expect(within(nour).getByText("NO")).toBeInTheDocument();
  });
});

describe("a person's file: the account form", () => {
  it("shows the edit button and the form behind it to the admin only, and asks for nothing of the admin's from anybody else", async () => {
    const served = serve("hr", { "/api/v1/hr/employees/5/": () => jsonResponse(hrHalf({ can: { edit: false, shift: true, plan: false } })) });
    open("/hr/employees/5");
    await screen.findByText("البيانات");
    expect(screen.queryByRole("button", { name: /عدّل$/ })).toBeNull();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/admin/"))).toBe(false);
  });

  it("keeps the form closed until the admin asks for it, and draws the classic form's fields with their labels, values and hints", async () => {
    serve("admin");
    open("/hr/employees/5");
    await screen.findByText("البيانات");
    expect(screen.queryByLabelText("First name")).toBeNull();
    await edit();
    expect(await screen.findByLabelText("First name")).toHaveValue("Sam");
    expect(screen.getByLabelText("Email address")).toHaveAttribute("type", "email");
    expect(screen.getByLabelText("Email address")).toHaveAttribute("dir", "ltr");
    expect(screen.getByText("Where we write to them.")).toHaveClass("helptext");
    expect(screen.getByLabelText("Role")).toHaveValue("translator");
    expect(screen.getByLabelText("Active")).toBeChecked();
    expect(screen.getByLabelText("Rating")).toHaveAttribute("step", "0.125");
  });

  it("closes the form again", async () => {
    serve("admin");
    open("/hr/employees/5");
    await screen.findByText("البيانات");
    await edit();
    await screen.findByLabelText("First name");
    await userEvent.click(screen.getByRole("button", { name: "قفل" }));
    expect(screen.queryByLabelText("First name")).toBeNull();
  });

  it("keeps Save off until something changes, and a field put back is no change", async () => {
    serve("admin");
    const user = userEvent.setup();
    open("/hr/employees/5");
    await screen.findByText("البيانات");
    await edit();
    const save = await screen.findByRole("button", { name: "حفظ" });
    expect(save).toBeDisabled();
    await user.type(screen.getByLabelText("First name"), "X");
    expect(save).toBeEnabled();
    await user.type(screen.getByLabelText("First name"), "{Backspace}");
    expect(save).toBeDisabled();
  });

  it("sends only the fields that were touched, and asks HR's half and the register again", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    open("/hr/employees/5");
    await screen.findByText("البيانات");
    await edit();
    await user.clear(await screen.findByLabelText("First name"));
    await user.type(screen.getByLabelText("First name"), "Samir");
    await user.selectOptions(screen.getByLabelText("Role"), "operation");
    await user.click(screen.getByLabelText("Active"));
    await user.click(screen.getByRole("button", { name: "حفظ" }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/admin/users/5/save/")).toBe(true));
    expect(served.sent.find((post) => post.url === "/api/v1/admin/users/5/save/")!.body).toEqual({ values: { first_name: "Samir", role: "operation", is_active: false } });
    await waitFor(() => expect(reads(served, "/api/v1/hr/employees/5/").length).toBe(2));
  });

  it("shows the form's own messages beside their fields and keeps what was typed when it refuses", async () => {
    serve("admin", {
      "/api/v1/admin/users/5/save/": () => jsonResponse({ ok: false, error: "invalid", errors: { email: ["Enter a valid email address."], __all__: ["Nothing was saved."] } }, 400),
    });
    const user = userEvent.setup();
    open("/hr/employees/5");
    await screen.findByText("البيانات");
    await edit();
    await user.type(await screen.findByLabelText("Email address"), "x");
    await user.click(screen.getByRole("button", { name: "حفظ" }));
    const message = await screen.findByText("Enter a valid email address.");
    expect(message.closest("ul")).toHaveClass("errorlist");
    expect(screen.getByLabelText("Email address")).toHaveAttribute("aria-describedby", "staff-email-errors");
    expect(screen.getByText("Nothing was saved.")).toBeInTheDocument();
    expect(screen.getByLabelText("Email address")).toHaveValue("sam@example.comx");
  });

  it("says so when the save fails for a reason that is not the form's", async () => {
    serve("admin", { "/api/v1/admin/users/5/save/": () => jsonResponse({ ok: false, error: "server" }, 500) });
    const user = userEvent.setup();
    open("/hr/employees/5");
    await screen.findByText("البيانات");
    await edit();
    await user.type(await screen.findByLabelText("First name"), "X");
    await user.click(screen.getByRole("button", { name: "حفظ" }));
    expect(await screen.findByText("حصلت مشكلة، ماتحفظش.")).toBeInTheDocument();
  });

  it("asks Google for the address list once as the file opens, and reads the admin's half again only if it did", async () => {
    let ran = false;
    const served = serve("admin", {
      "/api/v1/admin/aliases/sync/": (url, init) => {
        ran = true;
        return served.record(url, init, { ok: true, ran: true });
      },
    });
    open("/hr/employees/5");
    await screen.findByText("البيانات");
    await waitFor(() => expect(ran).toBe(true));
    await waitFor(() => expect(reads(served, "/api/v1/admin/users/5/").length).toBe(2));
    expect(served.sent.filter((post) => post.url === "/api/v1/admin/aliases/sync/")).toHaveLength(1);
  });

  it("does not read the admin's half again when Google was not asked", async () => {
    const served = serve("admin");
    open("/hr/employees/5");
    await screen.findByText("البيانات");
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/admin/aliases/sync/")).toBe(true));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(reads(served, "/api/v1/admin/users/5/")).toHaveLength(1);
  });

  it("does not ask Google when the person looking is not the admin", async () => {
    const served = serve("hr", { "/api/v1/hr/employees/5/": () => jsonResponse(hrHalf({ can: { edit: false, shift: true, plan: false } })) });
    open("/hr/employees/5");
    await screen.findByText("البيانات");
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(served.sent.some((post) => post.url === "/api/v1/admin/aliases/sync/")).toBe(false);
  });

  it("names the person with their picture, or their initials, and the sign-in name the admin knows them by", async () => {
    const FACE = "/files/avatars/2026/10/cccccccccccccccc.jpg";
    const withFace = hrHalf();
    withFace.person.avatar = FACE;
    serve("admin", { "/api/v1/hr/employees/5/": () => jsonResponse(withFace) });
    const first = open("/hr/employees/5");
    await screen.findByRole("heading", { name: "Sam Adel" });
    expect(first.container.querySelector(".page-head img")).toHaveAttribute("src", FACE);
    expect(await within(first.container.querySelector(".page-head") as HTMLElement).findByText("sam")).toHaveClass("mono");
    first.unmount();

    serve("admin");
    const second = open("/hr/employees/5");
    await screen.findByRole("heading", { name: "Sam Adel" });
    expect(second.container.querySelector(".page-head img")).toBeNull();
    expect(within(second.container.querySelector(".page-head") as HTMLElement).getByText("SA")).toBeInTheDocument();
  });

  it("lists the penalties to the admin", async () => {
    serve("admin");
    const { container } = open("/hr/employees/5");
    await screen.findByText("البيانات");
    const penalties = (await waitFor(() => {
      const found = container.querySelector('[data-card="penalties"]');
      expect(found).not.toBeNull();
      return found;
    })) as HTMLElement;
    expect(within(penalties).getByText("-0.125")).toHaveClass("badge--dead");
    expect(within(penalties).getByText("اتأخر")).toBeInTheDocument();
  });

  it("says no penalties when there are none, and shows none to HR", async () => {
    serve("admin", { "/api/v1/admin/users/5/": () => jsonResponse(adminHalf({ events: [] })) });
    const admin = open("/hr/employees/5");
    expect(await screen.findByText("مفيش خصومات.")).toBeInTheDocument();
    admin.unmount();
    serve("hr", { "/api/v1/hr/employees/5/": () => jsonResponse(hrHalf({ can: { edit: false, shift: true, plan: false } })) });
    const hr = open("/hr/employees/5");
    await screen.findByText("البيانات");
    expect(hr.container.querySelector('[data-card="penalties"]')).toBeNull();
  });
});

describe("a person's file: the roster rows", () => {
  it("lists the roster rows and takes one off", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    const { container } = open("/hr/employees/5");
    await screen.findByText("البيانات");
    const row = container.querySelector('[data-shift="31"]') as HTMLElement;
    expect(within(row).getByText("الاتنين")).toBeInTheDocument();
    expect(within(row).getByText("9:00 AM–5:00 PM")).toHaveClass("mono");
    await user.click(within(row).getByRole("button", { name: "امسح الشيفت" }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/admin/users/5/shifts/31/delete/")).toBe(true));
    // The roster is HR's answer, so it is asked again.
    await waitFor(() => expect(reads(served, "/api/v1/hr/employees/5/").length).toBe(2));
  });

  it("adds a roster row of typed times", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    const { container } = open("/hr/employees/5");
    await screen.findByText("البيانات");
    const roster = container.querySelector('[data-card="roster"]') as HTMLElement;
    await user.selectOptions(within(roster).getByLabelText("اليوم"), "0");
    await user.type(within(roster).getByLabelText("من"), "09:00");
    await user.type(within(roster).getByLabelText("إلى"), "17:00");
    await user.click(within(roster).getByRole("button", { name: /ضيف شيفت/ }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/admin/users/5/shifts/add/")).toBe(true));
    expect(served.sent.find((post) => post.url === "/api/v1/admin/users/5/shifts/add/")!.body).toEqual({ weekday: 0, start_time: "09:00", end_time: "17:00" });
  });

  it("says why a row was refused", async () => {
    serve("admin", { "/api/v1/admin/users/5/shifts/add/": () => jsonResponse({ ok: false, error: "times_required" }, 400) });
    const user = userEvent.setup();
    const { container } = open("/hr/employees/5");
    await screen.findByText("البيانات");
    const roster = container.querySelector('[data-card="roster"]') as HTMLElement;
    await user.click(within(roster).getByRole("button", { name: /ضيف شيفت/ }));
    expect(await within(roster).findByRole("alert")).toHaveTextContent("اكتب وقت البداية والنهاية.");
  });

  it("gives HR the roster to read and no way to take a row off or type one in", async () => {
    serve("hr", { "/api/v1/hr/employees/5/": () => jsonResponse(hrHalf({ can: { edit: false, shift: true, plan: false } })) });
    const { container } = open("/hr/employees/5");
    await screen.findByText("البيانات");
    const roster = container.querySelector('[data-card="roster"]') as HTMLElement;
    expect(roster).toHaveTextContent("9:00 AM–5:00 PM");
    expect(within(roster).queryByRole("button", { name: "امسح الشيفت" })).toBeNull();
    expect(within(roster).queryByRole("button", { name: /ضيف شيفت/ })).toBeNull();
    expect(within(roster).getByRole("link", { name: /عدّل الجدول/ })).toHaveAttribute("href", "/hr/schedules?user=5");
  });

  it("picks the company's shift from the one picker, on HR's door", async () => {
    const served = serve("admin", { "/api/v1/hr/employees/5/shift/": (url, init) => served.record(url, init, { ok: true, label: "الشيفت 1" }) });
    const user = userEvent.setup();
    open("/hr/employees/5");
    const picker = (await screen.findByRole("heading", { name: "الشيفت" })).closest(".card") as HTMLElement;
    await user.click(within(picker).getByRole("checkbox", { name: "الاتنين" }));
    await user.click(within(picker).getByRole("button", { name: /احفظ الشيفت/ }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/employees/5/shift/")).toBe(true));
    expect(served.sent.some((post) => post.url.startsWith("/api/v1/admin/users/5/shift/"))).toBe(false);
  });
});

describe("a new person", () => {
  it("draws the password boxes empty and as passwords", async () => {
    serve("admin");
    open("/hr/employees/new");
    const first = await screen.findByLabelText("Password");
    expect(first).toHaveAttribute("type", "password");
    expect(first).toHaveValue("");
    expect(first).toHaveAttribute("autocomplete", "new-password");
    expect(screen.getByLabelText("Password confirmation")).toHaveAttribute("type", "password");
  });

  it("makes the person and opens their file", async () => {
    const served = serve("admin", { "/api/v1/hr/employees/41/": () => jsonResponse(hrHalf()), "/api/v1/admin/users/41/": () => jsonResponse(adminHalf()) });
    const user = userEvent.setup();
    open("/hr/employees/new");
    await user.type(await screen.findByLabelText("Username"), "newbie");
    await user.type(screen.getByLabelText("Password"), "Quiet-harbour-41");
    await user.type(screen.getByLabelText("Password confirmation"), "Quiet-harbour-41");
    await user.selectOptions(screen.getByLabelText("Role"), "translator");
    await user.click(screen.getByRole("button", { name: "حفظ" }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/admin/users/create/")).toBe(true));
    expect(served.sent.find((post) => post.url === "/api/v1/admin/users/create/")!.body).toEqual({
      values: { username: "newbie", password1: "Quiet-harbour-41", password2: "Quiet-harbour-41", role: "translator" },
    });
    expect(await screen.findByText("البيانات")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("/hr/employees/41");
  });

  it("shows what the form refused and stays on the page, with the password still where it was typed", async () => {
    serve("admin", {
      "/api/v1/admin/users/create/": () => jsonResponse({ ok: false, error: "invalid", errors: { password2: ["The two password fields didn't match."] } }, 400),
    });
    const user = userEvent.setup();
    open("/hr/employees/new");
    await user.type(await screen.findByLabelText("Username"), "newbie");
    await user.type(screen.getByLabelText("Password"), "abc");
    await user.click(screen.getByRole("button", { name: "حفظ" }));
    expect(await screen.findByText("The two password fields didn't match.")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveValue("abc");
    expect(screen.getByTestId("where")).toHaveTextContent("/hr/employees/new");
  });

  it("sends anybody who is not the admin home and asks for nothing", async () => {
    const served = serve("hr");
    open("/hr/employees/new");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/admin/"))).toBe(false);
  });
});

describe("the owner is not bound by the company's rules", () => {
  const ownerFile = () =>
    hrHalf({
      person: { ...hrHalf().person, exempt: true, name: "Eagle Admin", role: { value: "admin", ar: "أدمن", en: "Admin" } },
      shifts: [],
      picker: null,
      work_mode_card: null,
      can: { edit: true, shift: false, plan: false },
    });

  it("draws the owner's file without attendance, roster, penalties or a pay plan, and says why", async () => {
    serve("admin", { "/api/v1/hr/employees/5/": () => jsonResponse(ownerFile()) });
    const { container } = open("/hr/employees/5");
    await screen.findByText("البيانات");
    expect(container.querySelector('[data-note="exempt"]')).toHaveTextContent("مالوش حضور ولا جدول ولا إجازات ولا راتب");
    for (const card of ["attendance", "roster", "penalties", "plan", "picker", "work-mode", "probation", "salary"]) {
      expect(container.querySelector(`[data-card="${card}"]`), card).toBeNull();
    }
    // The account form is still the admin's to open.
    expect(screen.getByRole("button", { name: /عدّل$/ })).toBeInTheDocument();
  });

  it("keeps the attendance, roster and pay plan on an employee's file", async () => {
    serve("admin", {
      "/api/v1/hr/employees/5/": () => jsonResponse(hrHalf({ summary: { scheduled_days: 22, present_days: 18, office_days: 12, remote_days: 6, leave_days: 1, absent_days: 2, late_days: 3, work_minutes: 9000, overtime_minutes: 90 } })),
    });
    const { container } = open("/hr/employees/5");
    await screen.findByText("البيانات");
    expect(container.querySelector('[data-note="exempt"]')).toBeNull();
    for (const card of ["attendance", "roster", "plan"]) expect(container.querySelector(`[data-card="${card}"]`), card).not.toBeNull();
  });

  it("shows a dash for the owner's shifts and rating in the list, and the figures for everybody else", async () => {
    const list = register();
    list.rows.push({ id: 1, code: "", name: "Eagle Admin", initials: "EA", role: { value: "admin", ar: "أدمن", en: "Admin" }, department: null, team_lead: null, employment: fullTime, joining_date: null, status: confirmed, state: "free", seen: stampOf("الآن", "now"), shifts: null, rating: null, username: "boss", mail_alias: "" });
    serve("admin", { "/api/v1/hr/employees/": () => jsonResponse(list) });
    const { container } = open("/hr/employees");
    await screen.findByText("Eagle Admin");
    const owner = container.querySelector('[data-person="1"]') as HTMLElement;
    expect(owner.querySelector(".rating")).toBeNull();
    const cells = Array.from(owner.querySelectorAll("td")).map((cell) => cell.textContent);
    expect(cells.filter((text) => text === "—").length).toBeGreaterThanOrEqual(2);
    const sam = container.querySelector('[data-person="5"]') as HTMLElement;
    expect(sam.querySelector(".rating")).not.toBeNull();
    expect(within(sam).getByText("3")).toHaveClass("mono");
  });
});
