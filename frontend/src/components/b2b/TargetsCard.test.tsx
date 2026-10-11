import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TargetRow, TargetsResponse } from "../../api/b2b";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../../test/helpers";
import { TargetsCard } from "./TargetsCard";

afterEach(() => vi.unstubAllGlobals());

const none = { target: null, done: 0, percent: null };

function row(over: Partial<TargetRow["progress"]> = {}): TargetRow {
  return {
    person: { id: 7, name: "Seller" },
    currency: "USD",
    progress: {
      new_leads: { target: 10, done: 5, percent: 50 },
      contacted: none,
      quotations: none,
      won: { target: 2, done: 2, percent: 100 },
      revenue: { target: "1000.00", done: "250.00", percent: 25 },
      ...over,
    },
  };
}

function answer(over: Partial<TargetsResponse> = {}): TargetsResponse {
  return {
    ok: true,
    month: "2026-10",
    can_edit: false,
    metrics: ["new_leads", "contacted", "quotations", "won", "revenue"],
    currencies: ["USD", "EUR"],
    rows: [row()],
    ...over,
  };
}

function serve(body: TargetsResponse, extra: Record<string, () => Response> = {}) {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role: "sales" })),
    ...extra,
    "/api/v1/b2b/targets/": () => jsonResponse(body),
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

const posted = (calls: { url: string; init?: RequestInit }[], url: string) =>
  calls.filter((call) => call.url === url && call.init?.method === "POST").map((call) => JSON.parse(String(call.init?.body)));

describe("TargetsCard", () => {
  it("shows a Sales person how far they are, and a dash where there is no target", async () => {
    serve(answer());
    const { container } = renderWithProviders(<TargetsCard />);
    expect(await screen.findByText("التارجت بتاعك")).toBeInTheDocument();
    const mine = container.querySelector('[data-target="7"]') as HTMLElement;
    expect(within(mine).getByText("5 / 10")).toBeInTheDocument();
    expect(mine.querySelector('[data-metric="contacted"]')).toHaveTextContent("—");
    expect(mine.querySelector('[data-metric="contacted"]')).not.toHaveTextContent("0%");
    expect(screen.queryByRole("button", { name: "حدد التارجت" })).toBeNull();
  });

  it("lets the manager set a person's target, blank boxes being no target", async () => {
    const user = userEvent.setup();
    const mocked = serve(answer({ can_edit: true }), {
      "/api/v1/b2b/targets/save/": () => jsonResponse({ ok: true, rows: [row()] }),
    });
    renderWithProviders(<TargetsCard />);
    await user.click(await screen.findByRole("button", { name: "حدد التارجت" }));
    const quotations = screen.getByLabelText("عروض اتبعتت");
    await user.type(quotations, "6");
    await user.clear(screen.getByLabelText("شركات جديدة"));
    await user.click(screen.getByRole("button", { name: "احفظ التارجت" }));
    await waitFor(() => expect(posted(mocked.calls, "/api/v1/b2b/targets/save/")).toHaveLength(1));
    expect(posted(mocked.calls, "/api/v1/b2b/targets/save/")[0]).toEqual({
      person: 7, month: "2026-10", new_leads: null, contacted: null, quotations: 6, won: 2, revenue: "1000.00", revenue_currency: "USD",
    });
  });

  it("asks for the month chosen", async () => {
    const mocked = serve(answer());
    renderWithProviders(<TargetsCard />);
    // A month box is not typed into the same way by every browser: the value is set, as a picker sets it.
    fireEvent.change(await screen.findByLabelText("الشهر"), { target: { value: "2026-09" } });
    await waitFor(() => expect(mocked.calls.some((call) => call.url === "/api/v1/b2b/targets/?month=2026-09")).toBe(true));
  });
});
