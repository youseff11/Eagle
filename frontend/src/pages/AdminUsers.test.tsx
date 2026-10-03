import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AdminUser, AdminUserNew, AdminUsers, FormField, Role } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { AdminUserNewPage, AdminUserPage } from "./AdminUserPage";
import { AdminUsersPage } from "./AdminUsersPage";

afterEach(() => vi.unstubAllGlobals());

const stamp = (text: string) => ({ ar: `${text} م`, en: `${text} PM` });

function field(name: string, label: string, over: Partial<FormField> = {}): FormField {
  return { name, label, kind: "text", required: false, help: "", disabled: false, ltr: false, value: "", ...over };
}

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

function userFile(over: Partial<AdminUser> = {}): AdminUser {
  return {
    ok: true,
    user: { id: 5, username: "sam", name: "Sam Adel", initials: "SA", role: { value: "translator", ar: "مترجم", en: "Translator" } },
    form: fileForm(),
    shifts: [{ id: 31, weekday: { num: 0, ar: "الاتنين", en: "Monday" }, start: stamp("9:00").en ? { ar: "9:00 ص", en: "9:00 AM" } : null, end: { ar: "5:00 م", en: "5:00 PM" } }],
    events: [{ delta: "-0.125", reason: "اتأخر", at: stamp("10-01") }],
    picker: {
      current: 3,
      has_custom: false,
      templates: [
        { id: 3, label: "الشيفت 1", start: { ar: "9:00 ص", en: "9:00 AM" }, end: { ar: "5:00 م", en: "5:00 PM" } },
        { id: 4, label: "الشيفت 2", start: { ar: "5:00 م", en: "5:00 PM" }, end: { ar: "1:00 ص", en: "1:00 AM" } },
      ],
      days: [
        { num: 5, ar: "السبت", en: "Saturday", checked: true },
        { num: 6, ar: "الحد", en: "Sunday", checked: true },
        { num: 0, ar: "الاتنين", en: "Monday", checked: false },
      ],
    },
    ...over,
  };
}

function usersList(): AdminUsers {
  return {
    ok: true,
    users: [
      { id: 5, username: "sam", name: "Sam Adel", initials: "SA", role: { value: "translator", ar: "مترجم", en: "Translator" }, team_lead: "Mona", mail_alias: "", state: "busy", seen: stamp("5:30"), shifts: 3, rating: 4.5 },
      { id: 6, username: "nour", name: "Nour Ops", initials: "NO", role: { value: "operation", ar: "أوبريشن", en: "Operation" }, team_lead: null, mail_alias: "ops1@example.com", state: "free", seen: stamp("5:31"), shifts: 0, rating: 5 },
      { id: 7, username: "old", name: "Old Timer", initials: "OT", role: { value: "hr", ar: "موارد بشرية", en: "HR" }, team_lead: null, mail_alias: "", state: "disabled", seen: { ar: "من يومين", en: "2 d ago" }, shifts: 1, rating: 3.25 },
    ],
  };
}

type Posts = { url: string; body: unknown }[];

function serve(who: Role, over: Record<string, (url: URL, init: RequestInit | undefined) => Response | Promise<Response>> = {}) {
  const posts: Posts = [];
  const record = (url: URL, init: RequestInit | undefined, answer: unknown, status = 200) => {
    posts.push({ url: url.pathname, body: init?.body ? JSON.parse(String(init.body)) : null });
    return jsonResponse(answer, status);
  };
  // The first prefix that matches answers, so what a test overrides goes first and the defaults after it.
  const defaults: Record<string, (url: URL, init: RequestInit | undefined) => Response | Promise<Response>> = {
    "/api/v1/me/": () => jsonResponse(me({ role: who, is_admin: who === "admin" })),
    "/api/v1/admin/aliases/sync/": (url, init) => record(url, init, { ok: true, ran: false }),
    "/api/v1/admin/users/new/": () => jsonResponse({ ok: true, form: newForm() } satisfies AdminUserNew),
    "/api/v1/admin/users/create/": (url, init) => record(url, init, { ok: true, id: 41 }),
    "/api/v1/admin/users/5/save/": (url, init) => record(url, init, { ok: true }),
    "/api/v1/admin/users/5/shift/": (url, init) => record(url, init, { ok: true, label: "الشيفت 2" }),
    "/api/v1/admin/users/5/shifts/add/": (url, init) => record(url, init, { ok: true, id: 90 }),
    "/api/v1/admin/users/5/shifts/31/delete/": (url, init) => record(url, init, { ok: true, deleted: 1 }),
    "/api/v1/admin/users/5/": () => jsonResponse(userFile()),
    "/api/v1/admin/users/": () => jsonResponse(usersList()),
  };
  const routes = { ...over };
  for (const [prefix, answer] of Object.entries(defaults)) if (!(prefix in routes)) routes[prefix] = answer;
  const mocked = mockFetch(routes);
  vi.stubGlobal("fetch", mocked.fn);
  return { ...mocked, posts };
}

