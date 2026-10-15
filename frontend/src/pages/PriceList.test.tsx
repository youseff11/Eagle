import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PriceListResponse } from "../api/pricing";
import { ToastProvider } from "../components/Toasts";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { PriceListPage } from "./PriceListPage";

/** The price list page (part 4, 15/10/2026): the list in force and its versions, the owner's editor and limits, and the
 * discounts waiting for whoever may approve them. */

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

const posted = (calls: { url: string; init?: RequestInit }[], url: string) =>
  calls.filter((call) => call.url === url && call.init?.method === "POST").map((call) => JSON.parse(String(call.init?.body)));

function answer(over: Partial<PriceListResponse> = {}): PriceListResponse {
  return {
    ok: true, can_edit: true,
    list: { id: 2, version: 2, note: "2027", created_at: "15/10/2026", items: [{ service: "translation", unit: "words", currency: "USD", pair: "EN>AR", rate: "0.1" }] },
    current: 2,
    versions: [{ version: 2, created_at: "15/10/2026", note: "2027" }, { version: 1, created_at: "01/10/2026", note: "" }],
    limits: { sales: "10.00", manager: "20.00", mine: "100.00" },
    waiting: [],
    services: [{ value: "translation", label: "Translation" }, { value: "review", label: "Proofreading / review" }],
    units: [{ value: "words", label: "Words" }],
    currencies: ["USD", "EGP"],
    ...over,
  };
}

function serve(body: PriceListResponse, who: Record<string, unknown> = { role: "admin", is_admin: true }) {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me(who)),
    "/api/v1/b2b/price-list/": (_url, init) => (init?.method === "POST" ? jsonResponse({ ok: true, state: "approved" }) : jsonResponse(body)),
    "/api/v1/b2b/quotations/": () => jsonResponse({ ok: true, state: "approved" }),
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function open() {
  return renderWithProviders(
    <ToastProvider>
      <Routes>
        <Route path="/price-list" element={<PriceListPage />} />
        <Route path="/" element={<div>home page</div>} />
      </Routes>
    </ToastProvider>,
    { route: "/price-list" },
  );
}

describe("PriceListPage", () => {
  it("saves the owner's edit as a new version", async () => {
    const user = userEvent.setup();
    const mocked = serve(answer());
    open();
    await user.click(await screen.findByRole("button", { name: "عدّل القايمة" }));
    await user.clear(screen.getByLabelText("السعر 1"));
    await user.type(screen.getByLabelText("السعر 1"), "0.12");
    await user.click(screen.getByRole("button", { name: "ضيف سعر" }));
    await user.type(screen.getByLabelText("السعر 2"), "0.15");
    await user.click(screen.getByRole("button", { name: "احفظ كإصدار جديد" }));
    await waitFor(() =>
      expect(posted(mocked.calls, "/api/v1/b2b/price-list/save/")).toEqual([
        {
          note: "",
          items: [
            { service: "translation", unit: "words", currency: "USD", pair: "EN>AR", rate: "0.12" },
            { service: "translation", unit: "words", currency: "USD", pair: "", rate: "0.15" },
          ],
        },
      ]),
    );
  });

  it("lets the owner set the limits; a Sales person only reads them and the list", async () => {
    const user = userEvent.setup();
    const mocked = serve(answer());
    const view = open();
    await user.clear(await screen.findByLabelText("حد الـSales"));
    await user.type(screen.getByLabelText("حد الـSales"), "12");
    await user.click(screen.getByRole("button", { name: "احفظ الحدود" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/price-list/limits/")).toEqual([{ sales: "12", manager: "20" }]));
    view.unmount();
    serve(answer({ can_edit: false, limits: { sales: "10.00", manager: "20.00", mine: "10.00" } }), { role: "sales" });
    open();
    expect(await screen.findByText("0.1 USD")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "عدّل القايمة" })).toBeNull();
    expect(screen.queryByLabelText("حد الـSales")).toBeNull();
  });

  it("approves a waiting discount, and turns one down only with why", async () => {
    const user = userEvent.setup();
    const waiting = {
      id: 3, code: "QT-0003", company_name: "Lingua GmbH", sheet: 4, person: "Seller", quantity: 1000, unit: "words", rate: "0.07",
      discount_percent: "0", total: "70.00", currency: "USD", list_rate: "0.1", version: 2, effective_discount: "30.00",
    };
    const mocked = serve(answer({ waiting: [waiting, { ...waiting, id: 4, code: "QT-0004" }] }));
    open();
    const first = within((await screen.findByText("QT-0003")).closest("tr") as HTMLElement);
    expect(first.getByText("30%")).toBeInTheDocument();
    await user.click(first.getByRole("button", { name: "اعتمد الخصم" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/quotations/3/discount/")).toEqual([{ approved: true, note: "" }]));
    await user.click(within(screen.getByText("QT-0004").closest("tr") as HTMLElement).getByRole("button", { name: "ارفض" }));
    await user.click(screen.getByRole("button", { name: "ارفض الخصم" }));
    expect(await screen.findByText("اكتب سبب الرفض.")).toBeInTheDocument();
    await user.type(screen.getByLabelText("سبب الرفض"), "Too low");
    await user.click(screen.getByRole("button", { name: "ارفض الخصم" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/quotations/4/discount/")).toEqual([{ approved: false, note: "Too low" }]));
  });

  it("sends anybody else home", async () => {
    serve(answer(), { role: "operation" });
    open();
    expect(await screen.findByText("home page")).toBeInTheDocument();
  });
});
