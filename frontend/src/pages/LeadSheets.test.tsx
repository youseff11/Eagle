import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { type B2bFollowUpsResponse, type B2bLead, type B2bSheetResponse, type B2bSheetsResponse } from "../api/b2b";
import type { Role } from "../api/types";
import { ToastProvider } from "../components/Toasts";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { LeadSheetPage } from "./LeadSheetPage";
import { LeadSheetsPage } from "./LeadSheetsPage";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

const COLUMNS: B2bSheetResponse["columns"] = [
  { name: "company_name", ar: "اسم الشركة", en: "Company name", max: 160 },
  { name: "country", ar: "الدولة", en: "Country", max: 80 },
  { name: "website", ar: "الموقع", en: "Website", max: 250 },
  { name: "industry", ar: "نوع الشركة", en: "Industry / type", max: 120 },
  { name: "contact_person", ar: "الشخص المسؤول", en: "Contact person", max: 160 },
  { name: "position", ar: "المنصب", en: "Position", max: 120 },
  { name: "email", ar: "الإيميل", en: "Email", max: 254 },
  { name: "phone", ar: "التليفون", en: "Phone", max: 250 },
  { name: "whatsapp", ar: "واتساب", en: "WhatsApp", max: 40 },
  { name: "linkedin", ar: "لينكدإن", en: "LinkedIn", max: 250 },
  { name: "languages", ar: "اللغات", en: "Language pairs", max: 250 },
  { name: "services", ar: "الخدمات المطلوبة", en: "Services required", max: 250 },
  { name: "source", ar: "المصدر", en: "Source", max: 120 },
];

function lead(over: Partial<B2bLead> = {}): B2bLead {
  return {
    id: 5,
    company_name: "Lingua GmbH",
    country: "Germany",
    website: "",
    industry: "Agency",
    contact_person: "Anna Schmidt",
    position: "PM",
    email: "anna@lingua.test",
    phone: "+49 30 1234",
    whatsapp: "+49 151 0000",
    linkedin: "",
    languages: "DE>AR",
    services: "",
    source: "",
    status: "new",
    priority: "",
    deal_value: "",
    phones: ["+49 151 0000", "+49 30 1234"],
    next_follow_up: "",
    notes: [],
    client_code: "",
    whatsapp_at: "",
    email_at: "",
    call_at: "",
    call_outcome: "",
    reached: false,
    last_contact_at: "",
    replied_at: "",
    last_outreach_at: "",
    follow_up: "",
    overdue: false,
    quote: null,
    governorate: "",
    address: "",
    location: "",
    map_link: "",
    customer_type: "",
    lost_reason: "",
    ...over,
  };
}

function sheetAnswer(over: Partial<B2bSheetResponse["sheet"]> = {}, leads: B2bLead[] = [lead()]): B2bSheetResponse {
  return {
    ok: true,
    sheet: {
      id: 3,
      title: "Germany",
      note: "",
      assigned_to: { id: 7, name: "Seller" },
      created_by: { id: 2, name: "Manager" },
      created_at: "10/10/2026 9:00 AM",
      rows: leads.length,
      contacted: 0,
      can_manage: false,
      can_contact: true,
      last_sent: null,
      market: "b2b",
      can_visit: false,
      ...over,
    },
    sales: [],
    sheets: [],
    leads,
    columns: COLUMNS,
    statuses: [
      { value: "new", label: "New client" },
      { value: "contacted", label: "Contacted" },
      { value: "won", label: "Contracted" },
    ],
    priorities: [
      { value: "high", label: "High" },
      { value: "medium", label: "Medium" },
      { value: "low", label: "Low" },
    ],
    outcomes: [
      { value: "quotation", label: "Quotation requested" },
      { value: "contracted", label: "Contracted" },
      { value: "no_answer", label: "No answer" },
    ],
    lost_reasons: [
      { value: "price", label: "Price" },
      { value: "other", label: "Other" },
    ],
    customer_types: [
      { value: "company", label: "Company" },
      { value: "individual", label: "Individual" },
    ],
  };
}

function serve(who: Role, routes: Record<string, (url: URL, init?: RequestInit) => Response | Promise<Response>>) {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role: who, is_admin: who === "admin", name: "Seller" })),
    ...routes,
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function open(route: string) {
  return renderWithProviders(
    <ToastProvider>
      <Routes>
        <Route path="/leads" element={<LeadSheetsPage />} />
        <Route path="/leads/:id" element={<LeadSheetPage />} />
        <Route path="/chats/:code" element={<div>chat page</div>} />
        <Route path="/" element={<div>home page</div>} />
      </Routes>
    </ToastProvider>,
    { route },
  );
}

const posted = (calls: { url: string; init?: RequestInit }[], url: string) =>
  calls.filter((call) => call.url === url && call.init?.method === "POST").map((call) => JSON.parse(String(call.init?.body)));

const noFollowUps: B2bFollowUpsResponse = { ok: true, today: "2026-10-10", items: [] };