function newForm(): FormField[] {
  return [
    field("username", "Username", { ltr: true, required: true }),
    field("password1", "Password", { kind: "password", required: true, ltr: true, saved: false }),
    field("password2", "Password confirmation", { kind: "password", required: true, ltr: true, saved: false }),
    field("role", "Role", { kind: "select", choices: [{ value: "operation", label: "Operation" }, { value: "translator", label: "Translator" }], value: "operation" }),
  ];
}

function open(route: string, lang: "ar" | "en" = "ar") {
  return renderWithProviders(
    <Routes>
      <Route path="/admin/users" element={<AdminUsersPage />} />
      <Route path="/admin/users/new" element={<AdminUserNewPage />} />
      <Route path="/admin/users/:id" element={<AdminUserPage />} />
      <Route path="/" element={<div>home page</div>} />
    </Routes>,
    { route, lang },
  );
}

describe("AdminUsersPage", () => {
  it("lists everybody with their role, leader, mail address, shifts and a link to the file", async () => {
    serve("admin");
    const { container } = open("/admin/users");
    await screen.findByText("Sam Adel");
    const sam = container.querySelector('[data-user="5"]') as HTMLElement;
    expect(within(sam).getByText("sam")).toHaveClass("mono");
    expect(within(sam).getByText("مترجم")).toHaveClass("chip");
    expect(within(sam).getByText("Mona")).toBeInTheDocument();
    expect(within(sam).getByText("3")).toHaveClass("mono");
    expect(within(sam).getByRole("link", { name: "تعديل" })).toHaveAttribute("href", "/admin/users/5");
    const nour = container.querySelector('[data-user="6"]') as HTMLElement;
    expect(within(nour).getByText("ops1@example.com")).toBeInTheDocument();
    expect(within(nour).getAllByText("—").length).toBeGreaterThan(0);
  });

  it("says who is here, who is busy and who is switched off", async () => {
    serve("admin");
    const { container } = open("/admin/users");
    await screen.findByText("Sam Adel");
    expect(within(container.querySelector('[data-user="5"]') as HTMLElement).getByText("مشغول")).toBeInTheDocument();
    expect(within(container.querySelector('[data-user="6"]') as HTMLElement).getByText("فاضي")).toBeInTheDocument();
    expect(within(container.querySelector('[data-user="7"]') as HTMLElement).getByText("موقوف")).toHaveClass("badge--dead");
  });

  it("opens the form for a new person", async () => {
    serve("admin");
    open("/admin/users");
    expect(await screen.findByRole("link", { name: /موظف جديد/ })).toHaveAttribute("href", "/admin/users/new");
  });

  it("speaks English", async () => {
    serve("admin");
    open("/admin/users", "en");
    expect(await screen.findByText("Staff & shifts")).toBeInTheDocument();
    expect((await screen.findAllByText("Translator")).length).toBeGreaterThan(0);
  });

  it("sends anybody who is not the admin home and asks the server for nothing", async () => {
    const served = serve("operation");
    open("/admin/users");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/admin/"))).toBe(false);
  });

  it("says so when the table cannot be read", async () => {
    serve("admin", { "/api/v1/admin/users/": () => jsonResponse({ ok: false, error: "server" }, 500) });
    open("/admin/users");
    expect(await screen.findByRole("alert")).toHaveTextContent("حصلت مشكلة في التحميل.");
  });
});

