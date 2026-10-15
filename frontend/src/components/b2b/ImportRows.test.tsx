import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { B2bRow, B2bSheetResponse } from "../../api/b2b";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../../test/helpers";
import { ImportRows } from "./ImportRows";

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

function row(over: Partial<B2bRow> = {}): B2bRow {
  return {
    company_name: "", country: "", website: "", industry: "", contact_person: "", position: "", email: "", phone: "",
    whatsapp: "", linkedin: "", languages: "", services: "", source: "", governorate: "", address: "", location: "", ...over,
  };
}

function serve(read: () => Response) {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role: "sales" })),
    "/api/v1/b2b/sheets/3/read/": read,
    "/api/v1/b2b/sheets/3/rows/": () => jsonResponse({ ok: true, added: 2, leads: [] }),
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function open() {
  return renderWithProviders(<ImportRows sheetId={3} columns={COLUMNS} onClose={() => undefined} />);
}

const posts = (calls: { url: string; init?: RequestInit }[], url: string) => calls.filter((call) => call.url === url && call.init?.method === "POST");

describe("ImportRows", () => {
  it("sends the chosen file to be read, shows the columns found, and lets every cell be corrected before adding", async () => {
    const user = userEvent.setup();
    const mocked = serve(() =>
      jsonResponse({
        ok: true,
        rows: [row({ company_name: "Alpha Ltd", phone: "1012345678" }), row({ company_name: "Beta", email: "b@beta.test" }), row({ country: "Spain" })],
        mapped: { company_name: "Company", phone: "Mobile" },
        more: false,
      }),
    );
    open();
    await user.upload(screen.getByLabelText("ملف Excel أو CSV"), new File(["x"], "leads.xlsx"));
    expect(await screen.findByText(/Mobile → التليفون/)).toBeInTheDocument();
    const [upload] = posts(mocked.calls, "/api/v1/b2b/sheets/3/read/");
    expect(upload?.init?.body).toBeInstanceOf(FormData);
    // The leading zero Excel dropped is put back by hand, and the row with no company is left out.
    const phone = screen.getByLabelText("التليفون 1");
    await user.clear(phone);
    await user.type(phone, "01012345678");
    expect(screen.getByText("2 شركة جاهزة تتضاف")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "ضيفهم" }));
    await waitFor(() => expect(posts(mocked.calls, "/api/v1/b2b/sheets/3/rows/")).toHaveLength(1));
    const body = JSON.parse(String(posts(mocked.calls, "/api/v1/b2b/sheets/3/rows/")[0]?.init?.body));
    expect(body.rows.map((r: B2bRow) => [r.company_name, r.phone])).toEqual([
      ["Alpha Ltd", "01012345678"],
      ["Beta", ""],
    ]);
  });

  it("reads pasted cells the same way, and a row can be taken out or added", async () => {
    const user = userEvent.setup();
    const mocked = serve(() => jsonResponse({ ok: true, rows: [row({ company_name: "Gamma" }), row({ company_name: "Delta" })], mapped: {}, more: false }));
    open();
    await user.click(screen.getByLabelText("أو الزق الصفوف هنا (منسوخة من الشيت)"));
    await user.paste("Gamma\nDelta");
    await user.click(screen.getByRole("button", { name: "اعرض الصفوف" }));
    expect(JSON.parse(String(posts(mocked.calls, "/api/v1/b2b/sheets/3/read/")[0]?.init?.body))).toEqual({ text: "Gamma\nDelta" });
    await screen.findByDisplayValue("Delta");
    await user.click(screen.getAllByRole("button", { name: "شيل الصف" })[1]!);
    expect(screen.queryByDisplayValue("Delta")).toBeNull();
    await user.click(screen.getByRole("button", { name: "صف جديد" }));
    await user.type(screen.getByLabelText("اسم الشركة 2"), "Epsilon");
    expect(screen.getByText("2 شركة جاهزة تتضاف")).toBeInTheDocument();
  });

  it("reads a Google Sheets link, keeps the status that came with it, and adds the rows", async () => {
    const user = userEvent.setup();
    const mocked = serve(() =>
      jsonResponse({
        ok: true,
        rows: [{ ...row({ company_name: "BASH", phone: "96522213775" }), status: "contacted", priority: "medium" }],
        mapped: { company_name: "الشركة", status: "الحالة" },
        more: false,
      }),
    );
    open();
    const link = "https://docs.google.com/spreadsheets/d/1ApFC-DzCnxbIANj_AFZpWmAvaqleT74NYP0eU2xjsGQ/edit?usp=sharing";
    await user.type(screen.getByLabelText("أو حط لينك الشيت من Google Sheets"), link);
    await user.click(screen.getByRole("button", { name: "اقرا الشيت" }));
    expect(JSON.parse(String(posts(mocked.calls, "/api/v1/b2b/sheets/3/read/")[0]?.init?.body))).toEqual({ link });
    expect(await screen.findByText(/الحالة → الحالة/)).toBeInTheDocument();
    await screen.findByDisplayValue("BASH");
    await user.click(screen.getByRole("button", { name: "ضيفهم" }));
    await waitFor(() => expect(posts(mocked.calls, "/api/v1/b2b/sheets/3/rows/")).toHaveLength(1));
    const body = JSON.parse(String(posts(mocked.calls, "/api/v1/b2b/sheets/3/rows/")[0]?.init?.body));
    expect(body.rows[0]).toMatchObject({ company_name: "BASH", status: "contacted", priority: "medium" });
  });

  it("says how to open a sheet that is not shared", async () => {
    const user = userEvent.setup();
    serve(() => jsonResponse({ ok: false, error: "unreadable", message: "الشيت مقفول. افتحه في Google Sheets واضغط Share", message_en: "x" }, 400));
    open();
    expect(screen.getByRole("button", { name: "اقرا الشيت" })).toBeDisabled();
    await user.type(screen.getByLabelText("أو حط لينك الشيت من Google Sheets"), "https://docs.google.com/spreadsheets/d/1ApFC-DzCnxbIANj_AFZpWmAvaqleT74NYP0eU2xjsGQ/edit");
    await user.click(screen.getByRole("button", { name: "اقرا الشيت" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("الشيت مقفول");
  });

  it("shows thousands of rows a page at a time and adds them in parts of 500", async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 1200 }, (_unused, i) => row({ company_name: `Firm ${i + 1}` }));
    const mocked = mockFetch({
      "/api/v1/me/": () => jsonResponse(me({ role: "sales" })),
      "/api/v1/b2b/sheets/3/read/": () => jsonResponse({ ok: true, rows: many, mapped: {}, more: false, max_rows: 5000, room: 4999 }),
      "/api/v1/b2b/sheets/3/rows/": (_url, init) => jsonResponse({ ok: true, added: JSON.parse(String(init?.body)).rows.length }),
    });
    vi.stubGlobal("fetch", mocked.fn);
    const { container } = open();
    await user.upload(screen.getByLabelText("ملف Excel أو CSV"), new File(["x"], "leads.xlsx"));
    await screen.findByDisplayValue("Firm 1");
    expect(container.querySelectorAll("tr[data-import-row]")).toHaveLength(100);
    expect(screen.getByText("1200 شركة جاهزة تتضاف")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "التالي" }));
    expect(screen.getByDisplayValue("Firm 101")).toBeInTheDocument();
    // A cell on the second page is the row it shows.
    await user.click(screen.getByLabelText("الدولة 101"));
    await user.paste("Spain");
    await user.click(screen.getByRole("button", { name: "ضيفهم" }));
    await waitFor(() => expect(posts(mocked.calls, "/api/v1/b2b/sheets/3/rows/")).toHaveLength(3));
    const parts = posts(mocked.calls, "/api/v1/b2b/sheets/3/rows/").map((call) => JSON.parse(String(call.init?.body)).rows as B2bRow[]);
    expect(parts.map((part) => part.length)).toEqual([500, 500, 200]);
    expect(parts[0]![100]).toMatchObject({ company_name: "Firm 101", country: "Spain" });
    expect(parts[2]![199]!.company_name).toBe("Firm 1200");
  }, 30000);

  it("says before adding anything that the sheet has no room for them all", async () => {
    const user = userEvent.setup();
    const mocked = serve(() =>
      jsonResponse({ ok: true, rows: [row({ company_name: "A" }), row({ company_name: "B" }), row({ company_name: "C" })], mapped: {}, more: false, max_rows: 5000, room: 2 }),
    );
    open();
    await user.upload(screen.getByLabelText("ملف Excel أو CSV"), new File(["x"], "leads.xlsx"));
    await screen.findByDisplayValue("C");
    await user.click(screen.getByRole("button", { name: "ضيفهم" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("فاضل فيه مكان لـ2 بس");
    expect(posts(mocked.calls, "/api/v1/b2b/sheets/3/rows/")).toEqual([]);
  });

  it("keeps the rows a failed part did not add, and says how many went in", async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 700 }, (_unused, i) => row({ company_name: `Firm ${i + 1}` }));
    let parts = 0;
    const mocked = mockFetch({
      "/api/v1/me/": () => jsonResponse(me({ role: "sales" })),
      "/api/v1/b2b/sheets/3/read/": () => jsonResponse({ ok: true, rows: many, mapped: {}, more: false }),
      "/api/v1/b2b/sheets/3/rows/": () => {
        parts += 1;
        return parts === 1 ? jsonResponse({ ok: true, added: 500 }) : jsonResponse({ ok: false, error: "bad_request" }, 400);
      },
    });
    vi.stubGlobal("fetch", mocked.fn);
    open();
    await user.upload(screen.getByLabelText("ملف Excel أو CSV"), new File(["x"], "leads.xlsx"));
    await screen.findByDisplayValue("Firm 1");
    await user.click(screen.getByRole("button", { name: "ضيفهم" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("اتضاف 500 شركة والباقي ماتضافش");
    expect(screen.getByText("200 شركة جاهزة تتضاف")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Firm 501")).toBeInTheDocument();
  }, 30000);

  it("says the file went on past what a sheet holds", async () => {
    const user = userEvent.setup();
    serve(() => jsonResponse({ ok: true, rows: [row({ company_name: "A" })], mapped: {}, more: true, max_rows: 5000, room: 5000 }));
    open();
    await user.upload(screen.getByLabelText("ملف Excel أو CSV"), new File(["x"], "leads.xlsx"));
    expect(await screen.findByText(/الملف فيه أكتر من 5000 شركة/)).toBeInTheDocument();
  });

  it("says why a file could not be read", async () => {
    const user = userEvent.setup();
    serve(() => jsonResponse({ ok: false, error: "unreadable", message: "الملف ده مش Excel سليم. احفظه .xlsx أو CSV.", message_en: "x" }, 400));
    open();
    await user.upload(screen.getByLabelText("ملف Excel أو CSV"), new File(["not a zip"], "broken.xlsx"));
    expect(await screen.findByRole("alert")).toHaveTextContent("الملف ده مش Excel سليم");
  });
});
