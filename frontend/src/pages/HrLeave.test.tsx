import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DayStatusJson, HrLeave, LeaveRequestJson, MyLeave, Role } from "../api/types";
import { jsonResponse } from "../test/helpers";
import { field, openHr as open, reads, serveHr, stampOf, type Handler } from "../test/hr";

afterEach(() => vi.unstubAllGlobals());

const serve = (who: Role, routes: Record<string, Handler>) => serveHr(who, routes);

const waiting: DayStatusJson = { value: "pending", tone: "wait", ar: "مستني", en: "Waiting" };
const managerOk: DayStatusJson = { value: "manager_ok", tone: "info", ar: "المدير وافق", en: "Manager approved" };
const approved: DayStatusJson = { value: "approved", tone: "ok", ar: "اتوافق عليه", en: "Approved" };
const rejected: DayStatusJson = { value: "rejected", tone: "dead", ar: "مرفوض", en: "Rejected" };

function request(id: number, over: Partial<LeaveRequestJson> = {}): LeaveRequestJson {
  return {
    id,
    kind: { value: "annual", ar: "إجازة اعتيادية", en: "Annual leave" },
    is_permission: false,
    start_date: "2026-10-12",
    end_date: "2026-10-14",
    days: 3,
    minutes: 0,
    start_time: null,
    end_time: null,
    status: managerOk,
    is_open: true,
    reason: "",
    decision_note: "",
    ...over,
  };
}

function mine(over: Partial<MyLeave> = {}): MyLeave {
  return {
    ok: true,
    balance: { allowance: 4, taken: 1, pending: 2, left: 1, over: 0 },
    rows: [
      request(1),
      request(2, { status: rejected, is_open: false, decision_note: "Busy week", start_date: "2026-09-01", end_date: "2026-09-02", days: 2 }),
      request(3, {
        kind: { value: "permission", ar: "إذن (ساعات)", en: "Permission (hours)" },
        is_permission: true,
        end_date: null,
        days: 0,
        minutes: 150,
        start_time: stampOf("10:00 ص", "10:00 AM"),
        end_time: stampOf("12:30 م", "12:30 PM"),
        status: approved,
        is_open: false,
      }),
    ],
    form: [
      field("kind", "Kind", {
        kind: "select",
        value: "annual",
        label_ar: "النوع",
        label_en: "Kind",
        choices: [
          { value: "annual", label: "Annual leave", label_ar: "إجازة اعتيادية", label_en: "Annual leave" },
          { value: "permission", label: "Permission (hours)", label_ar: "إذن (ساعات)", label_en: "Permission (hours)" },
        ],
      }),
      field("start_date", "From", { kind: "date", label_ar: "من", label_en: "From" }),
      field("end_date", "To", { kind: "date", label_ar: "إلى", label_en: "To" }),
      field("start_time", "From (permission)", { kind: "time", label_ar: "من الساعة (للإذن)", label_en: "From (permission)" }),
      field("reason", "Reason", { label_ar: "السبب", label_en: "Reason" }),
    ],
    needs_manager: false,
    ...over,
  };
}

const minePage = (data: MyLeave = mine()) => ({ "/api/v1/leave/": () => jsonResponse(data) });