describe("AdminUserPage: the form", () => {
  it("draws the classic form's fields with their labels, values, hints and kinds", async () => {
    serve("admin");
    open("/admin/users/5");
    expect(await screen.findByLabelText("First name")).toHaveValue("Sam");
    expect(screen.getByLabelText("Email address")).toHaveAttribute("type", "email");
    expect(screen.getByLabelText("Email address")).toHaveAttribute("dir", "ltr");
    expect(screen.getByText("Where we write to them.")).toHaveClass("helptext");
    expect(screen.getByLabelText("Role")).toHaveValue("translator");
    expect(screen.getByLabelText("Active")).toBeChecked();
    expect(screen.getByLabelText("Rating")).toHaveAttribute("step", "0.125");
  });

  it("keeps Save off until something changes, and a field put back is no change", async () => {
    serve("admin");
    const user = userEvent.setup();
    open("/admin/users/5");
    const save = await screen.findByRole("button", { name: "حفظ" });
    expect(save).toBeDisabled();
    await user.type(screen.getByLabelText("First name"), "X");
    expect(save).toBeEnabled();
    await user.type(screen.getByLabelText("First name"), "{Backspace}");
    expect(save).toBeDisabled();
  });

  it("sends only the fields that were touched", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    open("/admin/users/5");
    await user.clear(await screen.findByLabelText("First name"));
    await user.type(screen.getByLabelText("First name"), "Samir");
    await user.selectOptions(screen.getByLabelText("Role"), "operation");
    await user.click(screen.getByLabelText("Active"));
    await user.click(screen.getByRole("button", { name: "حفظ" }));
    await waitFor(() => expect(served.posts.some((post) => post.url === "/api/v1/admin/users/5/save/")).toBe(true));
    const sent = served.posts.find((post) => post.url === "/api/v1/admin/users/5/save/")!.body;
    expect(sent).toEqual({ values: { first_name: "Samir", role: "operation", is_active: false } });
  });

  it("shows the form's own messages beside their fields and keeps what was typed when it refuses", async () => {
    serve("admin", {
      "/api/v1/admin/users/5/save/": () => jsonResponse({ ok: false, error: "invalid", errors: { email: ["Enter a valid email address."], __all__: ["Nothing was saved."] } }, 400),
    });
    const user = userEvent.setup();
    open("/admin/users/5");
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
    open("/admin/users/5");
    await user.type(await screen.findByLabelText("First name"), "X");
    await user.click(screen.getByRole("button", { name: "حفظ" }));
    expect(await screen.findByText("حصلت مشكلة، ماتحفظش.")).toBeInTheDocument();
  });

  it("asks Google for the address list once as the file opens, and reads the file again only if it did", async () => {
    let ran = false;
    const served = serve("admin", {
      "/api/v1/admin/aliases/sync/": (url, init) => {
        ran = true;
        served.posts.push({ url: url.pathname, body: init?.body ? JSON.parse(String(init.body)) : null });
        return jsonResponse({ ok: true, ran: true });
      },
    });
    open("/admin/users/5");
    await screen.findByLabelText("First name");
    await waitFor(() => expect(ran).toBe(true));
    await waitFor(() => expect(served.calls.filter((call) => call.url === "/api/v1/admin/users/5/").length).toBe(2));
    expect(served.posts.filter((post) => post.url === "/api/v1/admin/aliases/sync/")).toHaveLength(1);
  });

  it("does not read the file again when Google was not asked", async () => {
    const served = serve("admin");
    open("/admin/users/5");
    await screen.findByLabelText("First name");
    await waitFor(() => expect(served.posts.some((post) => post.url === "/api/v1/admin/aliases/sync/")).toBe(true));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(served.calls.filter((call) => call.url === "/api/v1/admin/users/5/")).toHaveLength(1);
  });

  it("sends anybody who is not the admin home, and a bad id to the table", async () => {
    const served = serve("sales");
    open("/admin/users/5");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/admin/"))).toBe(false);
  });

  it("sends a bad id to the table without asking for it", async () => {
    const served = serve("admin");
    open("/admin/users/abc");
    expect(await screen.findByText("الموظفين والشيفتات")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.includes("/users/abc") || call.url.includes("/users/NaN"))).toBe(false);
  });

  it("lists the penalties", async () => {
    serve("admin");
    const { container } = open("/admin/users/5");
    await screen.findByLabelText("First name");
    const penalties = container.querySelector('[data-card="penalties"]') as HTMLElement;
    expect(within(penalties).getByText("-0.125")).toHaveClass("badge--dead");
    expect(within(penalties).getByText("اتأخر")).toBeInTheDocument();
  });
});

