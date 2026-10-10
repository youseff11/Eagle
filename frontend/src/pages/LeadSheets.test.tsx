import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parsePasted, type B2bLead, type B2bSheetResponse, type B2bSheetsResponse } from "../api/b2b";
import type { Role } from "../api/types";
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
    next_follow_up: "",
    notes: "",
    client_code: "",
    whatsapp_at: "",
    email_at: "",
    call_at: "",
    last_contact_at: "",
    overdue: false,
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
    leads,
    columns: COLUMNS,
    statuses: [
      { value: "new", label: "New lead" },
      { value: "won", label: "Won" },
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
    <Routes>
      <Route path="/leads" element={<LeadSheetsPage />} />
      <Route path="/leads/:id" element={<LeadSheetPage />} />
      <Route path="/chats/:code" element={<div>chat page</div>} />
      <Route path="/" element={<div>home page</div>} />
    </Routes>,
    { route },
  );
}

const posted = (calls: { url: string; init?: RequestInit }[], url: string) =>
  calls.filter((call) => call.url === url && call.init?.method === "POST").map((call) => JSON.parse(String(call.init?.body)));

describe("parsePasted", () => {
  it("reads tab-separated lines in the sheet's column order, leaving out a header line and empty lines", () => {
    const text = "Company name\tCountry\nAlpha\tFrance\t\t\t\t\talpha@a.test\n\nBeta\r\n";
    const rows = parsePasted(text, COLUMNS);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({ company_name: "Alpha", country: "France", email: "alpha@a.test", whatsapp: "" });
    expect(rows[1]).toMatchObject({ company_name: "Beta" });
  });

  it("knows an Arabic header too, and cuts a cell to its column's length", () => {
    const rows = parsePasted(`اسم الشركة\tالدولة\nGamma\t${"x".repeat(200)}`, COLUMNS);
    expect(rows).toHaveLength(1);
    expect(rows[0]?.country).toHaveLength(80);
  });
});

describe("LeadSheetsPage", () => {
  const list = (over: Partial<B2bSheetsResponse> = {}): B2bSheetsResponse => ({
    ok: true,
    can_manage: false,
    sales: [],
    sheets: [{ ...sheetAnswer().sheet, rows: 4, contacted: 1 }],
    ...over,
  });

  it("shows a Sales person their sheets, with no box to make one", async () => {
    serve("sales", { "/api/v1/b2b/sheets/": () => jsonResponse(list()) });
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
      "/api/v1/b2b/sheets/": () => jsonResponse(list({ can_manage: true, sales: [{ id: 7, name: "Seller" }] })),
    });
    open("/leads");
    await user.type(await screen.findByLabelText("اسم الشيت"), "France");
    await user.selectOptions(screen.getByLabelText("الـSales اللي هياخده"), "7");
    await user.click(screen.getByRole("button", { name: "اعمل الشيت" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/sheets/new/")).toEqual([{ title: "France", note: "", assigned_to: 7 }]));
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
    const row = (await screen.findByText("Lingua GmbH")).closest("tr") as HTMLElement;
    expect(within(row).getByRole("button", { name: "ابعت واتساب" })).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "ابعت إيميل" })).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "سجّل مكالمة" })).toBeInTheDocument();
  });

  it("draws no contact button for the manager reading someone else's sheet, and says why", async () => {
    serve("sales", { "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer({ can_contact: false, can_manage: true })) });
    open("/leads/3");
    const row = (await screen.findByText("Lingua GmbH")).closest("tr") as HTMLElement;
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
    const row = (await screen.findByText("Lingua GmbH")).closest("tr") as HTMLElement;
    expect(within(row).getAllByText("10/10/2026 1:00 PM").length).toBeGreaterThanOrEqual(2);
    expect(row.querySelector(".chip--replied")).not.toBeNull();
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

  it("adds a pasted block of rows in one request", async () => {
    const user = userEvent.setup();
    const mocked = serve("sales", {
      "/api/v1/b2b/sheets/3/rows/": () => jsonResponse({ ok: true, added: 2, leads: [] }),
      "/api/v1/b2b/sheets/3/": () => jsonResponse(sheetAnswer()),
    });
    open("/leads/3");
    await user.click(await screen.findByRole("button", { name: "لزق من شيت" }));
    const box = screen.getByLabelText("الصفوف");
    await user.click(box);
    await user.paste("Alpha\tFrance\nBeta\tSpain");
    expect(screen.getByText("2 شركة جاهزة تتضاف")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "ضيفهم" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/sheets/3/rows/")).toHaveLength(1));
    const [body] = posted(mocked.calls, "/api/v1/b2b/sheets/3/rows/");
    expect(body.rows.map((row: { company_name: string; country: string }) => [row.company_name, row.country])).toEqual([
      ["Alpha", "France"],
      ["Beta", "Spain"],
    ]);
  });
});
