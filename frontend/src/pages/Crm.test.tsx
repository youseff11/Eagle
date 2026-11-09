import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseCrmLines, type CrmRow, type CrmSheetResponse, type CrmSheetsResponse } from "../api/crm";
import { ToastProvider } from "../components/Toasts";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { CrmSheetPage } from "./CrmSheetPage";
import { CrmSheetsPage } from "./CrmSheetsPage";

/**
 * CRM (09/11/2026): the real-estate branch's sheets. Four columns and nothing more (the name, the phone, the status and the
 * contact buttons); the manager makes a sheet and writes its rows, the holder sets the status and contacts. Every rule is the
 * server's: what is held here is that the page draws what the answer allows and sends exactly what the server reads.
 */

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

const posted = (calls: { url: string; init?: RequestInit }[], url: string) =>
  calls.filter((call) => call.url === url && call.init?.method === "POST").map((call) => JSON.parse(String(call.init?.body)));

const STATUSES: CrmSheetResponse["statuses"] = [
  { value: "interested", ar: "مهتم", en: "Interested" },
  { value: "not_interested", ar: "غير مهتم", en: "Not interested" },
  { value: "quote_requested", ar: "طلب عرض سعر", en: "Asked for a price" },
  { value: "contacted", ar: "تم التواصل", en: "Contacted" },
  { value: "no_answer", ar: "مردش", en: "No answer" },
];

const COUNTS = { rows: 1, interested: 0, not_interested: 0, quote_requested: 0, contacted: 0, no_answer: 0 };

function row(over: Partial<CrmRow> = {}): CrmRow {
  return { id: 11, name: "Ahmed", phone: "01001234567", status: "", chat: "", ...over };
}

function sheet(over: Partial<CrmSheetResponse> = {}): CrmSheetResponse {
  return {
    ok: true,
    sheet: { id: 3, title: "New Cairo", assigned_to: { id: 7, name: "Agent" }, created_by: null, created_at: "", counts: COUNTS },
    rows: [row()],
    statuses: STATUSES,
    can_manage: false,
    can_contact: true,
    holders: [],
    ...over,
  };
}

