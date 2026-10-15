import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { B2bLead, B2bSheetResponse } from "../api/b2b";
import type { Visit, VisitsResponse } from "../api/b2c";
import { Shell } from "../components/Shell";
import { ToastProvider } from "../components/Toasts";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { LeadSheetPage } from "./LeadSheetPage";
import { VisitsPage } from "./VisitsPage";

/**
 * B2C (15/10/2026): the B2C team's sheet (its columns, its stages, the reason a lost company needs, the visit button) and
 * the visits page (one reading of the place at each press, the report, the manager's decision). Every rule is the
 * server's; what is held here is that the page asks for what the server needs and sends exactly that.
 */

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

const posted = (calls: { url: string; init?: RequestInit }[], url: string) =>
  calls.filter((call) => call.url === url && call.init?.method === "POST").map((call) => JSON.parse(String(call.init?.body)));

function lead(over: Partial<B2bLead> = {}): B2bLead {
  return {
    id: 5, company_name: "Nile Trading", country: "", website: "", industry: "", contact_person: "Mona", position: "", email: "",
    phone: "01001234567", whatsapp: "", linkedin: "", languages: "", services: "", source: "", governorate: "Cairo",
    address: "Zamalek", location: "30.0459, 31.2243", map_link: "https://www.google.com/maps?q=30.045900,31.224300",
    customer_type: "", lost_reason: "", status: "new", priority: "", deal_value: "", phones: ["01001234567"], next_follow_up: "",
    notes: [], client_code: "", whatsapp_at: "", email_at: "", call_at: "", last_contact_at: "", replied_at: "",
    last_outreach_at: "", follow_up: "", overdue: false, quote: null, ...over,
  };
}

function sheet(over: Partial<B2bSheetResponse["sheet"]> = {}): B2bSheetResponse {
  return {
    ok: true,
    sheet: {
      id: 3, title: "Cairo", note: "", assigned_to: { id: 7, name: "Walker" }, created_by: null, created_at: "", rows: 1,
      contacted: 0, can_manage: false, can_contact: true, last_sent: null, market: "b2c", can_visit: true, ...over,
    },
    sales: [],
    sheets: [],
    leads: [lead()],
    columns: [{ name: "company_name", ar: "اسم الشركة", en: "Company name", max: 160 }],
    statuses: ["new", "contacted", "requirement", "quoted", "waiting", "negotiation", "won", "lost", "later"].map((value) => ({ value, label: value })),
    priorities: [{ value: "high", label: "High" }],
    outcomes: [],
    lost_reasons: [
      { value: "price", label: "Price" },
      { value: "other", label: "Other" },
    ],
    customer_types: [],
  };
}

function serve(routes: Record<string, (url: URL, init?: RequestInit) => Response>, who: Record<string, unknown> = {}) {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role: "sales", sales_track: "b2c_field", ...who })),
    ...routes,
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function open(route: string) {
  return renderWithProviders(
    <ToastProvider>
      <Routes>
        <Route path="/leads/:id" element={<LeadSheetPage />} />
        <Route path="/b2c/visits" element={<VisitsPage />} />
        <Route path="/" element={<div>home page</div>} />
      </Routes>
    </ToastProvider>,
    { route },
  );
}