function fireValue(input: HTMLElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  setter.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("MyLeavePage", () => {
  it("shows what is left of the month and the requests so far", async () => {
    serve("translator", minePage());
    const { container } = open("/leave");
    await screen.findByText("طلباتي");
    expect(Array.from(container.querySelectorAll(".kpi")).map((one) => one.textContent)).toEqual(["رصيد الشهر4", "مستخدم1", "مستني موافقة2", "الباقي1"]);
    expect(container.querySelectorAll(".kpi--ok")).toHaveLength(1);
    const first = container.querySelector('[data-request="1"]') as HTMLElement;
    expect(within(first).getByText("إجازة اعتيادية")).toBeInTheDocument();
    expect(within(first).getByText("3")).toBeInTheDocument();
    expect(within(first).getByText("المدير وافق")).toHaveClass("badge--info");
  });

  it("draws a permission by its window and a decided request with its note", async () => {
    serve("translator", minePage());
    const { container } = open("/leave");
    await screen.findByText("طلباتي");
    const permission = container.querySelector('[data-request="3"]') as HTMLElement;
    expect(within(permission).getByText("2:30")).toBeInTheDocument();
    expect(within(permission).getByText("—")).toBeInTheDocument();
    expect(within(permission).queryByRole("button", { name: /اسحب/ })).toBeNull();
    const decided = container.querySelector('[data-request="2"]') as HTMLElement;
    expect(within(decided).getByText("Busy week")).toBeInTheDocument();
    expect(within(decided).getByText("مرفوض")).toHaveClass("badge--dead");
  });

  it("warns when days are beyond the allowance and says nothing when they are not", async () => {
    serve("translator", minePage(mine({ balance: { allowance: 4, taken: 5, pending: 1, left: 0, over: 2 } })));
    const view = open("/leave");
    expect(await screen.findByText(/فيه 2 يوم فوق الرصيد/)).toBeInTheDocument();
    expect(view.container.querySelector(".kpi--warn")).not.toBeNull();
    view.unmount();
    serve("translator", minePage());
    const quiet = open("/leave");
    await screen.findByText("طلباتي");
    expect(quiet.container.querySelector('[data-note="over"]')).toBeNull();
  });

  it("says who the request goes to", async () => {
    serve("translator", minePage());
    const direct = open("/leave");
    await screen.findByText("طلباتي");
    expect(direct.container.querySelector('[data-note="chain"]')).toHaveTextContent("الطلب بيروح للموارد البشرية مباشرة.");
    direct.unmount();
    serve("translator", minePage(mine({ needs_manager: true })));
    const chain = open("/leave");
    await screen.findByText("طلباتي");
    expect(chain.container.querySelector('[data-note="chain"]')).toHaveTextContent("الطلب بيروح لمديرك الأول وبعدين للموارد البشرية.");
  });

  it("withdraws an open request and offers nothing for one that is decided", async () => {
    const served = serve("translator", {
      ...minePage(),
      "/api/v1/leave/1/cancel/": (url, init) => served.record(url, init, { ok: true }),
    });
    const user = userEvent.setup();
    const { container } = open("/leave");
    await screen.findByText("طلباتي");
    expect(within(container.querySelector('[data-request="2"]') as HTMLElement).queryByRole("button")).toBeNull();
    await user.click(within(container.querySelector('[data-request="1"]') as HTMLElement).getByRole("button", { name: /اسحب/ }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/leave/1/cancel/")).toBe(true));
    expect(await screen.findByText("اتسحب")).toBeInTheDocument();
  });

  it("says why a withdrawal did not go", async () => {
    serve("translator", {
      ...minePage(),
      "/api/v1/leave/1/cancel/": () => jsonResponse({ ok: false, error: "already_decided", message: "الطلب اتقرر فيه بالفعل." }, 409),
    });
    const user = userEvent.setup();
    const { container } = open("/leave");
    await screen.findByText("طلباتي");
    await user.click(within(container.querySelector('[data-request="1"]') as HTMLElement).getByRole("button", { name: /اسحب/ }));
    expect(await screen.findByText("الطلب اتقرر فيه بالفعل.")).toBeInTheDocument();
  });

  it("asks for leave with what was typed, nothing else", async () => {
    const served = serve("translator", {
      ...minePage(),
      "/api/v1/leave/request/": (url, init) => served.record(url, init, { ok: true, id: 9 }),
    });
    const user = userEvent.setup();
    open("/leave");
    await screen.findByText("اطلب إجازة");
    const send = screen.getByRole("button", { name: "ابعت الطلب" });
    expect(send).toBeDisabled();
    expect(within(screen.getByLabelText("النوع")).getByRole("option", { name: "إذن (ساعات)" })).toBeInTheDocument();
    fireValue(screen.getByLabelText("من"), "2026-10-20");
    await user.type(screen.getByLabelText("السبب"), "Trip");
    await user.click(send);
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/leave/request/")).toBe(true));
    expect(served.sent.find((post) => post.url === "/api/v1/leave/request/")!.body).toEqual({ values: { start_date: "2026-10-20", reason: "Trip" } });
    expect(await screen.findByText("الطلب اتبعت")).toBeInTheDocument();
  });

  it("shows the form's refusal beside its box and keeps what was typed", async () => {
    serve("translator", {
      ...minePage(),
      "/api/v1/leave/request/": () => jsonResponse({ ok: false, error: "invalid", errors: { end_date: ["لازم يكون بعد تاريخ البداية."] } }, 400),
    });
    const user = userEvent.setup();
    open("/leave");
    await screen.findByText("اطلب إجازة");
    fireValue(screen.getByLabelText("من"), "2026-10-20");
    fireValue(screen.getByLabelText("إلى"), "2026-10-10");
    await user.click(screen.getByRole("button", { name: "ابعت الطلب" }));
    expect(await screen.findByText("لازم يكون بعد تاريخ البداية.")).toBeInTheDocument();
    expect(screen.getByLabelText("من")).toHaveValue("2026-10-20");
  });

  it("shows the engine's refusal in its own words", async () => {
    serve("translator", {
      ...minePage(),
      "/api/v1/leave/request/": () => jsonResponse({ ok: false, error: "refused", message: "فيه طلب تاني على نفس الأيام." }, 409),
    });
    const user = userEvent.setup();
    open("/leave");
    await screen.findByText("اطلب إجازة");
    fireValue(screen.getByLabelText("من"), "2026-10-13");
    await user.click(screen.getByRole("button", { name: "ابعت الطلب" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("فيه طلب تاني على نفس الأيام.");
  });

  it("is anybody's own page: every role opens it and none is sent away", async () => {
    for (const who of ["operation", "team_lead", "translator", "hr", "reviewer", "accounting", "sales", "admin"] as const) {
      const served = serve(who, minePage());
      const view = open("/leave");
      expect(await screen.findByText("طلباتي"), who).toBeInTheDocument();
      expect(served.calls.some((call) => call.url === "/api/v1/leave/"), who).toBe(true);
      view.unmount();
    }
  });

  it("says so when the page cannot be read", async () => {
    serve("translator", { "/api/v1/leave/": () => jsonResponse({ ok: false, error: "server" }, 500) });
    open("/leave");
    expect(await screen.findByRole("alert")).toHaveTextContent("حصلت مشكلة في التحميل.");
  });
});

function queue(over: Partial<HrLeave> = {}): HrLeave {
  return {
    ok: true,
    waiting: [
      { ...request(11, { status: waiting, reason: "Wedding" }), user: { id: 21, name: "Sam" }, manager: "Mona", can_decide: true },
      { ...request(12, { status: managerOk, kind: { value: "permission", ar: "إذن (ساعات)", en: "Permission (hours)" }, is_permission: true, end_date: null, days: 0, minutes: 120, start_time: stampOf("10:00 ص", "10:00 AM"), end_time: stampOf("12:00 م", "12:00 PM") }), user: { id: 22, name: "Nada" }, manager: null, can_decide: true },
    ],
    rows: [
      { ...request(13, { status: approved, is_open: false }), user: { id: 21, name: "Sam" }, decided_by: "Hala", applied: true },
      { ...request(14, { status: rejected, is_open: false, start_date: "2026-09-01", end_date: "2026-09-02", days: 2 }), user: { id: 22, name: "Nada" }, decided_by: null, applied: false },
    ],
    options: { people: [{ id: 21, name: "Sam" }, { id: 22, name: "Nada" }], statuses: [waiting, managerOk, approved, rejected] },
    ...over,
  };
}

const queuePage = (data: HrLeave = queue()) => ({ "/api/v1/hr/leave/": () => jsonResponse(data) });

describe("HrLeavePage", () => {
  it("lists what waits, with its dates, its reason, and who it waits for", async () => {
    serve("hr", queuePage());
    const { container } = open("/hr/leave");
    await screen.findByText("مستني قرار");
    expect(container.querySelector('[data-count="waiting"]')).toHaveTextContent("2");
    const first = container.querySelector('[data-waiting="11"]') as HTMLElement;
    expect(first).toHaveTextContent("Sam");
    expect(first).toHaveTextContent("2026-10-12 → 2026-10-14");
    expect(first).toHaveTextContent("(3 يوم)");
    expect(first).toHaveTextContent("Wedding");
    expect(first.querySelector("[data-manager]")).toHaveTextContent("Mona");
    const second = container.querySelector('[data-waiting="12"]') as HTMLElement;
    expect(second).toHaveTextContent("10:00 ص–12:00 م");
    expect(second.querySelector("[data-manager]")).toBeNull();
  });

  it("approves, and rejects with the reason that was typed", async () => {
    const served = serve("hr", {
      ...queuePage(),
      "/api/v1/leave/11/approve/": (url, init) => served.record(url, init, { ok: true }),
      "/api/v1/leave/12/reject/": (url, init) => served.record(url, init, { ok: true }),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/leave");
    await screen.findByText("مستني قرار");
    const first = container.querySelector('[data-waiting="11"]') as HTMLElement;
    // A reason typed and then an approval: the reason belongs to a rejection and goes nowhere else.
    await user.type(within(first).getByLabelText("السبب"), "changed my mind");
    await user.click(within(first).getByRole("button", { name: "وافق" }));
    const second = container.querySelector('[data-waiting="12"]') as HTMLElement;
    await user.type(within(second).getByLabelText("السبب"), "Busy week");
    await user.click(within(second).getByRole("button", { name: "ارفض" }));
    await waitFor(() => expect(served.sent).toHaveLength(2));
    expect(served.sent[0]).toEqual({ url: "/api/v1/leave/11/approve/", body: { note: "" } });
    expect(served.sent[1]).toEqual({ url: "/api/v1/leave/12/reject/", body: { note: "Busy week" } });
  });

  it("offers the buttons only where this person may press them", async () => {
    const data = queue();
    data.waiting[1] = { ...data.waiting[1]!, can_decide: false };
    serve("hr", queuePage(data));
    const { container } = open("/hr/leave");
    await screen.findByText("مستني قرار");
    expect(within(container.querySelector('[data-waiting="11"]') as HTMLElement).getByRole("button", { name: "وافق" })).toBeInTheDocument();
    expect(within(container.querySelector('[data-waiting="12"]') as HTMLElement).queryByRole("button")).toBeNull();
  });

  it("says in the engine's words why a decision did not go", async () => {
    serve("hr", {
      ...queuePage(),
      "/api/v1/leave/11/approve/": () => jsonResponse({ ok: false, error: "refused", message: "الطلب ده اتقرر فيه بالفعل." }, 409),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/leave");
    await screen.findByText("مستني قرار");
    await user.click(within(container.querySelector('[data-waiting="11"]') as HTMLElement).getByRole("button", { name: "وافق" }));
    expect(await screen.findByText("الطلب ده اتقرر فيه بالفعل.")).toBeInTheDocument();
  });

  it("draws the record with who decided and whether the days were written", async () => {
    serve("hr", queuePage());
    const { container } = open("/hr/leave");
    await screen.findByText("السجل");
    const done = container.querySelector('[data-record="13"]') as HTMLElement;
    expect(within(done).getByText("Hala")).toBeInTheDocument();
    expect(within(done).getByText("اتوافق عليه")).toHaveClass("badge--ok");
    expect(done.querySelector("svg")).not.toBeNull();
    const turned = container.querySelector('[data-record="14"]') as HTMLElement;
    expect(within(turned).getByText("مرفوض")).toHaveClass("badge--dead");
    expect(turned.querySelector("svg")).toBeNull();
  });

  it("filters through the address and forwards only the filters it knows", async () => {
    const served = serve("hr", queuePage());
    const user = userEvent.setup();
    open("/hr/leave?evil=1");
    await screen.findByText("السجل");
    expect(reads(served, "/api/v1/hr/leave/")[0]).toBe("/api/v1/hr/leave/");
    await user.selectOptions(screen.getByLabelText("الموظف"), "21");
    await user.selectOptions(screen.getByLabelText("الحالة"), "approved");
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("status=approved"));
    expect(screen.getByTestId("where")).toHaveTextContent("user=21");
    await waitFor(() => expect(reads(served, "/api/v1/hr/leave/").some((url) => url.includes("user=21") && url.includes("status=approved"))).toBe(true));
  });

  it("says when nothing waits and nothing is recorded", async () => {
    serve("hr", queuePage(queue({ waiting: [], rows: [] })));
    open("/hr/leave");
    expect(await screen.findByText("مفيش طلبات مستنية.")).toBeInTheDocument();
    expect(screen.getByText("مفيش سجلات.")).toBeInTheDocument();
  });

  it("is HR's and the admin's", async () => {
    for (const who of ["operation", "team_lead", "translator", "reviewer", "accounting", "sales"] as const) {
      const served = serve(who, queuePage());
      const view = open("/hr/leave");
      expect(await screen.findByText("home page"), who).toBeInTheDocument();
      expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/")), who).toBe(false);
      view.unmount();
    }
    serve("admin", queuePage());
    open("/hr/leave");
    expect(await screen.findByText("مستني قرار")).toBeInTheDocument();
  });
});