function serve(routes: Record<string, (url: URL, init?: RequestInit) => Response>, who: Record<string, unknown> = {}) {
  const mocked = mockFetch({ "/api/v1/me/": () => jsonResponse(me({ role: "crm", ...who })), ...routes });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function open(route: string) {
  return renderWithProviders(
    <ToastProvider>
      <Routes>
        <Route path="/crm" element={<CrmSheetsPage />} />
        <Route path="/crm/:id" element={<CrmSheetPage />} />
        <Route path="/chats/:code" element={<div>the chat</div>} />
        <Route path="/" element={<div>home page</div>} />
      </Routes>
    </ToastProvider>,
    { route },
  );
}

describe("a CRM sheet", () => {
  it("has the four columns and the owner's five statuses, and the holder only sets the status", async () => {
    serve({ "/api/v1/crm/sheets/3/": () => jsonResponse(sheet()) });
    open("/crm/3");
    expect(await screen.findByText("Ahmed")).toBeInTheDocument();
    const heads = screen.getAllByRole("columnheader").map((cell) => cell.textContent);
    expect(heads).toEqual(["الاسم", "رقم التليفون", "الحالة", "التواصل"]);
    const status = screen.getByLabelText("الحالة");
    expect(within(status).getAllByRole("option").map((option) => option.textContent)).toEqual(["— لسه —", "مهتم", "غير مهتم", "طلب عرض سعر", "تم التواصل", "مردش"]);
    // The holder writes no row: no boxes for the name or the phone, no «ضيف صفوف», no delete.
    expect(screen.queryByLabelText("الاسم")).toBeNull();
    expect(screen.queryByText("ضيف صفوف")).toBeNull();
    expect(screen.queryByRole("button", { name: /امسح الصف/ })).toBeNull();
  });

  it("saves the status as soon as it is picked", async () => {
    const mocked = serve({
      "/api/v1/crm/rows/11/save/": () => jsonResponse({ ok: true, row: row({ status: "no_answer" }) }),
      "/api/v1/crm/sheets/3/": () => jsonResponse(sheet()),
    });
    open("/crm/3");
    await userEvent.selectOptions(await screen.findByLabelText("الحالة"), "no_answer");
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/crm/rows/11/save/")).toEqual([{ status: "no_answer" }]));
  });

  it("calls from the phone and opens the WhatsApp chat on the holder's number", async () => {
    const mocked = serve({
      "/api/v1/crm/rows/11/whatsapp/": () => jsonResponse({ ok: true, chat: "C-0042", row: row({ chat: "C-0042" }) }),
      "/api/v1/crm/sheets/3/": () => jsonResponse(sheet()),
    });
    open("/crm/3");
    expect(await screen.findByRole("link", { name: "اتصل" })).toHaveAttribute("href", "tel:01001234567");
    await userEvent.click(screen.getByRole("button", { name: "واتساب" }));
    expect(await screen.findByText("the chat")).toBeInTheDocument();
    expect(posted(mocked.calls, "/api/v1/crm/rows/11/whatsapp/")).toEqual([{}]);
  });

  it("says why WhatsApp cannot start the conversation, in the server's words", async () => {
    serve({
      "/api/v1/crm/rows/11/whatsapp/": () => jsonResponse({ ok: false, error: "needs_template", message: "لسه مفيش كلام بينك وبين الرقم ده", message_en: "x" }, 400),
      "/api/v1/crm/sheets/3/": () => jsonResponse(sheet()),
    });
    open("/crm/3");
    await userEvent.click(await screen.findByRole("button", { name: "واتساب" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("لسه مفيش كلام بينك وبين الرقم ده");
    expect(screen.queryByText("the chat")).toBeNull();
  });

  it("gives the manager no WhatsApp button on a sheet someone else holds, and the boxes to write the rows", async () => {
    const mocked = serve(
      {
        "/api/v1/crm/sheets/3/rows/": () => jsonResponse({ ok: true, rows: [] }),
        "/api/v1/crm/sheets/3/": () => jsonResponse(sheet({ can_manage: true, can_contact: false, holders: [{ id: 7, name: "Agent" }, { id: 8, name: "Boss" }] })),
      },
      { crm_manager: true },
    );
    open("/crm/3");
    expect(await screen.findByLabelText("الاسم")).toHaveValue("Ahmed");
    expect(screen.queryByRole("button", { name: "واتساب" })).toBeNull();
    await userEvent.type(screen.getByLabelText(/كل واحد في سطر/), "Mona, 01112223334{enter}Omar 01223334445");
    await userEvent.click(screen.getByRole("button", { name: "ضيف 2" }));
    await waitFor(() =>
      expect(posted(mocked.calls, "/api/v1/crm/sheets/3/rows/")).toEqual([
        { rows: [{ name: "Mona", phone: "01112223334" }, { name: "Omar", phone: "01223334445" }] },
      ]),
    );
  });
});

describe("the CRM sheets", () => {
  const list = (over: Partial<CrmSheetsResponse> = {}): CrmSheetsResponse => ({
    ok: true,
    can_manage: false,
    holders: [],
    statuses: STATUSES,
    sheets: [{ id: 3, title: "New Cairo", assigned_to: { id: 7, name: "Agent" }, created_by: null, created_at: "09/11/2026", counts: { ...COUNTS, interested: 1 } }],
    ...over,
  });

  it("lets the manager make a sheet for someone on the team", async () => {
    const mocked = serve(
      {
        "/api/v1/crm/sheets/new/": () => jsonResponse({ ok: true, sheet: { id: 9 } }),
        "/api/v1/crm/sheets/9/": () => jsonResponse(sheet({ rows: [] })),
        "/api/v1/crm/sheets/": () => jsonResponse(list({ can_manage: true, holders: [{ id: 7, name: "Agent" }] })),
      },
      { crm_manager: true },
    );
    open("/crm");
    await userEvent.type(await screen.findByLabelText("اسم الشيت"), "Zayed");
    await userEvent.selectOptions(screen.getByLabelText("صاحب الشيت"), "7");
    await userEvent.click(screen.getByRole("button", { name: "اعمل الشيت" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/crm/sheets/new/")).toEqual([{ title: "Zayed", assigned_to: 7 }]));
  });

  it("shows a CRM person their sheets without the box that makes one", async () => {
    serve({ "/api/v1/crm/sheets/": () => jsonResponse(list()) });
    open("/crm");
    expect(await screen.findByText("New Cairo")).toBeInTheDocument();
    expect(screen.queryByText("شيت جديد")).toBeNull();
  });

  it("sends anyone off the CRM team home", async () => {
    serve({ "/api/v1/crm/sheets/": () => jsonResponse(list()) }, { role: "sales" });
    open("/crm");
    expect(await screen.findByText("home page")).toBeInTheDocument();
  });
});

describe("pasted lines", () => {
  it("reads a name and a number from a tab, a comma or spaces, in either order", () => {
    expect(parseCrmLines("Mona\t01112223334\n01223334445, Omar\nأحمد علي 0100 123 4567\n\n")).toEqual([
      { name: "Mona", phone: "01112223334" },
      { name: "Omar", phone: "01223334445" },
      { name: "أحمد علي", phone: "0100 123 4567" },
    ]);
  });
});