describe("the B2C sheet", () => {
  it("draws the B2C columns and stages", async () => {
    serve({ "/api/v1/b2b/sheets/3/": () => jsonResponse(sheet()) });
    open("/leads/3");
    expect(await screen.findByText("المحافظة")).toBeInTheDocument();
    expect(screen.getByText("اللوكيشن")).toBeInTheDocument();
    expect(screen.queryByText("الدوله")).toBeNull();
    const stage = screen.getByLabelText("الحالة · Nile Trading");
    expect(within(stage).getByRole("option", { name: "تفاوض" })).toBeInTheDocument();
    expect(within(stage).getByRole("option", { name: "خسرناه" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "على الخريطة · Nile Trading" })).toHaveAttribute("href", "https://www.google.com/maps?q=30.045900,31.224300");
  });

  it("asks why a company was lost before it saves, and sends the reason with the stage", async () => {
    const user = userEvent.setup();
    const mocked = serve({
      "/api/v1/b2b/leads/5/save/": () => jsonResponse({ ok: true, lead: lead({ status: "lost", lost_reason: "price" }) }),
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheet()),
    });
    open("/leads/3");
    await user.selectOptions(await screen.findByLabelText("الحالة · Nile Trading"), "lost");
    // Nothing is saved by the cell itself: the window asks first.
    expect(posted(mocked.calls, "/api/v1/b2b/leads/5/save/")).toEqual([]);
    await user.click(screen.getByRole("button", { name: "احفظ" }));
    expect(await screen.findByText("اختار سبب الخسارة.")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("سبب الخسارة"), "price");
    await user.click(screen.getByRole("button", { name: "احفظ" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/leads/5/save/")).toEqual([{ status: "lost", lost_reason: "price" }]));
  });

  it("asks the day of the next follow-up for «Follow-up later»", async () => {
    const user = userEvent.setup();
    const mocked = serve({
      "/api/v1/b2b/leads/5/save/": () => jsonResponse({ ok: true, lead: lead({ status: "later", next_follow_up: "2026-11-02" }) }),
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheet()),
    });
    open("/leads/3");
    await user.selectOptions(await screen.findByLabelText("الحالة · Nile Trading"), "later");
    await user.type(screen.getByLabelText("المتابعة الجاية"), "2026-11-02");
    await user.click(screen.getByRole("button", { name: "احفظ" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/leads/5/save/")).toEqual([{ status: "later", next_follow_up: "2026-11-02" }]));
  });

  it("plans a visit from the company's row, and a B2B sheet has no visit button", async () => {
    const user = userEvent.setup();
    const mocked = serve({
      "/api/v1/b2c/visits/new/": () => jsonResponse({ ok: true, visit: { id: 1, code: "VIS-0001" } }),
      "/api/v1/b2c/visits/": () => jsonResponse(visitsAnswer()),
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheet()),
    });
    open("/leads/3");
    await user.click(await screen.findByRole("button", { name: "زيارة · Nile Trading" }));
    await user.type(screen.getByLabelText("الغرض من الزيارة"), "Intro");
    await user.click(screen.getByRole("button", { name: "اعمل الزيارة" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2c/visits/new/")).toEqual([{ lead: 5, purpose: "Intro", planned_at: "" }]));
  });

  it("draws no visit button where the server says none", async () => {
    serve({ "/api/v1/b2b/sheets/3/": () => jsonResponse(sheet({ can_visit: false })) });
    open("/leads/3");
    await screen.findByLabelText("الحالة · Nile Trading");
    expect(screen.queryByRole("button", { name: "زيارة · Nile Trading" })).toBeNull();
  });
});

function visit(over: Partial<Visit> = {}): Visit {
  return {
    id: 11, code: "VIS-0011", status: "planned",
    lead: { id: 5, company_name: "Nile Trading", governorate: "Cairo", address: "Zamalek", sheet: 3, has_place: true, map_link: "" },
    person: { id: 7, name: "Walker" }, planned_at: "", planned_day: "", purpose: "Intro", check_in_at: "", check_in_distance: null,
    check_in_accuracy: null, check_in_map: "", check_out_at: "", check_out_distance: null, check_out_accuracy: null, check_out_map: "",
    minutes: null, no_location_reason: "", outcome: "", met: "", interest: "", summary: "", next_step: "", next_step_on: "", flags: [],
    escalated: false, escalation_note: "", decided_by: null, decided_at: "", decision_note: "", mine: true, can_decide: false,
    can_escalate: false, appeal_note: "", appealed_from: "", appealed_at: "", can_appeal: false, ...over,
  };
}

function visitsAnswer(visits: Visit[] = [visit()], over: Partial<VisitsResponse> = {}): VisitsResponse {
  return {
    ok: true, month: "2026-10", can_manage: false, field: true,
    rules: { target: 220, work_days: 22, radius_m: 100, accuracy_m: 100 },
    board: [{
      person: { id: 7, name: "Walker", active: true }, target: 180, leave_days: 4, planned: 1, open: 0, pending: 0, verified: 9,
      rejected: 1, submitted: 10, remaining: 171, achievement: 5, verification_rate: 90,
    }],
    visits,
    outcomes: [{ value: "interested", label: "Interested" }],
    interests: [{ value: "high", label: "High" }],
    flags: [{ value: "far", ar: "المكان بعيد عن الشركة", en: "Away from the company" }],
    ...over,
  };
}

/** The phone's place at a press: a fix, or none (refused or unavailable). Counts how often it was asked. */
function phone(answer: "fix" | "none") {
  const getCurrentPosition = vi.fn((ok: PositionCallback, fail: PositionErrorCallback) => {
    if (answer === "fix") ok({ coords: { latitude: 30.0459, longitude: 31.2248, accuracy: 12 } } as GeolocationPosition);
    else fail({ code: 1 } as GeolocationPositionError);
  });
  const watchPosition = vi.fn();
  vi.stubGlobal("navigator", { ...navigator, geolocation: { getCurrentPosition, watchPosition } });
  return { getCurrentPosition, watchPosition };
}

describe("the visits page", () => {
  it("shows the target with what each rate is made of", async () => {
    serve({ "/api/v1/b2c/visits/": () => jsonResponse(visitsAnswer()) });
    open("/b2c/visits");
    const row = await screen.findByText("Walker", { selector: "td" });
    const cells = within(row.closest("tr") as HTMLElement);
    expect(cells.getByText("(4 يوم إجازة)")).toBeInTheDocument();
    expect(cells.getByText("(9/10)")).toBeInTheDocument();
  });

  it("reads the place once at «وصلت» and sends it, and never follows the person", async () => {
    const user = userEvent.setup();
    const geo = phone("fix");
    const mocked = serve({
      "/api/v1/b2c/visits/11/check-in/": () => jsonResponse({ ok: true, visit: visit({ status: "checked_in", check_in_distance: 40 }) }),
      "/api/v1/b2c/visits/": () => jsonResponse(visitsAnswer()),
    });
    open("/b2c/visits");
    await user.click(await screen.findByRole("button", { name: "وصلت" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2c/visits/11/check-in/")).toEqual([{ lat: 30.0459, lng: 31.2248, accuracy: 12 }]));
    expect(geo.getCurrentPosition).toHaveBeenCalledTimes(1);
    expect(geo.watchPosition).not.toHaveBeenCalled();
    expect(await screen.findByText("اتسجّل وصولك: على بُعد 40 متر من الشركة")).toBeInTheDocument();
  });

  it("asks why when the phone gives no place, and sends the reason instead", async () => {
    const user = userEvent.setup();
    phone("none");
    const mocked = serve({
      "/api/v1/b2c/visits/11/check-in/": () => jsonResponse({ ok: true, visit: visit({ status: "checked_in" }) }),
      "/api/v1/b2c/visits/": () => jsonResponse(visitsAnswer()),
    });
    open("/b2c/visits");
    await user.click(await screen.findByRole("button", { name: "وصلت" }));
    await user.type(await screen.findByLabelText("السبب"), "GPS broken");
    await user.click(screen.getByRole("button", { name: "ابعت من غير لوكيشن" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2c/visits/11/check-in/")).toEqual([{ reason: "GPS broken" }]));
  });

  it("needs the outcome and the summary before «خلصت» reads the place", async () => {
    const user = userEvent.setup();
    const geo = phone("fix");
    const mocked = serve({
      "/api/v1/b2c/visits/11/check-out/": () => jsonResponse({ ok: true, visit: visit({ status: "pending" }) }),
      "/api/v1/b2c/visits/": () => jsonResponse(visitsAnswer([visit({ status: "checked_in", check_in_at: "15/10/2026 10:00 AM" })])),
    });
    open("/b2c/visits");
    // The banner of the open visit and the visit's own card both say it.
    await user.click((await screen.findAllByRole("button", { name: "خلصت" }))[0]!);
    await user.click(screen.getByRole("button", { name: "خلصت، ابعتها" }));
    expect(await screen.findByText("اختار النتيجة واكتب ملخص المقابلة.")).toBeInTheDocument();
    expect(geo.getCurrentPosition).not.toHaveBeenCalled();
    await user.selectOptions(screen.getByLabelText("نتيجة الزيارة"), "interested");
    await user.type(screen.getByLabelText("ملخص المقابلة"), "Met the manager");
    await user.click(screen.getByRole("button", { name: "خلصت، ابعتها" }));
    await waitFor(() =>
      expect(posted(mocked.calls, "/api/v1/b2c/visits/11/check-out/")).toEqual([
        { lat: 30.0459, lng: 31.2248, accuracy: 12, outcome: "interested", met: "", interest: "", summary: "Met the manager", next_step: "", next_step_on: "" },
      ]),
    );
  });

  it("lets the manager turn a visit down only with the reason, and verify the clean ones in one go", async () => {
    const user = userEvent.setup();
    const waiting = [
      visit({ id: 21, code: "VIS-0021", status: "pending", mine: false, can_decide: true, can_escalate: true }),
      visit({ id: 22, code: "VIS-0022", status: "pending", mine: false, can_decide: true, can_escalate: true, flags: ["far"] }),
    ];
    const mocked = serve(
      {
        "/api/v1/b2c/visits/verify-clean/": () => jsonResponse({ ok: true, verified: 1 }),
        "/api/v1/b2c/visits/22/decide/": () => jsonResponse({ ok: true, visit: waiting[1] }),
        "/api/v1/b2c/visits/": () => jsonResponse(visitsAnswer(waiting, { can_manage: true, field: false })),
      },
      { sales_track: "b2c_online", sales_manager: true },
    );
    open("/b2c/visits");
    expect(await screen.findByText("المكان بعيد عن الشركة")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "اعتمد السليمة (1)" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2c/visits/verify-clean/")).toEqual([{ ids: [21] }]));
    const card = within(document.querySelector('[data-visit="22"]') as HTMLElement);
    await user.click(card.getByRole("button", { name: "ارفض" }));
    await user.click(screen.getByRole("button", { name: "ارفض الزيارة" }));
    expect(await screen.findByText("اكتب السبب.")).toBeInTheDocument();
    await user.type(screen.getByLabelText("سبب الرفض"), "Not the company");
    await user.click(screen.getByRole("button", { name: "ارفض الزيارة" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2c/visits/22/decide/")).toEqual([{ verified: false, note: "Not the company" }]));
  });

  it("lets the person object to a turned-down visit, once, with why", async () => {
    const user = userEvent.setup();
    const turned = visit({ status: "rejected", decision_note: "Not the company", can_appeal: true });
    const mocked = serve({
      "/api/v1/b2c/visits/11/appeal/": () => jsonResponse({ ok: true, visit: { ...turned, status: "pending", can_appeal: false } }),
      "/api/v1/b2c/visits/": () => jsonResponse(visitsAnswer([turned])),
    });
    open("/b2c/visits");
    await user.click(await screen.findByRole("button", { name: "اعترض" }));
    await user.click(screen.getByRole("button", { name: "ابعت الاعتراض" }));
    expect(await screen.findByText("اكتب سبب اعتراضك.")).toBeInTheDocument();
    await user.type(screen.getByLabelText("سبب اعتراضك"), "I was there");
    await user.click(screen.getByRole("button", { name: "ابعت الاعتراض" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2c/visits/11/appeal/")).toEqual([{ note: "I was there" }]));
  });

  it("offers no objection where the server says none", async () => {
    serve({ "/api/v1/b2c/visits/": () => jsonResponse(visitsAnswer([visit({ status: "rejected", can_appeal: false, appeal_note: "Once", appealed_from: "No" })])) });
    open("/b2c/visits");
    expect(await screen.findByText(/Once/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "اعترض" })).toBeNull();
  });

  it("sends an online Sales person home", async () => {
    serve({ "/api/v1/b2c/visits/": () => jsonResponse(visitsAnswer()) }, { sales_track: "b2c_online" });
    open("/b2c/visits");
    expect(await screen.findByText("home page")).toBeInTheDocument();
  });
});

describe("the B2C Sales menu", () => {
  const at = (track: string, manager = false) => {
    const mocked = mockFetch({
      "/api/prefs/": () => jsonResponse({ ok: true }),
      "/api/v1/me/": () => jsonResponse(me({ role: "sales", sales_track: track as never, sales_manager: manager }, 0, ["sales", "chats"] as never)),
    });
    vi.stubGlobal("fetch", mocked.fn);
    return renderWithProviders(
      <Routes>
        <Route element={<Shell />}>
          <Route path="inbox" element={<div>mailbox</div>} />
        </Route>
      </Routes>,
      { route: "/inbox" },
    );
  };
  const links = (container: HTMLElement) => Array.from(container.querySelectorAll(".sidebar .nav__item")).map((a) => a.getAttribute("href"));

  it("gives a field person the B2C sheets and the visits, not the B2B sheets", async () => {
    const view = at("b2c_field");
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/b2c/visits"]')).not.toBeNull());
    expect(links(view.container)).toContain("/b2c");
    expect(links(view.container)).not.toContain("/leads");
    // Their numbers are the B2C page's, not the B2B one's.
    expect(links(view.container)).toContain("/b2c/performance");
    expect(links(view.container)).not.toContain("/sales-performance");
  });

  it("keeps a B2B person on the B2B sheets", async () => {
    const view = at("b2b");
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/leads"]')).not.toBeNull());
    expect(links(view.container)).not.toContain("/b2c");
    expect(links(view.container)).not.toContain("/b2c/visits");
  });

  it("gives an online person the B2C sheets only, and their manager the visits too", async () => {
    let view = at("b2c_online");
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/b2c"]')).not.toBeNull());
    expect(links(view.container)).not.toContain("/b2c/visits");
    view.unmount();
    view = at("b2c_online", true);
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/b2c/visits"]')).not.toBeNull());
  });
});
