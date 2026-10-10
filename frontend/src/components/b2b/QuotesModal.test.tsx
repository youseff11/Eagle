import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Quotation, QuotationsResponse } from "../../api/b2b";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../../test/helpers";
import { QuotesModal } from "./QuotesModal";

afterEach(() => vi.unstubAllGlobals());

function quote(over: Partial<Quotation> = {}): Quotation {
  return {
    id: 1,
    code: "QT-0001",
    status: "draft",
    source_lang: "EN",
    target_lang: "AR",
    service: "translation",
    unit: "words",
    quantity: 1000,
    rate: "0.08",
    discount_percent: "10",
    total: "72.00",
    currency: "USD",
    deadline: "",
    payment_terms: "",
    notes: "",
    created_at: "10/10/2026 1:00 PM",
    sent_at: "",
    decided_at: "",
    task: "",
    ...over,
  };
}

function answer(over: Partial<QuotationsResponse> = {}): QuotationsResponse {
  return {
    ok: true,
    lead: { id: 5, company_name: "Lingua GmbH", contact_person: "Anna", email: "anna@lingua.test" },
    quotations: [quote()],
    can_make: true,
    can_decide: true,
    services: [{ value: "translation", label: "Translation" }],
    units: [{ value: "words", label: "Words" }],
    currencies: ["USD", "EUR"],
    languages: [{ code: "EN", ar: "الإنجليزية", en: "English" }],
    ...over,
  };
}

function serve(body: QuotationsResponse, extra: Record<string, () => Response> = {}) {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role: "sales" })),
    ...extra,
    "/api/v1/b2b/leads/5/quotations/": () => jsonResponse(body),
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

const posted = (calls: { url: string; init?: RequestInit }[], url: string) =>
  calls.filter((call) => call.url === url && call.init?.method === "POST").map((call) => JSON.parse(String(call.init?.body)));

function open() {
  return renderWithProviders(<QuotesModal leadId={5} onClose={() => undefined} />);
}

describe("QuotesModal", () => {
  it("makes a draft with the figures typed, and shows the total they make", async () => {
    const user = userEvent.setup();
    const mocked = serve(answer({ quotations: [] }), {
      "/api/v1/b2b/leads/5/quotations/new/": () => jsonResponse({ ok: true, quotation: quote() }),
    });
    open();
    await user.click(await screen.findByRole("button", { name: "عرض سعر جديد" }));
    await user.type(screen.getByLabelText("الكمية"), "1000");
    await user.type(screen.getByLabelText("سعر الوحدة"), "0.08");
    await user.clear(screen.getByLabelText("الخصم %"));
    await user.type(screen.getByLabelText("الخصم %"), "10");
    expect(document.querySelector("[data-quote-total]")).toHaveTextContent("72.00 USD");
    await user.click(screen.getByRole("button", { name: "اعمل المسودة" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/leads/5/quotations/new/")).toHaveLength(1));
    expect(posted(mocked.calls, "/api/v1/b2b/leads/5/quotations/new/")[0]).toMatchObject({
      source_lang: "EN", target_lang: "AR", quantity: 1000, rate: "0.08", discount_percent: "10", currency: "USD",
    });
  });

  it("sends a draft, and a sent one is answered: accepted or turned down", async () => {
    const user = userEvent.setup();
    const mocked = serve(answer({ quotations: [quote(), quote({ id: 2, code: "QT-0002", status: "sent" })] }), {
      "/api/v1/b2b/quotations/1/send/": () => jsonResponse({ ok: true, quotation: quote({ status: "sent" }) }),
      "/api/v1/b2b/quotations/2/decide/": () => jsonResponse({ ok: true, quotation: quote({ id: 2, status: "accepted" }) }),
    });
    const { container } = open();
    await screen.findByText("QT-0002");
    const draft = container.querySelector('[data-quotation="QT-0001"]') as HTMLElement;
    expect(within(draft).queryByRole("button", { name: "اتقبل" })).toBeNull();
    await user.click(within(draft).getByRole("button", { name: "ابعته" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/quotations/1/send/")).toHaveLength(1));
    const sentRow = container.querySelector('[data-quotation="QT-0002"]') as HTMLElement;
    expect(within(sentRow).queryByRole("button", { name: "ابعته" })).toBeNull();
    expect(within(sentRow).queryByRole("button", { name: "عدّل" })).toBeNull();
    await user.click(within(sentRow).getByRole("button", { name: "اتقبل" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/quotations/2/decide/")).toEqual([{ accepted: true }]));
  });

  it("gives the manager the answer buttons only, nothing to make or send", async () => {
    serve(answer({ can_make: false, quotations: [quote(), quote({ id: 2, code: "QT-0002", status: "sent" })] }));
    const { container } = open();
    await screen.findByText("QT-0002");
    expect(screen.queryByRole("button", { name: "عرض سعر جديد" })).toBeNull();
    expect(within(container.querySelector('[data-quotation="QT-0001"]') as HTMLElement).queryByRole("button", { name: "ابعته" })).toBeNull();
    expect(within(container.querySelector('[data-quotation="QT-0002"]') as HTMLElement).getByRole("button", { name: "اتقبل" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "نسخة جديدة" })).toBeNull();
  });

  it("will not send to a company with no e-mail, and says why", async () => {
    serve(answer({ lead: { id: 5, company_name: "Lingua GmbH", contact_person: "Anna", email: "" } }));
    open();
    expect(await screen.findByRole("button", { name: "ابعته" })).toBeDisabled();
    expect(screen.getByText(/الشركة مالهاش إيميل في الشيت/)).toBeInTheDocument();
  });

  it("shows the server's reason when a send is refused", async () => {
    const user = userEvent.setup();
    serve(answer(), {
      "/api/v1/b2b/quotations/1/send/": () => jsonResponse({ ok: false, error: "not_draft", message: "العرض ده اتبعت قبل كده.", message_en: "x" }, 400),
    });
    open();
    await user.click(await screen.findByRole("button", { name: "ابعته" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("العرض ده اتبعت قبل كده.");
  });
});