describe("AdminUserPage: the shifts", () => {
  it("lists the roster rows and takes one off", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    const { container } = open("/admin/users/5");
    await screen.findByLabelText("First name");
    const row = container.querySelector('[data-shift="31"]') as HTMLElement;
    expect(within(row).getByText("الاتنين")).toBeInTheDocument();
    expect(within(row).getByText("9:00 ص → 5:00 م")).toHaveClass("mono");
    await user.click(within(row).getByRole("button", { name: "امسح الشيفت" }));
    await waitFor(() => expect(served.posts.some((post) => post.url === "/api/v1/admin/users/5/shifts/31/delete/")).toBe(true));
  });

  it("adds a roster row of typed times", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    open("/admin/users/5");
    const shifts = (await screen.findByRole("heading", { name: "الشيفتات" })).closest(".card") as HTMLElement;
    await user.selectOptions(within(shifts).getByLabelText("اليوم"), "0");
    await user.type(within(shifts).getByLabelText("من"), "09:00");
    await user.type(within(shifts).getByLabelText("إلى"), "17:00");
    await user.click(within(shifts).getByRole("button", { name: /ضيف شيفت/ }));
    await waitFor(() => expect(served.posts.some((post) => post.url === "/api/v1/admin/users/5/shifts/add/")).toBe(true));
    expect(served.posts.find((post) => post.url === "/api/v1/admin/users/5/shifts/add/")!.body).toEqual({ weekday: 0, start_time: "09:00", end_time: "17:00" });
  });

  it("says why a row was refused", async () => {
    serve("admin", { "/api/v1/admin/users/5/shifts/add/": () => jsonResponse({ ok: false, error: "times_required" }, 400) });
    const user = userEvent.setup();
    open("/admin/users/5");
    const shifts = (await screen.findByRole("heading", { name: "الشيفتات" })).closest(".card") as HTMLElement;
    await user.click(within(shifts).getByRole("button", { name: /ضيف شيفت/ }));
    expect(await within(shifts).findByRole("alert")).toHaveTextContent("اكتب وقت البداية والنهاية.");
  });

  it("starts the picker on the shift most of the roster is on and the days it works", async () => {
    serve("admin");
    open("/admin/users/5");
    const picker = (await screen.findByRole("heading", { name: "الشيفت" })).closest(".card") as HTMLElement;
    expect(within(picker).getByRole("radio", { name: /الشيفت 1/ })).toBeChecked();
    expect(within(picker).getByRole("radio", { name: /الشيفت 2/ })).not.toBeChecked();
    expect(within(picker).getByRole("checkbox", { name: "السبت" })).toBeChecked();
    expect(within(picker).getByRole("checkbox", { name: "الاتنين" })).not.toBeChecked();
  });

  it("sends the chosen shift and days", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    open("/admin/users/5");
    const picker = (await screen.findByRole("heading", { name: "الشيفت" })).closest(".card") as HTMLElement;
    await user.click(within(picker).getByRole("radio", { name: /الشيفت 2/ }));
    await user.click(within(picker).getByRole("checkbox", { name: "الاتنين" }));
    await user.click(within(picker).getByRole("checkbox", { name: "الحد" }));
    await user.click(within(picker).getByRole("button", { name: /احفظ الشيفت/ }));
    await waitFor(() => expect(served.posts.some((post) => post.url === "/api/v1/admin/users/5/shift/")).toBe(true));
    expect(served.posts.find((post) => post.url === "/api/v1/admin/users/5/shift/")!.body).toEqual({
      template: "4",
      weekdays: [5, 0],
      new_name: "",
      new_start: "",
      new_end: "",
    });
  });

  it("makes a new shift from a name and two times", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    open("/admin/users/5");
    const picker = (await screen.findByRole("heading", { name: "الشيفت" })).closest(".card") as HTMLElement;
    await user.click(within(picker).getByRole("radio", { name: /شيفت جديد/ }));
    await user.type(within(picker).getByLabelText("اسم الشيفت"), "Late");
    await user.type(within(picker).getByLabelText("من"), "14:00");
    await user.type(within(picker).getByLabelText("إلى"), "22:00");
    await user.click(within(picker).getByRole("button", { name: /احفظ الشيفت/ }));
    await waitFor(() => expect(served.posts.some((post) => post.url === "/api/v1/admin/users/5/shift/")).toBe(true));
    expect(served.posts.find((post) => post.url === "/api/v1/admin/users/5/shift/")!.body).toMatchObject({
      template: "new",
      new_name: "Late",
      new_start: "14:00",
      new_end: "22:00",
    });
  });

  it("says in words why the choice was refused", async () => {
    serve("admin", { "/api/v1/admin/users/5/shift/": () => jsonResponse({ ok: false, error: "no_days" }, 400) });
    const user = userEvent.setup();
    open("/admin/users/5");
    const picker = (await screen.findByRole("heading", { name: "الشيفت" })).closest(".card") as HTMLElement;
    await user.click(within(picker).getByRole("button", { name: /احفظ الشيفت/ }));
    expect(await within(picker).findByRole("alert")).toHaveTextContent("اختار أيام الشغل.");
  });

  it("warns that a custom schedule is replaced", async () => {
    serve("admin", { "/api/v1/admin/users/5/": () => jsonResponse(userFile({ picker: { ...userFile().picker, has_custom: true } })) });
    open("/admin/users/5");
    expect(await screen.findByText(/عنده جدول مخصص دلوقتي/)).toBeInTheDocument();
  });

  it("links to the full schedule on the HR page", async () => {
    serve("admin");
    open("/admin/users/5");
    expect(await screen.findByRole("link", { name: /الجدول الكامل ونظام العمل/ })).toHaveAttribute("href", "/hr/schedules/?user=5");
  });
});

