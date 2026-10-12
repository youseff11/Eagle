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

afterEach(() => vi.unstubAllGlobals());

const COLUMNS: B2bSheetResponse["columns"] = [
  { name: "company_name", ar: "اسم الشركة", en: "Company name", max: 160 },
  { name: "country", ar: "الدولة", en: "Country", max: 80 },
  { name: "website", ar: "الموقع", en: "Website", max: 250 },
  { name: "industry", ar: "نوع الشركة", en: "Industry / type", max: 120 },
  { name: "contact_person", ar: "الشخص المسؤول", en: "Contact person", max: 160 },
  { name: "position", ar: "المنصب", en: "Position", max: 120 },
  { name: "email", ar: "الإيميل", en: "Email", max: 254 },
  { name: "phone", ar: "التليفون", en: "Phone", max: 40 },
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
    next_follow_up: "",
    notes: "",
    client_code: "",
    whatsapp_at: "",
    email_at: "",
    call_at: "",
    last_contact_at: "",
    replied_at: "",
    last_outreach_at: "",
    follow_up: "",
    overdue: false,
    quote: null,
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
    outcomes: [{ value: "no_answer", label: "No answer" }],
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
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/sheets/new/")).toEqual([{ title: "France", note: "", assigned_to: 7 }]));
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
  it("puts a WhatsApp, an e-mail and a call button beside the company for the sheet's own Sales person", async () => {
    serve("sales", { "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()) });
    open("/leads/3");
    const row = (await screen.findByDisplayValue("Lingua GmbH")).closest("tr") as HTMLElement;
    expect(within(row).getByRole("button", { name: "ابعت واتساب" })).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "ابعت إيميل" })).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "سجّل مكالمة" })).toBeInTheDocument();
  });

  it("draws no contact button for the manager reading someone else's sheet, and says why", async () => {
    serve("sales", { "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer({ can_contact: false, can_manage: true })) });
    open("/leads/3");
    const row = (await screen.findByDisplayValue("Lingua GmbH")).closest("tr") as HTMLElement;
    expect(within(row).queryByRole("button", { name: "ابعت واتساب" })).toBeNull();
    expect(within(row).queryByRole("button", { name: "سجّل مكالمة" })).toBeNull();
    expect(screen.getByText(/التواصل من الشيت ده لصاحبه بس/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "إعدادات الشيت" })).toBeInTheDocument();
  });

  it("asks before the opening message goes, then opens the chat the server names", async () => {
    const user = userEvent.setup();
    const mocked = serve("sales", {
      "/api/v1/b2b/leads/5/whatsapp/": () => jsonResponse({ ok: true, sent: true, chat: "CL-0042", lead: lead({ whatsapp_at: "10/10/2026 1:00 PM" }) }),
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()),
    });
    open("/leads/3");
    await user.click(await screen.findByRole("button", { name: "ابعت واتساب" }));
    expect(posted(mocked.calls, "/api/v1/b2b/leads/5/whatsapp/")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "ابعت وافتح الشات" }));
    expect(await screen.findByText("chat page")).toBeInTheDocument();
    expect(posted(mocked.calls, "/api/v1/b2b/leads/5/whatsapp/")).toHaveLength(1);
  });

  it("shows the server's reason when the send is refused, and stays", async () => {
    const user = userEvent.setup();
    serve("sales", {
      "/api/v1/b2b/leads/5/whatsapp/": () => jsonResponse({ ok: false, error: "no_line", message: "مفيش رقم واتساب متسجّل ليك.", message_en: "x" }, 400),
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()),
    });
    open("/leads/3");
    await user.click(await screen.findByRole("button", { name: "ابعت واتساب" }));
    await user.click(screen.getByRole("button", { name: "ابعت وافتح الشات" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("مفيش رقم واتساب متسجّل ليك.");
    expect(screen.queryByText("chat page")).toBeNull();
  });

  it("marks what reached the company, with when", async () => {
    serve("sales", {
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer({}, [lead({ whatsapp_at: "10/10/2026 1:00 PM", last_contact_at: "10/10/2026 1:00 PM" })])),
    });
    open("/leads/3");
    const row = (await screen.findByDisplayValue("Lingua GmbH")).closest("tr") as HTMLElement;
    expect(within(row).getByText("10/10/2026 1:00 PM")).toBeInTheDocument();
    expect(row.querySelector(".chip--replied")).toHaveTextContent("واتساب");
    // The button of the way that reached them is marked; the others are not.
    expect(within(row).getByRole("button", { name: "ابعت واتساب" })).toHaveClass("is-done");
    expect(within(row).getByRole("button", { name: "ابعت إيميل" })).not.toHaveClass("is-done");
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
        jsonResponse(sheetAnswer({}, [lead({ status: "contacted", priority: "medium", deal_value: "1500", notes: "call back", industry: "Tourism", country: "الكويت" })])),
    });
    const { container } = open("/leads/3");
    const row = (await screen.findByDisplayValue("Lingua GmbH")).closest("tr") as HTMLElement;
    const heads = [...container.querySelectorAll(".sheet thead tr:first-child th")].map((th) => th.textContent);
    expect(heads).toEqual(["الشركة", "الشخص المسؤول", "رقم الهاتف", "البريد الإلكتروني", "الحالة", "الأولوية", "قيمة الصفقة", "النشاط", "ملاحظات", "الدوله", "التواصل"]);
    expect(container.querySelector(".sheet .sheet__band")).not.toBeNull();
    expect(within(row).getByLabelText("الحالة · Lingua GmbH")).toHaveValue("contacted");
    expect(within(row).getByRole("option", { name: "تم التواصل" })).toBeInTheDocument();
    expect(within(row).getByLabelText("الأولوية · Lingua GmbH")).toHaveValue("medium");
    expect(within(row).getByLabelText("قيمة الصفقة · Lingua GmbH")).toHaveValue("1500");
    expect(within(row).getByLabelText("ملاحظات · Lingua GmbH")).toHaveValue("call back");
    expect(within(row).getByLabelText("الدوله · Lingua GmbH")).toHaveValue("الكويت");
  });

  it("saves a typed cell alone when the cursor leaves it, and nothing when it did not change", async () => {
    const user = userEvent.setup();
    const mocked = serve("sales", {
      "/api/v1/b2b/leads/5/save/": () => jsonResponse({ ok: true, lead: lead({ notes: "call Sunday" }) }),
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()),
    });
    open("/leads/3");
    const notes = await screen.findByLabelText("ملاحظات · Lingua GmbH");
    await user.click(notes);
    await user.tab();
    expect(posted(mocked.calls, "/api/v1/b2b/leads/5/save/")).toEqual([]);
    await user.type(notes, "call Sunday{Enter}");
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/leads/5/save/")).toEqual([{ notes: "call Sunday" }]));
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

  it("opens the upload window from the sheet", async () => {
    const user = userEvent.setup();
    serve("sales", { "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()) });
    open("/leads/3");
    await user.click(await screen.findByRole("button", { name: "ارفع Excel أو Google Sheet" }));
    expect(screen.getByLabelText("ملف Excel أو CSV")).toBeInTheDocument();
  });
});
