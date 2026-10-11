import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { InvoiceDetail, InvoiceResponse, InvoiceRow, InvoicesResponse } from "../api/finance";
import type { Role } from "../api/types";
import { ToastProvider } from "../components/Toasts";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { AccountsInvoicePage } from "./AccountsInvoicePage";
import { AccountsInvoicesPage } from "./AccountsInvoicesPage";

afterEach(() => vi.unstubAllGlobals());

function row(over: Partial<InvoiceRow> = {}): InvoiceRow {
  return {
    id: 3,
    code: "INV-0001",
    client_code: "CL-0042",
    task: "TSK-00010",
    quotation: "QT-0001",
    amount: "80.00",
    paid: "0.00",
    left: "80.00",
    currency: "USD",
    status: "draft",
    overdue: false,
    issue_date: "2026-10-11",
    due_date: "2026-10-25",
    sent_at: "",
    sales: "Seller",
    ...over,
  };
}

function detail(over: Partial<InvoiceDetail> = {}): InvoiceResponse {
  return {
    ok: true,
    invoice: {
      ...row(),
      client: { code: "CL-0042" },
      egp_rate: "50",
      payment_terms: "",
      notes: "",
      payments: [],
      costs: [{ id: 9, kind: "translator", person: "Tr", description: "", words: 1000, rate_per_250: "50.00", amount: "200.00", automatic: true }],
      profit: { price_egp: "4000.00", costs: "200.00", profit: "3800.00", margin: 95, currency: "EGP" },
      ...over,
    },
    cost_kinds: [{ value: "reviewer", label: "Reviewer" }],
    currencies: ["USD", "EGP"],
  };
}

function list(over: Partial<InvoicesResponse> = {}): InvoicesResponse {
  return {
    ok: true,
    show: "all",
    invoices: [row(), row({ id: 4, code: "INV-0002", status: "sent", overdue: true })],
    owed: { USD: "80.00" },
    uninvoiced: [{ code: "TSK-00011", client_code: "CL-0050", title: "WhatsApp job", delivered_at: "11/10/2026 1:00 PM", words: 500 }],
    currencies: ["USD", "EGP"],
    ...over,
  };
}