describe("AdminUserNewPage", () => {
  it("draws the password boxes empty and as passwords", async () => {
    serve("admin");
    open("/admin/users/new");
    const first = await screen.findByLabelText("Password");
    expect(first).toHaveAttribute("type", "password");
    expect(first).toHaveValue("");
    expect(first).toHaveAttribute("autocomplete", "new-password");
    expect(screen.getByLabelText("Password confirmation")).toHaveAttribute("type", "password");
  });

  it("makes the person and opens their file", async () => {
    const served = serve("admin", { "/api/v1/admin/users/41/": () => jsonResponse(userFile({ user: { ...userFile().user, id: 41 } })) });
    const user = userEvent.setup();
    open("/admin/users/new");
    await user.type(await screen.findByLabelText("Username"), "newbie");
    await user.type(screen.getByLabelText("Password"), "Quiet-harbour-41");
    await user.type(screen.getByLabelText("Password confirmation"), "Quiet-harbour-41");
    await user.selectOptions(screen.getByLabelText("Role"), "translator");
    await user.click(screen.getByRole("button", { name: "حفظ" }));
    await waitFor(() => expect(served.posts.some((post) => post.url === "/api/v1/admin/users/create/")).toBe(true));
    expect(served.posts.find((post) => post.url === "/api/v1/admin/users/create/")!.body).toEqual({
      values: { username: "newbie", password1: "Quiet-harbour-41", password2: "Quiet-harbour-41", role: "translator" },
    });
    expect(await screen.findByLabelText("First name")).toBeInTheDocument();
  });

  it("shows what the form refused and stays on the page, with the password still where it was typed", async () => {
    serve("admin", {
      "/api/v1/admin/users/create/": () => jsonResponse({ ok: false, error: "invalid", errors: { password2: ["The two password fields didn't match."] } }, 400),
    });
    const user = userEvent.setup();
    open("/admin/users/new");
    await user.type(await screen.findByLabelText("Username"), "newbie");
    await user.type(screen.getByLabelText("Password"), "abc");
    await user.click(screen.getByRole("button", { name: "حفظ" }));
    expect(await screen.findByText("The two password fields didn't match.")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveValue("abc");
  });

  it("sends anybody who is not the admin home", async () => {
    const served = serve("hr");
    open("/admin/users/new");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/admin/"))).toBe(false);
  });
});
