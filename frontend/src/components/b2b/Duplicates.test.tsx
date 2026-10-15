import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { B2bLead } from "../../api/b2b";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../../test/helpers";
import { Duplicates } from "./Duplicates";

afterEach(() => vi.unstubAllGlobals());

function lead(id: number, company_name: string, over: Partial<B2bLead> = {}): B2bLead {
  return {
    id, company_name, country: "", website: "", industry: "", contact_person: "", position: "", email: "", phone: "", whatsapp: "",
    linkedin: "", languages: "", services: "", source: "", status: "new", priority: "", deal_value: "", phones: [],
    next_follow_up: "", notes: [], client_code: "", whatsapp_at: "", email_at: "", call_at: "", last_contact_at: "",
    replied_at: "", last_outreach_at: "", follow_up: "", overdue: false, quote: null, governorate: "", address: "", location: "",
    map_link: "", customer_type: "", lost_reason: "", ...over,
  };
}

const LEADS = [
  lead(1, "GEM86", { phones: ["34968214882"], status: "contacted" }),
  lead(2, "GEM 86", { phones: ["34968214882"] }),
  lead(3, "gem86.", { email: "gempt@gem86.com" }),
  lead(7, "Geo Translations"),
  lead(8, "Geo  Translations"),
];

function serve(groups: unknown[]) {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role: "sales" })),
    // Routes match by prefix: the longer address first.
    "/api/v1/b2b/sheets/4/duplicates/remove/": () => jsonResponse({ ok: true, removed: 1 }),
    "/api/v1/b2b/sheets/4/duplicates/": () => jsonResponse({ ok: true, groups }),
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

const removes = (calls: { url: string; init?: RequestInit }[]) =>
  calls.filter((call) => call.url === "/api/v1/b2b/sheets/4/duplicates/remove/" && call.init?.method === "POST").map((call) => JSON.parse(String(call.init?.body)));

describe("Duplicates", () => {
  it("shows each company that is there twice and deletes the ticked copies, keeping the row picked", async () => {
    const user = userEvent.setup();
    const mocked = serve([
      { ids: [1, 2, 3], keep: 1, why: ["phone", "name"] },
      { ids: [7, 8], keep: 7, why: ["name"] },
    ]);
    renderWithProviders(<Duplicates sheetId={4} leads={LEADS} onClose={() => undefined} />);
    expect(await screen.findByRole("button", { name: "امسح كل المكرر (3)" })).toBeInTheDocument();
    expect(screen.getByText("نفس الرقم")).toBeInTheDocument();
    // The suggested row stays and cannot be ticked; one copy is unticked by hand; then the second row is picked to stay.
    expect(screen.getByLabelText("امسح GEM86")).toBeDisabled();
    await user.click(screen.getByLabelText("امسح gem86."));
    expect(screen.getByRole("button", { name: "امسح كل المكرر (2)" })).toBeInTheDocument();
    await user.click(screen.getByLabelText("GEM 86 يفضل"));
    expect(screen.getByLabelText("امسح GEM86")).toBeChecked();
    await user.click(screen.getAllByRole("button", { name: /^امسح \(/ })[0]!);
    await waitFor(() => expect(removes(mocked.calls)).toHaveLength(1));
    expect(removes(mocked.calls)[0]).toEqual({ keep: 2, remove: [1, 3] });
    expect(await screen.findByText(/اتمسح 1 صف مكرر/)).toBeInTheDocument();
  });

  it("deletes every group with one press, one group at a time", async () => {
    const user = userEvent.setup();
    const mocked = serve([
      { ids: [1, 2, 3], keep: 1, why: ["phone"] },
      { ids: [7, 8], keep: 7, why: ["name"] },
    ]);
    renderWithProviders(<Duplicates sheetId={4} leads={LEADS} onClose={() => undefined} />);
    await user.click(await screen.findByRole("button", { name: "امسح كل المكرر (3)" }));
    await waitFor(() => expect(removes(mocked.calls)).toHaveLength(2));
    expect(removes(mocked.calls)).toEqual([
      { keep: 1, remove: [2, 3] },
      { keep: 7, remove: [8] },
    ]);
  });

  it("says so when there is nothing twice", async () => {
    serve([]);
    renderWithProviders(<Duplicates sheetId={4} leads={LEADS} onClose={() => undefined} />);
    expect(await screen.findByText("مفيش صفوف مكررة في الشيت ده.")).toBeInTheDocument();
  });
});