describe("LeadSheetsPage", () => {
  const list = (over: Partial<B2bSheetsResponse> = {}): B2bSheetsResponse => ({
    ok: true,
    market: "b2b",
    can_manage: false,
    sales: [],
    sheets: [{ ...sheetAnswer().sheet, rows: 4, contacted: 1 }],
    ...over,
  });

  it("shows a Sales person their sheets, with no box to make one", async () => {
    serve("sales", { "/api/v1/b2b/follow-ups/": () => jsonResponse(noFollowUps), "/api/v1/b2b/sheets/": () => jsonResponse(list()) });
    open("/leads");
    expect(await screen.findByText("Germany")).toBeInTheDocument();
    expect(screen.getByText("1 / 4")).toBeInTheDocument();
    expect(screen.queryByText("شيت جديد")).toBeNull();
  });

  it("lets the manager make a sheet for a Sales person and opens it", async () => {
    const user = userEvent.setup();
    const mocked = serve("sales", {
      "/api/v1/b2b/sheets/new/": () => jsonResponse({ ok: true, sheet: { ...sheetAnswer().sheet, id: 9 } }),
      "/api/v1/b2b/sheets/9/": () => jsonResponse(sheetAnswer({ id: 9 })),
      "/api/v1/b2b/follow-ups/": () => jsonResponse(noFollowUps),
      "/api/v1/b2b/sheets/": () => jsonResponse(list({ can_manage: true, sales: [{ id: 7, name: "Seller" }] })),
    });
    open("/leads");
    await user.type(await screen.findByLabelText("اسم الشيت"), "France");
    await user.selectOptions(screen.getByLabelText("الـSales اللي هياخده"), "7");
    await user.click(screen.getByRole("button", { name: "اعمل الشيت" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/sheets/new/")).toEqual([{ title: "France", note: "", assigned_to: 7, market: "b2b" }]));
  });

  it("puts the day's follow-ups on top, late ones marked, and the team's with whose they are for the manager", async () => {
    const due: B2bFollowUpsResponse = {
      ok: true,
      today: "2026-10-10",
      items: [
        { ...lead({ id: 5, next_follow_up: "2026-10-08", follow_up: "overdue", overdue: true }), sheet: { id: 3, title: "Germany" }, sales: { id: 7, name: "Seller" } },
        { ...lead({ id: 6, company_name: "Beta", next_follow_up: "2026-10-10", follow_up: "today" }), sheet: { id: 3, title: "Germany" }, sales: { id: 7, name: "Seller" } },
      ],
    };
    serve("sales", { "/api/v1/b2b/follow-ups/": () => jsonResponse(due), "/api/v1/b2b/sheets/": () => jsonResponse(list({ can_manage: true })) });
    const { container } = open("/leads");
    expect(await screen.findByText("متابعات الفريق النهارده والمتأخرة")).toBeInTheDocument();
    const late = container.querySelector('[data-follow-up-row="5"]') as HTMLElement;
    expect(within(late).getAllByText("متأخرة").length).toBeGreaterThan(0);
    expect(within(late).getByText("Seller")).toBeInTheDocument();
    expect(within(container.querySelector('[data-follow-up-row="6"]') as HTMLElement).getByText("النهارده")).toBeInTheDocument();
    expect(screen.getByText("1 متأخرة")).toBeInTheDocument();
  });

  it("draws no follow-up box when there is none due", async () => {
    serve("sales", { "/api/v1/b2b/follow-ups/": () => jsonResponse(noFollowUps), "/api/v1/b2b/sheets/": () => jsonResponse(list()) });
    open("/leads");
    await screen.findByText("Germany");
    expect(screen.queryByText("متابعاتك النهارده والمتأخرة")).toBeNull();
  });

  it("lets the manager delete a sheet from the list, after asking", async () => {
    const user = userEvent.setup();
    let gone = false;
    const mocked = serve("sales", {
      "/api/v1/b2b/sheets/3/delete/": () => {
        gone = true;
        return jsonResponse({ ok: true });
      },
      "/api/v1/b2b/follow-ups/": () => jsonResponse(noFollowUps),
      "/api/v1/b2b/sheets/": () =>
        jsonResponse(list({ can_manage: true, sheets: gone ? [] : [{ ...sheetAnswer().sheet, rows: 2, contacted: 0 }] })),
    });
    open("/leads");
    await user.click(await screen.findByRole("button", { name: "امسح الشيت Germany" }));
    expect(screen.getByText(/الـ2 شركة اللي فيه هيتمسحوا ومفيش رجوع/)).toBeInTheDocument();
    expect(posted(mocked.calls, "/api/v1/b2b/sheets/3/delete/")).toEqual([]);
    await user.click(screen.getByRole("button", { name: "امسح" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/sheets/3/delete/")).toEqual([{}]));
    await waitFor(() => expect(screen.queryByText("Germany")).toBeNull());
  });

  it("asks nothing when cancelled, and cannot delete a sheet with a contacted company", async () => {
    const user = userEvent.setup();
    const mocked = serve("sales", {
      "/api/v1/b2b/follow-ups/": () => jsonResponse(noFollowUps),
      "/api/v1/b2b/sheets/": () =>
        jsonResponse(list({ can_manage: true, sheets: [{ ...sheetAnswer().sheet, rows: 2, contacted: 0 }, { ...sheetAnswer().sheet, id: 4, title: "Spain", rows: 1, contacted: 1 }] })),
    });
    open("/leads");
    expect(await screen.findByRole("button", { name: "امسح الشيت Spain" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "امسح الشيت Germany" }));
    await user.click(screen.getByRole("button", { name: "إلغاء" }));
    expect(screen.queryByText(/ومفيش رجوع/)).toBeNull();
    expect(mocked.calls.some((call) => call.url.endsWith("/delete/"))).toBe(false);
  });

  it("shows the server's refusal and keeps the question open", async () => {
    const user = userEvent.setup();
    serve("sales", {
      "/api/v1/b2b/sheets/3/delete/": () =>
        jsonResponse({ ok: false, error: "contacted", message: "فيه شركات في الشيت ده اتواصلنا معاها، فمش هيتمسح.", message_en: "kept" }, 400),
      "/api/v1/b2b/follow-ups/": () => jsonResponse(noFollowUps),
      "/api/v1/b2b/sheets/": () => jsonResponse(list({ can_manage: true, sheets: [{ ...sheetAnswer().sheet, rows: 2, contacted: 0 }] })),
    });
    open("/leads");
    await user.click(await screen.findByRole("button", { name: "امسح الشيت Germany" }));
    await user.click(screen.getByRole("button", { name: "امسح" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("فيه شركات في الشيت ده اتواصلنا معاها");
  });

  it("gives a Sales person no delete button", async () => {
    serve("sales", { "/api/v1/b2b/follow-ups/": () => jsonResponse(noFollowUps), "/api/v1/b2b/sheets/": () => jsonResponse(list()) });
    open("/leads");
    await screen.findByText("Germany");
    expect(screen.queryByRole("button", { name: /امسح الشيت/ })).toBeNull();
  });

  it("sends anybody else home", async () => {
    const mocked = serve("operation", {});
    open("/leads");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(mocked.calls.some((call) => call.url.startsWith("/api/v1/b2b/"))).toBe(false);
  });
});

describe("LeadSheetPage", () => {
  it("puts a send and a call button beside the company for the sheet's own Sales person", async () => {
    serve("sales", { "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()) });
    open("/leads/3");
    const row = (await screen.findByDisplayValue("Lingua GmbH")).closest("tr") as HTMLElement;
    expect(within(row).getByRole("button", { name: "ابعت رسالة" })).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "سجّل مكالمة" })).toBeInTheDocument();
  });

  it("draws no contact button for the manager reading someone else's sheet, and says why", async () => {
    serve("sales", { "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer({ can_contact: false, can_manage: true })) });
    open("/leads/3");
    const row = (await screen.findByDisplayValue("Lingua GmbH")).closest("tr") as HTMLElement;
    expect(within(row).queryByRole("button", { name: "ابعت رسالة" })).toBeNull();
    expect(within(row).queryByRole("button", { name: "سجّل مكالمة" })).toBeNull();
    expect(screen.getByText(/التواصل من الشيت ده لصاحبه بس/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "إعدادات الشيت" })).toBeInTheDocument();
  });

  it("sends a written WhatsApp to the number chosen, and the row is marked by the server", async () => {
    const user = userEvent.setup();
    const mocked = serve("sales", {
      "/api/v1/b2b/leads/5/send/": () => jsonResponse({ ok: true, chat: "CL-0042", lead: lead({ whatsapp_at: "10/10/2026 1:00 PM" }) }),
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()),
    });
    open("/leads/3");
    await user.click(await screen.findByRole("button", { name: "ابعت رسالة" }));
    expect(screen.getByRole("radio", { name: "+49 151 0000" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "anna@lingua.test" })).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "+49 30 1234" }));
    await user.type(screen.getByLabelText("الرسالة"), "Here are our rates");
    await user.click(screen.getByRole("button", { name: "ابعت" }));
    await waitFor(() =>
      expect(posted(mocked.calls, "/api/v1/b2b/leads/5/send/")).toEqual([{ channel: "whatsapp", to: "+49 30 1234", subject: "", body: "Here are our rates" }]),
    );
    expect(await screen.findByText("الرسالة اتبعتت واتسجلت في الصف")).toBeInTheDocument();
  });

  it("offers the opening message when the number has not written in the last day, and then opens the chat", async () => {
    const user = userEvent.setup();
    const mocked = serve("sales", {
      "/api/v1/b2b/leads/5/send/": () => jsonResponse({ ok: false, error: "window_closed", message: "x", message_en: "x" }, 400),
      "/api/v1/b2b/leads/5/whatsapp/": () => jsonResponse({ ok: true, sent: true, chat: "CL-0042", lead: lead() }),
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()),
    });
    open("/leads/3");
    await user.click(await screen.findByRole("button", { name: "ابعت رسالة" }));
    await user.type(screen.getByLabelText("الرسالة"), "hello");
    await user.click(screen.getByRole("button", { name: "ابعت" }));
    expect(await screen.findByText(/ماكلّمكش في آخر 24 ساعة/)).toBeInTheDocument();
    expect(posted(mocked.calls, "/api/v1/b2b/leads/5/whatsapp/")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "ابعت الرسالة الافتتاحية" }));
    expect(await screen.findByText("chat page")).toBeInTheDocument();
    expect(posted(mocked.calls, "/api/v1/b2b/leads/5/whatsapp/")).toEqual([{ number: "+49 151 0000" }]);
  });

  it("sends an e-mail to the address with its subject", async () => {
    const user = userEvent.setup();
    const mocked = serve("sales", {
      "/api/v1/b2b/leads/5/send/": () => jsonResponse({ ok: true, chat: "CL-0042", lead: lead() }),
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()),
    });
    open("/leads/3");
    await user.click(await screen.findByRole("button", { name: "ابعت رسالة" }));
    await user.click(screen.getByRole("radio", { name: "anna@lingua.test" }));
    await user.clear(screen.getByLabelText("العنوان"));
    await user.type(screen.getByLabelText("العنوان"), "Rates");
    await user.click(screen.getByRole("button", { name: "ابعت" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/leads/5/send/")).toHaveLength(1));
    expect(posted(mocked.calls, "/api/v1/b2b/leads/5/send/")[0]).toMatchObject({ channel: "email", to: "anna@lingua.test", subject: "Rates" });
    expect(posted(mocked.calls, "/api/v1/b2b/leads/5/send/")[0].body).toContain("Dear Anna");
  });

  it("shows the server's reason when the send is refused, and stays", async () => {
    const user = userEvent.setup();
    serve("sales", {
      "/api/v1/b2b/leads/5/send/": () => jsonResponse({ ok: false, error: "no_line", message: "مفيش رقم واتساب متسجّل ليك.", message_en: "x" }, 400),
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()),
    });
    open("/leads/3");
    await user.click(await screen.findByRole("button", { name: "ابعت رسالة" }));
    await user.type(screen.getByLabelText("الرسالة"), "hello");
    await user.click(screen.getByRole("button", { name: "ابعت" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("مفيش رقم واتساب متسجّل ليك.");
    expect(screen.getByRole("button", { name: "ابعت الرسالة الافتتاحية" })).toBeInTheDocument();
  });

  it("marks what reached the company, with when", async () => {
    serve("sales", {
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer({}, [lead({ whatsapp_at: "10/10/2026 1:00 PM", last_contact_at: "10/10/2026 1:00 PM" })])),
    });
    open("/leads/3");
    const row = (await screen.findByDisplayValue("Lingua GmbH")).closest("tr") as HTMLElement;
    expect(within(row).getByText("10/10/2026 1:00 PM")).toBeInTheDocument();
    expect(row.querySelector(".chip--replied")).toHaveTextContent("واتساب");
    expect(within(row).getByRole("button", { name: "ابعت رسالة" })).toHaveClass("is-done");
    expect(within(row).getByRole("button", { name: "سجّل مكالمة" })).not.toHaveClass("is-done");
  });

  it("logs a call with its outcome", async () => {
    const user = userEvent.setup();
    const mocked = serve("sales", {
      "/api/v1/b2b/leads/5/call/": () => jsonResponse({ ok: true, lead: lead({ call_at: "10/10/2026 2:00 PM" }) }),
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()),
    });
    open("/leads/3");
    await user.click(await screen.findByRole("button", { name: "سجّل مكالمة" }));
    await user.click(screen.getByRole("button", { name: "سجّل" }));
    expect(screen.getByRole("alert")).toHaveTextContent("اختار نتيجة المكالمة.");
    await user.selectOptions(screen.getByLabelText("النتيجة"), "no_answer");
    await user.type(screen.getByLabelText("ملاحظات"), "busy");
    await user.click(screen.getByRole("button", { name: "سجّل" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/leads/5/call/")).toHaveLength(1));
    expect(posted(mocked.calls, "/api/v1/b2b/leads/5/call/")[0]).toMatchObject({ outcome: "no_answer", notes: "busy", duration_minutes: null });
  });

  // 19/10/2026: the outcome chosen in «سجّل مكالمة» showed only in the timeline, never on the sheet.
  it("shows the last call's outcome on the row, and offers «تم التعاقد»", async () => {
    const user = userEvent.setup();
    serve("sales", {
      "/api/v1/b2b/sheets/3/": () =>
        jsonResponse(sheetAnswer({}, [lead({ call_at: "10/10/2026 2:00 PM", call_outcome: "quotation", reached: true }), lead({ id: 6, company_name: "Silent Ltd" })])),
    });
    const { container } = open("/leads/3");
    await screen.findByDisplayValue("Lingua GmbH");
    expect(container.querySelector('[data-lead="5"] [data-call-outcome="quotation"]')).toHaveTextContent("آخر مكالمة: طلب عرض سعر");
    expect(container.querySelector('[data-lead="6"] [data-call-outcome]')).toBeNull();
    await user.click(within(container.querySelector('[data-lead="5"]') as HTMLElement).getByRole("button", { name: "سجّل مكالمة" }));
    expect(within(screen.getByLabelText("النتيجة")).getByRole("option", { name: "تم التعاقد" })).toHaveValue("contracted");
  });

  // 19/10/2026: a company called from the Sales person's own phone, its stage set to «call» by hand, is not «not contacted».
  it("leaves a row whose stage says we talked out of «لسه ماتواصلناش»", async () => {
    const user = userEvent.setup();
    serve("sales", {
      "/api/v1/b2b/sheets/3/": () =>
        jsonResponse(sheetAnswer({}, [lead({ status: "call", reached: true }), lead({ id: 6, company_name: "Silent Ltd" })])),
    });
    open("/leads/3");
    await screen.findByDisplayValue("Lingua GmbH");
    await user.selectOptions(screen.getByLabelText("اعرض"), "untouched");
    expect(screen.queryByDisplayValue("Lingua GmbH")).toBeNull();
    expect(screen.getByDisplayValue("Silent Ltd")).toBeInTheDocument();
  });

  it("zooms the sheet in and out, and keeps the size", async () => {
    const user = userEvent.setup();
    serve("sales", { "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()) });
    const { container, unmount } = open("/leads/3");
    await screen.findByDisplayValue("Lingua GmbH");
    const table = () => container.querySelector("table.sheet") as HTMLElement;
    expect(table().dataset.zoom).toBe("1");
    await user.click(screen.getByRole("button", { name: "كبّر" }));
    await user.click(screen.getByRole("button", { name: "كبّر" }));
    expect(table().dataset.zoom).toBe("1.25");
    expect(table().style.zoom).toBe("1.25");
    await user.click(screen.getByRole("button", { name: "صغّر" }));
    await user.click(screen.getByRole("button", { name: "صغّر" }));
    await user.click(screen.getByRole("button", { name: "صغّر" }));
    expect(table().dataset.zoom).toBe("0.9");
    unmount();
    const again = open("/leads/3");
    await screen.findByDisplayValue("Lingua GmbH");
    expect((again.container.querySelector("table.sheet") as HTMLElement).dataset.zoom).toBe("0.9");
    await user.click(screen.getByRole("button", { name: "رجّعه 100%" }));
    expect((again.container.querySelector("table.sheet") as HTMLElement).dataset.zoom).toBe("1");
  });

  // 20/10/2026: «فلتر بالناس المهتمة».
  it("shows only the companies whose last call was «مهتم» when asked", async () => {
    const user = userEvent.setup();
    serve("sales", {
      "/api/v1/b2b/sheets/3/": () =>
        jsonResponse(sheetAnswer({}, [
          lead({ call_outcome: "interested", reached: true }),
          lead({ id: 6, company_name: "Busy Ltd", call_outcome: "no_answer", reached: true }),
          lead({ id: 7, company_name: "Silent Ltd" }),
        ])),
    });
    open("/leads/3");
    await screen.findByDisplayValue("Lingua GmbH");
    await user.selectOptions(screen.getByLabelText("اعرض"), "interested");
    expect(screen.getByDisplayValue("Lingua GmbH")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("Busy Ltd")).toBeNull();
    expect(screen.queryByDisplayValue("Silent Ltd")).toBeNull();
  });

  // 20/10/2026: «زود فلتر تم التعاقد».
  it("shows only the companies at «تم التعاقد» when asked", async () => {
    const user = userEvent.setup();
    serve("sales", {
      "/api/v1/b2b/sheets/3/": () =>
        jsonResponse(sheetAnswer({}, [
          lead({ status: "won", reached: true }),
          lead({ id: 6, company_name: "Busy Ltd", status: "contacted", call_outcome: "contracted", reached: true }),
          lead({ id: 7, company_name: "Silent Ltd" }),
        ])),
    });
    open("/leads/3");
    await screen.findByDisplayValue("Lingua GmbH");
    await user.selectOptions(screen.getByLabelText("اعرض"), "won");
    expect(screen.getByDisplayValue("Lingua GmbH")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("Busy Ltd")).toBeNull();
    expect(screen.queryByDisplayValue("Silent Ltd")).toBeNull();
  });

  // 20/10/2026: a company written to before opens its chat from the row.
  it("opens the chat of a company written to before, for the sheet's Sales person", async () => {
    const user = userEvent.setup();
    serve("sales", {
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer({}, [lead({ client_code: "C-0042" }), lead({ id: 6, company_name: "Silent Ltd" })])),
    });
    const { container } = open("/leads/3");
    await screen.findByDisplayValue("Lingua GmbH");
    expect(within(container.querySelector('[data-lead="6"]') as HTMLElement).queryByRole("link", { name: /افتح الشات/ })).toBeNull();
    await user.click(screen.getByRole("link", { name: "افتح الشات · Lingua GmbH" }));
    expect(await screen.findByText("chat page")).toBeInTheDocument();
  });

  it("does not offer the chat to a manager who does not hold the sheet", async () => {
    serve("sales", { "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer({ can_contact: false, can_manage: true }, [lead({ client_code: "C-0042" })])) });
    open("/leads/3");
    await screen.findByDisplayValue("Lingua GmbH");
    expect(screen.queryByRole("link", { name: /افتح الشات/ })).toBeNull();
  });

  it("marks a company that answered, and shows only those when asked", async () => {
    const user = userEvent.setup();
    serve("sales", {
      "/api/v1/b2b/sheets/3/": () =>
        jsonResponse(sheetAnswer({}, [lead({ replied_at: "10/10/2026 3:00 PM" }), lead({ id: 6, company_name: "Silent Ltd" })])),
    });
    open("/leads/3");
    const row = (await screen.findByDisplayValue("Lingua GmbH")).closest("tr") as HTMLElement;
    expect(within(row).getByText("ردّوا")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Silent Ltd")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("اعرض"), "replied");
    expect(screen.queryByDisplayValue("Silent Ltd")).toBeNull();
    expect(screen.getByDisplayValue("Lingua GmbH")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("اعرض"), "untouched");
    expect(screen.getByDisplayValue("Silent Ltd")).toBeInTheDocument();
  });

  it("says where a row's follow-up stands", async () => {
    serve("sales", {
      "/api/v1/b2b/sheets/3/": () =>
        jsonResponse(sheetAnswer({}, [lead({ next_follow_up: "2026-10-01", follow_up: "overdue", overdue: true }), lead({ id: 6, company_name: "Done Ltd", next_follow_up: "2026-10-02", follow_up: "done" })])),
    });
    const { container } = open("/leads/3");
    await screen.findByDisplayValue("Lingua GmbH");
    expect(container.querySelector('[data-lead="5"] [data-follow-up="overdue"]')).toHaveTextContent("متأخرة");
    expect(container.querySelector('[data-lead="6"] [data-follow-up="done"]')).toHaveTextContent("اتعملت");
  });

  it("lets the manager move a company to another Sales person's sheet", async () => {
    const user = userEvent.setup();
    const mocked = serve("sales", {
      "/api/v1/b2b/leads/5/move/": () => jsonResponse({ ok: true, lead: lead() }),
      "/api/v1/b2b/sheets/3/": () =>
        jsonResponse({ ...sheetAnswer({ can_manage: true, can_contact: false }), sheets: [{ id: 4, title: "Spain", assigned_to: { id: 8, name: "Other" } }] }),
    });
    open("/leads/3");
    await user.click(await screen.findByRole("button", { name: "تعديل" }));
    await user.selectOptions(screen.getByLabelText("انقلها لشيت تاني"), "4");
    await user.click(screen.getByRole("button", { name: "انقل" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/leads/5/move/")).toEqual([{ sheet: 4 }]));
  });

  it("offers no move to a Sales person (the server sends them no other sheets)", async () => {
    const user = userEvent.setup();
    serve("sales", { "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()) });
    open("/leads/3");
    await user.click(await screen.findByRole("button", { name: "تعديل" }));
    expect(screen.queryByLabelText("انقلها لشيت تاني")).toBeNull();
  });

  it("draws the team's sheet: its columns in its order, the band under the header, the cells as written", async () => {
    serve("sales", {
      "/api/v1/b2b/sheets/3/": () =>
        jsonResponse(
          sheetAnswer({}, [
            lead({
              status: "contacted", priority: "medium", deal_value: "1500", industry: "Tourism", country: "الكويت",
              notes: [{ id: 1, text: "call back", at: "10/10/2026 1:00 PM", day: "10/10/2026", by: { id: 7, name: "Seller" } }],
            }),
          ]),
        ),
    });
    const { container } = open("/leads/3");
    const row = (await screen.findByDisplayValue("Lingua GmbH")).closest("tr") as HTMLElement;
    const heads = [...container.querySelectorAll(".sheet thead tr:first-child th")].map((th) => th.textContent);
    expect(heads).toEqual(["الشركة", "الشخص المسؤول", "رقم الهاتف", "واتساب", "البريد الإلكتروني", "الحالة", "الأولوية", "قيمة الصفقة", "النشاط", "ملاحظات", "الدوله", "التواصل"]);
    expect(container.querySelector(".sheet .sheet__band")).not.toBeNull();
    expect(within(row).getByLabelText("الحالة · Lingua GmbH")).toHaveValue("contacted");
    expect(within(row).getByRole("option", { name: "تم التواصل" })).toBeInTheDocument();
    expect(within(row).getByLabelText("الأولوية · Lingua GmbH")).toHaveValue("medium");
    expect(within(row).getByLabelText("قيمة الصفقة · Lingua GmbH")).toHaveValue("1500");
    expect(row.querySelector('[data-note="1"]')).toHaveTextContent("10/10/2026");
    expect(row.querySelector('[data-note="1"]')).toHaveTextContent("call back");
    expect(within(row).getByLabelText("واتساب · Lingua GmbH")).toHaveValue("+49 151 0000");
    expect(within(row).getByLabelText("الدوله · Lingua GmbH")).toHaveValue("الكويت");
  });

  it("saves a typed cell alone when the cursor leaves it, and nothing when it did not change", async () => {
    const user = userEvent.setup();
    const mocked = serve("sales", {
      "/api/v1/b2b/leads/5/save/": () => jsonResponse({ ok: true, lead: lead({ contact_person: "Anna Weber" }) }),
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()),
    });
    open("/leads/3");
    const person = await screen.findByLabelText("الشخص المسؤول · Lingua GmbH");
    await user.click(person);
    await user.tab();
    expect(posted(mocked.calls, "/api/v1/b2b/leads/5/save/")).toEqual([]);
    await user.clear(person);
    await user.type(person, "Anna Weber{Enter}");
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/leads/5/save/")).toEqual([{ contact_person: "Anna Weber" }]));
  });

  it("puts a cell back on Escape and sends nothing", async () => {
    const user = userEvent.setup();
    const mocked = serve("sales", { "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()) });
    open("/leads/3");
    const phone = await screen.findByLabelText("رقم الهاتف · Lingua GmbH");
    await user.clear(phone);
    await user.type(phone, "123{Escape}");
    expect(phone).toHaveValue("+49 30 1234");
    expect(posted(mocked.calls, "/api/v1/b2b/leads/5/save/")).toEqual([]);
  });

  it("saves the status and the priority as soon as they are picked", async () => {
    const user = userEvent.setup();
    const mocked = serve("sales", {
      "/api/v1/b2b/leads/5/save/": () => jsonResponse({ ok: true, lead: lead() }),
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()),
    });
    open("/leads/3");
    await user.selectOptions(await screen.findByLabelText("الحالة · Lingua GmbH"), "won");
    await user.selectOptions(screen.getByLabelText("الأولوية · Lingua GmbH"), "high");
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/leads/5/save/")).toEqual([{ status: "won" }, { priority: "high" }]));
  });

  it("puts a refused cell back and says why", async () => {
    const user = userEvent.setup();
    serve("sales", {
      "/api/v1/b2b/leads/5/save/": () => jsonResponse({ ok: false, error: "no_company", message: "اكتب اسم الشركة.", message_en: "x" }, 400),
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()),
    });
    open("/leads/3");
    const company = await screen.findByLabelText("الشركة · Lingua GmbH");
    await user.clear(company);
    await user.type(company, "x{Enter}");
    expect(await screen.findByText("اكتب اسم الشركة.")).toBeInTheDocument();
    await waitFor(() => expect(company).toHaveValue("Lingua GmbH"));
  });

  it("takes Enter as a new line in the phone and WhatsApp numbers, and saves the lines when the cursor leaves", async () => {
    const user = userEvent.setup();
    const mocked = serve("sales", {
      "/api/v1/b2b/leads/5/save/": () => jsonResponse({ ok: true, lead: lead() }),
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()),
    });
    open("/leads/3");
    const whatsapp = await screen.findByLabelText("واتساب · Lingua GmbH");
    await user.type(whatsapp, "{Enter}{Enter}+49 151 2222 ");
    expect(posted(mocked.calls, "/api/v1/b2b/leads/5/save/")).toEqual([]);
    await user.tab();
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/leads/5/save/")).toEqual([{ whatsapp: "+49 151 0000\n+49 151 2222" }]));
  });

  it("adds a note on Enter, dated by the server, and keeps the ones before", async () => {
    const user = userEvent.setup();
    const before = { id: 1, text: "first call", at: "10/10/2026 1:00 PM", day: "10/10/2026", by: { id: 7, name: "Seller" } };
    const added = { id: 2, text: "sent the rate sheet", at: "13/10/2026 2:00 PM", day: "13/10/2026", by: { id: 7, name: "Seller" } };
    // The door answers with the row and every note on it, as the server does.
    const mocked = serve("sales", {
      "/api/v1/b2b/leads/5/notes/": () => jsonResponse({ ok: true, lead: lead({ notes: [before, added] }) }),
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer({}, [lead({ notes: [before] })])),
    });
    const { container } = open("/leads/3");
    const input = await screen.findByLabelText("ملاحظات · Lingua GmbH");
    await user.type(input, "   {Enter}");
    expect(posted(mocked.calls, "/api/v1/b2b/leads/5/notes/")).toEqual([]);
    await user.type(input, "sent the rate sheet{Enter}");
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/leads/5/notes/")).toEqual([{ text: "sent the rate sheet" }]));
    await waitFor(() => expect(input).toHaveValue(""));
    expect(container.querySelector('[data-note="1"]')).toHaveTextContent("first call");
    await waitFor(() => expect(container.querySelector('[data-note="2"]')).toHaveTextContent("sent the rate sheet"));
  });

  it("lets the writer take a note off after asking twice, and nobody else's", async () => {
    const user = userEvent.setup();
    const mine = { id: 1, text: "mine", at: "10/10/2026 1:00 PM", day: "10/10/2026", by: { id: 7, name: "Seller" } };
    const theirs = { id: 2, text: "theirs", at: "10/10/2026 2:00 PM", day: "10/10/2026", by: { id: 99, name: "Manager" } };
    const mocked = serve("sales", {
      "/api/v1/b2b/notes/1/delete/": () => jsonResponse({ ok: true, lead: lead() }),
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer({}, [lead({ notes: [mine, theirs] })])),
    });
    const { container } = open("/leads/3");
    await screen.findByDisplayValue("Lingua GmbH");
    expect(container.querySelector('[data-note="2"] button')).toBeNull();
    const x = container.querySelector('[data-note="1"] button') as HTMLButtonElement;
    expect(x).not.toBeNull();
    await user.click(x);
    expect(posted(mocked.calls, "/api/v1/b2b/notes/1/delete/")).toEqual([]);
    await user.click(screen.getByRole("button", { name: "أكيد امسحها" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/notes/1/delete/")).toHaveLength(1));
  });

  // 13/10/2026: a row copied from the team's Google Sheet and pasted into the company cell all landed in that one cell.
  const COPIED = "A2Z Traducciones\t\t34637563743\tinfo@a2z.es\t\t\t\t22-9";
  const readOne = () =>
    jsonResponse({
      ok: true,
      rows: [{ ...lead({ company_name: "A2Z Traducciones", phone: "34637563743", email: "info@a2z.es", country: "", industry: "", contact_person: "", position: "", whatsapp: "", languages: "" }), notes: "22-9" }].map(
        ({ id: _i, status: _s, priority: _p, deal_value: _d, phones: _ph, next_follow_up: _n, client_code: _c, whatsapp_at: _w, email_at: _e, call_at: _k, call_outcome: _co, reached: _rc, last_contact_at: _l, replied_at: _r, last_outreach_at: _o, follow_up: _f, overdue: _v, quote: _q, ...row }) => row,
      ),
      mapped: {},
      more: false,
    });

  it("spreads a row pasted into a cell over that row's columns, its leftovers as a note", async () => {
    const user = userEvent.setup();
    const mocked = serve("sales", {
      "/api/v1/b2b/sheets/3/read/": readOne,
      "/api/v1/b2b/leads/5/save/": () => jsonResponse({ ok: true, lead: lead() }),
      "/api/v1/b2b/leads/5/notes/": () => jsonResponse({ ok: true, lead: lead() }),
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()),
    });
    open("/leads/3");
    const company = await screen.findByLabelText("الشركة · Lingua GmbH");
    await user.click(company);
    await user.paste(COPIED);
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/leads/5/save/")).toHaveLength(1));
    expect(posted(mocked.calls, "/api/v1/b2b/sheets/3/read/")).toEqual([{ text: COPIED }]);
    expect(posted(mocked.calls, "/api/v1/b2b/leads/5/save/")).toEqual([
      { company_name: "A2Z Traducciones", phone: "34637563743", email: "info@a2z.es" },
    ]);
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/leads/5/notes/")).toEqual([{ text: "22-9" }]));
    // The cell never held the tabs: the blur saved nothing of its own.
    expect(company).not.toHaveValue(expect.stringContaining("\t"));
  });

  it("leaves a paste with no tab to the cell itself", async () => {
    const user = userEvent.setup();
    const mocked = serve("sales", { "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()) });
    open("/leads/3");
    const person = await screen.findByLabelText("الشخص المسؤول · Lingua GmbH");
    await user.clear(person);
    await user.paste("Anna Weber");
    expect(person).toHaveValue("Anna Weber");
    expect(posted(mocked.calls, "/api/v1/b2b/sheets/3/read/")).toEqual([]);
  });

  it("opens the upload window with the rows read when several rows are pasted into a cell", async () => {
    const user = userEvent.setup();
    const two = `${COPIED}\nABCTranslink\t\t34636442091\tinfo@abctranslink.com`;
    const mocked = serve("sales", {
      "/api/v1/b2b/sheets/3/read/": () =>
        jsonResponse({
          ok: true,
          rows: [
            { company_name: "A2Z Traducciones", country: "", website: "", industry: "", contact_person: "", position: "", email: "info@a2z.es", phone: "34637563743", whatsapp: "", linkedin: "", languages: "", services: "", source: "" },
            { company_name: "ABCTranslink", country: "", website: "", industry: "", contact_person: "", position: "", email: "info@abctranslink.com", phone: "34636442091", whatsapp: "", linkedin: "", languages: "", services: "", source: "" },
          ],
          mapped: {},
          more: false,
        }),
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()),
    });
    open("/leads/3");
    await user.click(await screen.findByLabelText("الشركة · Lingua GmbH"));
    await user.paste(two);
    expect(await screen.findByText("2 شركة جاهزة تتضاف")).toBeInTheDocument();
    expect(screen.getByLabelText("التليفون 2")).toHaveValue("34636442091");
    expect(posted(mocked.calls, "/api/v1/b2b/sheets/3/read/")).toHaveLength(1);
    expect(posted(mocked.calls, "/api/v1/b2b/leads/5/save/")).toEqual([]);
  });

  it("fills the new company's boxes from a pasted row", async () => {
    const user = userEvent.setup();
    serve("sales", { "/api/v1/b2b/sheets/3/read/": readOne, "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()) });
    open("/leads/3");
    await user.click(await screen.findByRole("button", { name: "شركة جديدة" }));
    await user.click(screen.getByLabelText("اسم الشركة"));
    await user.paste(COPIED);
    await waitFor(() => expect(screen.getByLabelText("اسم الشركة")).toHaveValue("A2Z Traducciones"));
    expect(screen.getByLabelText("التليفون")).toHaveValue("34637563743");
    expect(screen.getByLabelText("الإيميل")).toHaveValue("info@a2z.es");
    expect(screen.getByLabelText("ملاحظة")).toHaveValue("22-9");
  });

  it("opens the upload window from the sheet", async () => {
    const user = userEvent.setup();
    serve("sales", { "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()) });
    open("/leads/3");
    await user.click(await screen.findByRole("button", { name: "ارفع Excel أو Google Sheet" }));
    expect(screen.getByLabelText("ملف Excel أو CSV")).toBeInTheDocument();
  });

  it("draws a big sheet a hundred rows at a time, and the search looks through all of them", async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 250 }, (_unused, i) => lead({ id: i + 1, company_name: `Company ${i + 1}` }));
    serve("sales", { "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer({}, many)) });
    const { container } = open("/leads/3");
    await screen.findByDisplayValue("Company 1");
    expect(container.querySelectorAll("tr[data-lead]")).toHaveLength(100);
    expect(screen.getByText("1–100 من 250")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "السابق" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "التالي" }));
    await user.click(screen.getByRole("button", { name: "التالي" }));
    expect(container.querySelectorAll("tr[data-lead]")).toHaveLength(50);
    expect(screen.getByDisplayValue("Company 250")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("Company 1")).toBeNull();
    expect(screen.getByRole("button", { name: "التالي" })).toBeDisabled();
    // A search goes back to the first page, and finds a company that was not on the page drawn.
    await user.click(screen.getByLabelText("بحث"));
    await user.paste("Company 7");
    await waitFor(() => expect(container.querySelectorAll("tr[data-lead]")).toHaveLength(11));
    expect(screen.getByLabelText("الشركة · Company 7")).toBeInTheDocument();
    expect(container.querySelector("[data-pages]")).toBeNull();
  }, 30000);

  // 14/10/2026: on a 5000-row sheet the Sales person walked to company 2000, wrote to it, and on coming back walked there
  // again from the first page.
  it("opens a sheet again on the page and the view it was left on, each sheet its own", async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 250 }, (_unused, i) => lead({ id: i + 1, company_name: `Company ${i + 1}` }));
    serve("sales", {
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer({}, many)),
      "/api/v1/b2b/sheets/4/": () => jsonResponse(sheetAnswer({ id: 4 }, many)),
    });
    const first = open("/leads/3");
    await screen.findByDisplayValue("Company 1");
    await user.click(screen.getByRole("button", { name: "التالي" }));
    await user.click(screen.getByRole("button", { name: "التالي" }));
    // A search walks to its own first page and is not kept; wiping it goes back to the page before it.
    await user.click(screen.getByLabelText("بحث"));
    await user.paste("Company 7");
    await waitFor(() => expect(first.container.querySelector("[data-pages]")).toBeNull());
    await user.clear(screen.getByLabelText("بحث"));
    expect(await screen.findByText("201–250 من 250")).toBeInTheDocument();
    first.unmount();

    const back = open("/leads/3");
    expect(await screen.findByDisplayValue("Company 250")).toBeInTheDocument();
    expect(screen.getByText("201–250 من 250")).toBeInTheDocument();
    back.unmount();

    const other = open("/leads/4");
    expect(await screen.findByDisplayValue("Company 1")).toBeInTheDocument();
    expect(screen.getByText("1–100 من 250")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("اعرض"), "untouched");
    await user.click(screen.getByRole("button", { name: "التالي" }));
    other.unmount();

    open("/leads/4");
    expect(await screen.findByText("101–200 من 250")).toBeInTheDocument();
    expect(screen.getByLabelText("اعرض")).toHaveValue("untouched");
  }, 30000);

  // 15/10/2026: the Sales person writes down the sheet one company after another; the last row a message left from is
  // marked, so the sheet opens where they stopped and they write to the next one.
  it("opens on the last row a message left from, marked, and walks back to it from another page", async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 250 }, (_unused, i) => lead({ id: i + 1, company_name: `Company ${i + 1}` }));
    serve("sales", { "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer({ last_sent: 180 }, many)) });
    const { container } = open("/leads/3");
    expect(await screen.findByDisplayValue("Company 180")).toBeInTheDocument();
    expect(screen.getByText("101–200 من 250")).toBeInTheDocument();
    expect(container.querySelectorAll("tr.sheet__row--last")).toHaveLength(1);
    expect(container.querySelector("tr.sheet__row--last")).toHaveAttribute("data-lead", "180");
    expect(within(container.querySelector<HTMLElement>('tr[data-lead="180"]')!).getByText("آخر واحد بعتله")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "التالي" }));
    expect(await screen.findByText("201–250 من 250")).toBeInTheDocument();
    expect(container.querySelector("tr.sheet__row--last")).toBeNull();
    await user.click(screen.getByRole("button", { name: "آخر صف بعتله" }));
    expect(await screen.findByText("101–200 من 250")).toBeInTheDocument();
    expect(container.querySelector("tr.sheet__row--last")).toHaveAttribute("data-lead", "180");
  }, 30000);

  it("moves the mark to the row a message was just sent from, and marks nothing on a sheet never written from", async () => {
    const user = userEvent.setup();
    serve("sales", {
      "/api/v1/b2b/leads/5/send/": () => jsonResponse({ ok: true, chat: "CL-0042", lead: lead({ whatsapp_at: "15/10/2026 1:00 PM" }), last_sent: 5 }),
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer({}, [lead(), lead({ id: 6, company_name: "Other Co" })])),
    });
    const { container } = open("/leads/3");
    await screen.findByDisplayValue("Lingua GmbH");
    expect(container.querySelector("tr.sheet__row--last")).toBeNull();
    expect(screen.queryByRole("button", { name: "آخر صف بعتله" })).toBeNull();
    await user.click(within(container.querySelector<HTMLElement>('tr[data-lead="5"]')!).getByRole("button", { name: "ابعت رسالة" }));
    await user.type(screen.getByLabelText("الرسالة"), "Here are our rates");
    await user.click(screen.getByRole("button", { name: "ابعت" }));
    await waitFor(() => expect(container.querySelector("tr.sheet__row--last")).toHaveAttribute("data-lead", "5"));
    expect(screen.getByRole("button", { name: "آخر صف بعتله" })).toBeInTheDocument();
  });

  it("starts on the first page when what was kept is rubbish", async () => {
    localStorage.setItem("eagle.sheet.place", JSON.stringify({ 3: { page: "<b>", only: "everything" } }));
    serve("sales", { "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer({}, Array.from({ length: 150 }, (_u, i) => lead({ id: i + 1, company_name: `Company ${i + 1}` })))) });
    open("/leads/3");
    expect(await screen.findByText("1–100 من 150")).toBeInTheDocument();
    expect(screen.getByLabelText("اعرض")).toHaveValue("all");
  }, 30000);

  it("puts a saved cell's row in place without asking for the whole sheet again", async () => {
    const user = userEvent.setup();
    const mocked = serve("sales", {
      "/api/v1/b2b/leads/5/save/": () => jsonResponse({ ok: true, lead: lead({ contact_person: "Anna Weber", call_at: "13/10/2026 1:00 PM", reached: true }) }),
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()),
    });
    open("/leads/3");
    const person = await screen.findByLabelText("الشخص المسؤول · Lingua GmbH");
    const sheetLoads = () => mocked.calls.filter((call) => call.url === "/api/v1/b2b/sheets/3/").length;
    const before = sheetLoads();
    await user.clear(person);
    await user.type(person, "Anna Weber{Enter}");
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/leads/5/save/")).toHaveLength(1));
    // The row is the server's answer, and the header's count follows it.
    expect(await screen.findByText(/1 من 1 اتواصلنا معاهم/)).toBeInTheDocument();
    expect(sheetLoads()).toBe(before);
  });
});
