import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CommissionLine, CommissionsResponse, Deal } from "../api/commissions";
import { ToastProvider } from "../components/Toasts";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { CommissionsPage } from "./CommissionsPage";

/** The commissions page, per deal (21/10/2026): each deal a Sales person closed with its details, the owner's rates, the
 * deal's set-up (value, invoice, each person's percent) and buttons drawn from what the server says, and the Sales person's
 * own lines with no button at all. */

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

const posted = (calls: { url: string; init?: RequestInit }[], url: string) =>
  calls.filter((call) => call.url === url && call.init?.method === "POST").map((call) => JSON.parse(String(call.init?.body)));

function line(over: Partial<CommissionLine> = {}): CommissionLine {
  return {
    id: 4, code: "COM-0004", person: { id: 7, name: "Abroad" }, rate: "5.00", own_rate: false, status: "pending", amount: "500.00",
    currency: "USD", amount_egp: "25000.00", approved_by: null, approved_at: "", paid_at: "", note: "", ...over,
  };
}

function deal(over: Partial<Deal> = {}): Deal {
  return {
    id: 3, code: "DEAL-0003", market: "b2b", status: "open", stage: "due",
    company: { name: "Lingua GmbH", sheet: "Germany", contact_person: "Anna", position: "CEO", country: "Germany", services: "Legal", languages: "DE>AR", sheet_value: null },
    client_code: "CL-0003", owner: { id: 7, name: "Abroad" }, won_at: "21/10/2026", won_by: { id: 7, name: "Abroad" },
    value: "10000.00", currency: "USD", value_by_hand: false, egp_rate: "50.0000",
    quotation: {
      code: "QT-0002", status: "accepted", service: "Translation", unit: "Words", quantity: 1000, rate: "10.00", discount: "0.00", total: "10000.00",
      currency: "USD", source_lang: "German", target_lang: "Arabic", deadline: "30/10/2026", payment_terms: "",
    },
    invoice: { id: 9, code: "INV-0009", status: "paid", amount: "10000.00", currency: "USD", client_code: "CL-0003" },
    paid: true, note: "", lines: [line()], ...over,
  };
}

function answer(over: Partial<CommissionsResponse> = {}): CommissionsResponse {
  return {
    ok: true, can_manage: true, deals: [deal()],
    totals: { waiting: "0.00", due: "25000.00", approved: "0.00", paid: "0.00", unknown: 0 },
    currencies: ["USD", "EUR", "EGP"],
    company_rate: "5.00",
    people: [{ id: 7, name: "Abroad", rate: null, track: "b2b" }, { id: 8, name: "Walker", rate: "7.00", track: "b2c_field" }],
    uncovered: [{ id: 11, code: "INV-0011", status: "sent", amount: "300.00", currency: "EGP", client_code: "CL-0005" }], ...over,
  };
}

function serve(body: CommissionsResponse, who: Record<string, unknown> = { role: "admin", is_admin: true }) {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me(who)),
    "/api/v1/commissions/": (_url, init) => (init?.method === "POST" ? jsonResponse({ ok: true, deal: deal({ id: 12 }) }) : jsonResponse(body)),
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function open() {
  return renderWithProviders(
    <ToastProvider>
      <Routes>
        <Route path="/commissions" element={<CommissionsPage />} />
        <Route path="/" element={<div>home page</div>} />
      </Routes>
    </ToastProvider>,
    { route: "/commissions" },
  );
}

const card = async (code: string) => within((await screen.findByText(code)).closest("[data-deal]") as HTMLElement);