function serve(who: Role, routes: Record<string, (url: URL, init?: RequestInit) => Response>) {
  const mocked = mockFetch({ "/api/v1/me/": () => jsonResponse(me({ role: who, is_admin: who === "admin" })), ...routes });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function open(route: string) {
  return renderWithProviders(
    <ToastProvider>
      <Routes>
        <Route path="/accounts/invoices" element={<AccountsInvoicesPage />} />
        <Route path="/accounts/invoices/:id" element={<AccountsInvoicePage />} />
        <Route path="/" element={<div>home page</div>} />
      </Routes>
    </ToastProvider>,
    { route },
  );
}

const posted = (calls: { url: string; init?: RequestInit }[], url: string) =>
  calls.filter((call) => call.url === url && call.init?.method === "POST").map((call) => JSON.parse(String(call.init?.body)));

describe("AccountsInvoicesPage", () => {
  it("lists the invoices with what is owed per currency, an overdue one in red", async () => {
    serve("accounting", { "/api/v1/finance/invoices/": () => jsonResponse(list()) });
    const { container } = open("/accounts/invoices");
    expect(await screen.findByText("INV-0002")).toBeInTheDocument();
    expect(container.querySelector('[data-owed="USD"]')).toHaveTextContent("80.00 USD");
    expect(within(container.querySelector('[data-invoice="INV-0002"]') as HTMLElement).getByText("متأخرة")).toBeInTheDocument();
  });

  it("asks for the filter chosen", async () => {
    const user = userEvent.setup();
    const mocked = serve("accounting", { "/api/v1/finance/invoices/": () => jsonResponse(list()) });
    open("/accounts/invoices");
    await screen.findByText("INV-0001");
    await user.click(screen.getByRole("button", { name: "متأخرة" }));
    await waitFor(() => expect(mocked.calls.some((call) => call.url === "/api/v1/finance/invoices/?show=overdue")).toBe(true));
  });

  it("invoices by hand a delivered task with no quotation", async () => {
    const user = userEvent.setup();
    const mocked = serve("accounting", {
      "/api/v1/finance/tasks/TSK-00011/invoice/": () => jsonResponse({ ok: true, invoice: { ...detail().invoice, id: 8 } }),
      "/api/v1/finance/invoices/8/": () => jsonResponse(detail({ id: 8 })),
      "/api/v1/finance/invoices/": () => jsonResponse(list()),
    });
    open("/accounts/invoices");
    await user.click(await screen.findByRole("button", { name: "اعمل فاتورة" }));
    await user.type(screen.getByLabelText("المبلغ"), "150");
    await user.selectOptions(screen.getByLabelText("العملة"), "EGP");
    await user.click(screen.getByRole("button", { name: "اعمل الفاتورة" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/finance/tasks/TSK-00011/invoice/")).toEqual([{ amount: "150", currency: "EGP" }]));
  });

  it("sends anybody else home without asking", async () => {
    const mocked = serve("sales", {});
    open("/accounts/invoices");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(mocked.calls.some((call) => call.url.startsWith("/api/v1/finance/"))).toBe(false);
  });
});

describe("AccountsInvoicePage", () => {
  it("shows the profit, and «مش متقاس» for what cannot be known yet", async () => {
    serve("accounting", {
      "/api/v1/finance/invoices/3/": () =>
        jsonResponse(detail({ profit: { price_egp: "4000.00", costs: null, profit: null, margin: null, currency: "EGP" } })),
    });
    const { container } = open("/accounts/invoices/3");
    await screen.findByText("INV-0001");
    expect(container.querySelector('[data-profit="price"]')).toHaveTextContent("4000.00");
    expect(container.querySelector('[data-profit="profit"]')).toHaveTextContent("مش متقاس");
    expect(container.querySelector('[data-profit="margin"]')).toHaveTextContent("مش متقاس");
  });

  it("sends a draft, and shows the server's reason when it is refused", async () => {
    const user = userEvent.setup();
    const mocked = serve("accounting", {
      "/api/v1/finance/invoices/3/send/": () => jsonResponse({ ok: false, error: "no_rate", message: "اكتب سعر الصرف الأول.", message_en: "x" }, 400),
      "/api/v1/finance/invoices/3/": () => jsonResponse(detail()),
    });
    open("/accounts/invoices/3");
    await user.click(await screen.findByRole("button", { name: "ابعت الفاتورة للعميل" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("اكتب سعر الصرف الأول.");
    expect(posted(mocked.calls, "/api/v1/finance/invoices/3/send/")).toHaveLength(1);
  });

  it("records a payment on a sent invoice", async () => {
    const user = userEvent.setup();
    const mocked = serve("accounting", {
      "/api/v1/finance/invoices/3/payments/": () => jsonResponse({ ok: true, invoice: detail({ status: "partial" }).invoice }),
      "/api/v1/finance/invoices/3/": () => jsonResponse(detail({ status: "sent" })),
    });
    open("/accounts/invoices/3");
    await user.type(await screen.findByLabelText("المبلغ اللي اتدفع"), "30");
    await user.type(screen.getByLabelText("الطريقة"), "Wise");
    await user.click(screen.getByRole("button", { name: "سجّل الدفع" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/finance/invoices/3/payments/")).toEqual([{ amount: "30", paid_on: "", method: "Wise", note: "" }]));
    expect(screen.queryByRole("button", { name: "ابعت الفاتورة للعميل" })).toBeNull();
  });

  it("locks the amount once sent, and names the client only when the server sends the name", async () => {
    serve("accounting", { "/api/v1/finance/invoices/3/": () => jsonResponse(detail({ status: "sent" })) });
    open("/accounts/invoices/3");
    expect(await screen.findByLabelText("المبلغ")).toBeDisabled();
    expect(screen.queryByText(/Lingua/)).toBeNull();
    vi.unstubAllGlobals();
  });

  it("shows the client's company to who may see it", async () => {
    serve("admin", { "/api/v1/finance/invoices/3/": () => jsonResponse(detail({ client: { code: "CL-0042", company: "Lingua GmbH", name: "Anna", email: "a@l.test" } })) });
    open("/accounts/invoices/3");
    expect(await screen.findByText(/Lingua GmbH/)).toBeInTheDocument();
  });

  it("gives a cost its amount", async () => {
    const user = userEvent.setup();
    const mocked = serve("accounting", {
      "/api/v1/finance/costs/9/save/": () => jsonResponse({ ok: true, invoice: detail().invoice }),
      "/api/v1/finance/invoices/3/": () => jsonResponse(detail({ costs: [{ id: 9, kind: "translator", person: "Tr2", description: "", words: 400, rate_per_250: null, amount: null, automatic: true }] })),
    });
    const { container } = open("/accounts/invoices/3");
    await screen.findByText("Tr2");
    const cost = container.querySelector('[data-cost="9"]') as HTMLElement;
    await user.type(within(cost).getByLabelText("المبلغ بالجنيه"), "90");
    await user.click(within(cost).getByRole("button", { name: "احفظ" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/finance/costs/9/save/")).toEqual([{ amount: "90", description: "" }]));
  });
});
