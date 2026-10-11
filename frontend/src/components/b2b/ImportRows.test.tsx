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
    whatsapp: "", linkedin: "", languages: "", services: "", source: "", ...over,
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

  it("says why a file could not be read", async () => {
    const user = userEvent.setup();
    serve(() => jsonResponse({ ok: false, error: "unreadable", message: "الملف ده مش Excel سليم. احفظه .xlsx أو CSV.", message_en: "x" }, 400));
    open();
    await user.upload(screen.getByLabelText("ملف Excel أو CSV"), new File(["not a zip"], "broken.xlsx"));
    expect(await screen.findByRole("alert")).toHaveTextContent("الملف ده مش Excel سليم");
  });
});
