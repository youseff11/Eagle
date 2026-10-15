import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { KpiCounts } from "../api/b2b";
import type { CeoBoard } from "../api/ceo";
import type { Role } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { CeoBoardPage } from "./CeoBoardPage";

afterEach(() => vi.unstubAllGlobals());

const counts: KpiCounts = {
  new_leads: 12, contacted: 9, whatsapp: 4, failed: 0, emails: 7, calls: 3, replies: 2, visits: 1, won: 1, lost: 1,
  follow_ups_on_time: 1, follow_ups_late: 0, follow_ups_missed: 0, overdue_now: 0, holding: 20, untouched: 5,
  quotations: 3, quotes_accepted: 1, revenue: { USD: "80.00" }, conversion_rate: 50, follow_up_rate: 100,
};

function board(over: Partial<CeoBoard> = {}): CeoBoard {
  return {
    ok: true,
    from: "2026-10-01",
    to: "2026-10-11",
    sales: { today: { won: 1, won_value: { USD: "80.00", EUR: "100.00" } }, period: counts, people: [{ person: { id: 7, name: "Seller", active: true }, ...counts }] },
    projects: { active: 4, late: 1, delivered: 2, words_delivered: 3000, rework_rate: null, review_score: null, complaints: 0, complaints_open: 0 },
    workload: { translators: [{ id: 3, name: "Busy Tr", tasks: 2, words: 1500 }], free: 4 },
    money: {
      invoiced: { USD: "80.00" }, received: {}, owed: { USD: "80.00" }, overdue: {}, overdue_count: 0, drafts: 1,
      revenue_egp: "4000.00", costs_egp: null, profit_egp: null, margin: null, invoices: 1,
    },
    by_project: [{ invoice: "INV-0001", invoice_id: 5, task: "TSK-00010", client: "CL-0042", amount: "80.00", currency: "USD", price_egp: "4000.00", profit_egp: null, margin: null }],
    by_client: [{ code: "CL-0042", name: "Lingua GmbH", invoices: 1, invoiced: { USD: "80.00" }, revenue_egp: "4000.00", profit_egp: null }],
    ...over,
  };
}

function serve(who: Role, answer: (url: URL) => Response) {
  const mocked = mockFetch({ "/api/v1/me/": () => jsonResponse(me({ role: who, is_admin: who === "admin" })), "/api/v1/admin/ceo/": answer });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function open(route = "/admin/ceo") {
  return renderWithProviders(
    <Routes>
      <Route path="/admin/ceo" element={<CeoBoardPage />} />
      <Route path="/" element={<div>home page</div>} />
    </Routes>,
    { route },
  );
}

describe("CeoBoardPage", () => {
  it("shows the money per currency, never added together, and «مش متقاس» for what is not known", async () => {
    serve("admin", () => jsonResponse(board()));
    const { container } = open();
    await screen.findByText("Busy Tr");
    const today = container.querySelector('[data-ceo="won_today"]') as HTMLElement;
    expect(today).toHaveTextContent("80.00 USD");
    expect(today).toHaveTextContent("100.00 EUR");
    expect(container.querySelector('[data-ceo="revenue"]')).toHaveTextContent("4,000.00");
    expect(container.querySelector('[data-ceo="profit"]')).toHaveTextContent("مش متقاس");
    expect(container.querySelector('[data-ceo="rework"]')).toHaveTextContent("مش متقاس");
    expect(container.querySelector('[data-ceo-client="CL-0042"]')).toHaveTextContent("Lingua GmbH");
    expect(container.querySelector('[data-ceo-project="INV-0001"] a')).toHaveAttribute("href", "/accounts/invoices/5");
  });

  it("asks for the period chosen", async () => {
    const user = userEvent.setup();
    const mocked = serve("admin", () => jsonResponse(board()));
    open();
    await user.click(await screen.findByRole("button", { name: "الشهر اللي فات" }));
    await waitFor(() => expect(mocked.calls.some((call) => /\/api\/v1\/admin\/ceo\/\?from=\d{4}-\d{2}-01&to=/.test(call.url))).toBe(true));
  });

  it("is the owner's alone: anybody else goes home without asking", async () => {
    for (const role of ["accounting", "sales"] as Role[]) {
      const mocked = serve(role, () => jsonResponse(board()));
      const view = open();
      expect(await screen.findByText("home page")).toBeInTheDocument();
      expect(mocked.calls.some((call) => call.url.startsWith("/api/v1/admin/ceo/"))).toBe(false);
      view.unmount();
      vi.unstubAllGlobals();
    }
  });
});
