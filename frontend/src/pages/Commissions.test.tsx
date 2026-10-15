import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CommissionLine, CommissionsResponse } from "../api/commissions";
import { ToastProvider } from "../components/Toasts";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { CommissionsPage } from "./CommissionsPage";

/** The commissions page (15/10/2026): the owner's rates, split and buttons drawn from what the server says, and the Sales
 * person's own lines with no button at all. */

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

const posted = (calls: { url: string; init?: RequestInit }[], url: string) =>
  calls.filter((call) => call.url === url && call.init?.method === "POST").map((call) => JSON.parse(String(call.init?.body)));

function line(over: Partial<CommissionLine> = {}): CommissionLine {
  return {
    id: 4, code: "COM-0004", invoice: { id: 9, code: "INV-0009", status: "paid", amount: "10000.00", currency: "USD", client_code: "CL-0003" },
    person: { id: 7, name: "Abroad" }, share: "100.00", rate: "5.00", own_rate: false, status: "pending", amount: "500.00", currency: "USD",
    amount_egp: "25000.00", due: true, approved_by: null, approved_at: "", paid_at: "", note: "", ...over,
  };
}

function answer(over: Partial<CommissionsResponse> = {}): CommissionsResponse {
  return {
    ok: true, can_manage: true, lines: [line()],
    totals: { waiting: "0.00", due: "25000.00", approved: "0.00", paid: "0.00", unknown: 0 },
    company_rate: "5.00",
    people: [{ id: 7, name: "Abroad", rate: null, track: "b2b" }, { id: 8, name: "Walker", rate: "7.00", track: "b2c_field" }],
    uncovered: [], ...over,
  };
}

function serve(body: CommissionsResponse, who: Record<string, unknown> = { role: "admin", is_admin: true }) {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me(who)),
    "/api/v1/commissions/": (_url, init) => (init?.method === "POST" ? jsonResponse({ ok: true }) : jsonResponse(body)),
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

describe("CommissionsPage", () => {
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

  it("offers «Approve» only on a due line, then «Paid» and «Take back»", async () => {
    const user = userEvent.setup();
    const mocked = serve(answer({ lines: [line(), line({ id: 5, code: "COM-0005", due: false }), line({ id: 6, code: "COM-0006", status: "approved" })] }));
    open();
    const due = within((await screen.findByText("COM-0004")).closest("tr") as HTMLElement);
    await user.click(due.getByRole("button", { name: "اعتمد" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/commissions/4/approve/")).toEqual([{}]));
    expect(within(screen.getByText("COM-0005").closest("tr") as HTMLElement).queryByRole("button", { name: "اعتمد" })).toBeNull();
    const approved = within(screen.getByText("COM-0006").closest("tr") as HTMLElement);
    await user.click(approved.getByRole("button", { name: "اتصرفت" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/commissions/6/paid/")).toEqual([{}]));
    expect(approved.getByRole("button", { name: "رجّعها" })).toBeInTheDocument();
  });

  it("splits a deal and sends each person's share", async () => {
    const user = userEvent.setup();
    const mocked = serve(answer());
    open();
    await user.click(within((await screen.findByText("COM-0004")).closest("tr") as HTMLElement).getByRole("button", { name: "قسّم" }));
    await user.clear(screen.getByLabelText("النصيب 1"));
    await user.type(screen.getByLabelText("النصيب 1"), "60");
    await user.click(screen.getByRole("button", { name: "ضيف شخص" }));
    await user.selectOptions(screen.getByLabelText("الشخص 2"), "8");
    await user.type(screen.getByLabelText("النصيب 2"), "40");
    expect(screen.getByText("المجموع 100%")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "احفظ التقسيم" }));
    await waitFor(() =>
      expect(posted(mocked.calls, "/api/v1/commissions/invoices/9/split/")).toEqual([{ shares: [{ person: 7, share: "60" }, { person: 8, share: "40" }] }]),
    );
  });

  it("shows a Sales person their own lines with no button and no rates", async () => {
    serve(answer({ can_manage: false, company_rate: null, people: [] }), { role: "sales" });
    open();
    expect(await screen.findByText("عمولاتي", { selector: "h1" })).toBeInTheDocument();
    expect(screen.getByText("COM-0004")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "اعتمد" })).toBeNull();
    expect(screen.queryByText("نسب العمولة")).toBeNull();
  });

  it("sends anybody else home", async () => {
    serve(answer(), { role: "operation" });
    open();
    expect(await screen.findByText("home page")).toBeInTheDocument();
  });
});