describe("CommissionsPage", () => {
  it("shows each deal with what it was about", async () => {
    serve(answer());
    open();
    const one = await card("DEAL-0003");
    expect(one.getByText("Lingua GmbH")).toBeInTheDocument();
    expect(one.getByText("10000.00 USD", { selector: "[data-deal-value]" })).toBeInTheDocument();
    expect(one.getByText("Anna · CEO")).toBeInTheDocument();
    expect(one.getByText("QT-0002")).toBeInTheDocument();
    expect(one.getByText("German > Arabic", { exact: false })).toBeInTheDocument();
    expect(one.getByText("INV-0009")).toBeInTheDocument();
    expect(one.getByText("Abroad", { selector: ".kv strong" })).toBeInTheDocument();
  });

  it("lets the owner set the company rate and a person's own", async () => {
    const user = userEvent.setup();
    const mocked = serve(answer());
    open();
    const company = await screen.findByLabelText("النسبة العامة");
    await user.clear(company);
    await user.type(company, "6");
    await user.click(within(company.closest("form") as HTMLElement).getByRole("button", { name: "احفظ" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/commissions/rate/")).toEqual([{ rate: "6" }]));
    const walker = screen.getByLabelText("نسبة Walker");
    await user.clear(walker);
    await user.click(within(walker.closest("form") as HTMLElement).getByRole("button", { name: "احفظ" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/commissions/people/8/rate/")).toEqual([{ rate: "" }]));
  });

  it("sets up a deal: its value, invoice and each person's own percent", async () => {
    const user = userEvent.setup();
    const mocked = serve(answer());
    open();
    await user.click((await card("DEAL-0003")).getByRole("button", { name: "ظبّط الصفقة" }));
    const value = screen.getByLabelText("قيمة الصفقة");
    await user.clear(value);
    await user.type(value, "9500");
    await user.selectOptions(screen.getByLabelText("الفاتورة"), "11");
    await user.type(screen.getByLabelText("العمولة 1"), "6");
    await user.click(screen.getByRole("button", { name: "ضيف Sales" }));
    await user.selectOptions(screen.getByLabelText("الـSales 2"), "8");
    // An empty percent shows what it will count at: Walker's own rate.
    expect(screen.getByLabelText("العمولة 2")).toHaveAttribute("placeholder", "7");
    await user.type(screen.getByLabelText("العمولة 2"), "2.5");
    expect(screen.getByText("مجموع النسب 8.5%")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "احفظ الصفقة" }));
    await waitFor(() =>
      expect(posted(mocked.calls, "/api/v1/commissions/deals/3/")).toEqual([
        { value: "9500", currency: "USD", invoice: 11, people: [{ person: 7, rate: "6" }, { person: 8, rate: "2.5" }] },
      ]),
    );
  });

  it("offers «Approve» only when the invoice is paid, then «Paid» and «Take back»", async () => {
    const user = userEvent.setup();
    const mocked = serve(
      answer({
        deals: [
          deal(),
          deal({ id: 5, code: "DEAL-0005", stage: "waiting", paid: false, lines: [line({ id: 5, code: "COM-0005" })] }),
          deal({ id: 6, code: "DEAL-0006", stage: "approved", lines: [line({ id: 6, code: "COM-0006", status: "approved" })] }),
        ],
      }),
    );
    open();
    await user.click((await card("DEAL-0003")).getByRole("button", { name: "اعتمد" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/commissions/4/approve/")).toEqual([{}]));
    expect((await card("DEAL-0005")).queryByRole("button", { name: "اعتمد" })).toBeNull();
    const approved = await card("DEAL-0006");
    await user.click(approved.getByRole("button", { name: "اتصرفت" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/commissions/6/paid/")).toEqual([{}]));
    expect(approved.getByRole("button", { name: "رجّعها" })).toBeInTheDocument();
    // A deal with an approved line is not set up again nor cancelled.
    expect(approved.queryByRole("button", { name: "ظبّط الصفقة" })).toBeNull();
    expect(approved.queryByRole("button", { name: "الغي الصفقة" })).toBeNull();
  });

  it("cancels a deal after asking", async () => {
    const user = userEvent.setup();
    const mocked = serve(answer());
    open();
    await user.click((await card("DEAL-0003")).getByRole("button", { name: "الغي الصفقة" }));
    expect(posted(mocked.calls, "/api/v1/commissions/deals/3/cancel/")).toEqual([]);
    const dialog = within(screen.getByRole("dialog"));
    await user.click(dialog.getByRole("button", { name: "الغي الصفقة" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/commissions/deals/3/cancel/")).toEqual([{}]));
  });

  it("makes a deal of an invoice on none", async () => {
    const user = userEvent.setup();
    const mocked = serve(answer());
    open();
    const row = within((await screen.findByText("INV-0011")).closest("li") as HTMLElement);
    await user.click(row.getByRole("button", { name: "اعمل صفقة منها" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/commissions/invoices/11/deal/")).toEqual([{}]));
  });

  it("asks for the stage it shows", async () => {
    const user = userEvent.setup();
    const mocked = serve(answer());
    open();
    await user.selectOptions(await screen.findByLabelText("اعرض"), "due");
    await waitFor(() => expect(mocked.calls.some((call) => call.url === "/api/v1/commissions/?stage=due")).toBe(true));
  });

  it("shows a Sales person their own lines with no button and no rates", async () => {
    serve(answer({ can_manage: false, company_rate: null, people: [], uncovered: [] }), { role: "sales" });
    open();
    expect(await screen.findByText("عمولاتي", { selector: "h1" })).toBeInTheDocument();
    expect(screen.getByText("COM-0004")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "اعتمد" })).toBeNull();
    expect(screen.queryByRole("button", { name: "ظبّط الصفقة" })).toBeNull();
    expect(screen.queryByText("نسب العمولة")).toBeNull();
  });

  it("sends anybody else home", async () => {
    serve(answer(), { role: "operation" });
    open();
    expect(await screen.findByText("home page")).toBeInTheDocument();
  });
});
