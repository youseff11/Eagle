import { screen } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Role } from "../api/types";
import type { UsageMonthCell, UsageMonths } from "../api/usageMonths";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { UsageMonthsPage } from "./UsageMonthsPage";

/** «سجل الدفع» (02/11/2026): each subscription's bill month by month and the month's total, the owner's and technical support's; what is not
 * known reads «مش متقاس», never a zero, and a total missing a host says so. */

afterEach(() => vi.unstubAllGlobals());

const HOSTS = [
  { key: "bunny", name: "Bunny.net", link: "https://dash.bunny.net/billing" },
  { key: "neon", name: "Neon", link: "https://console.neon.tech/app/billing" },
  { key: "render", name: "Render", link: "https://dashboard.render.com/billing" },
  { key: "claude", name: "Claude", link: "https://platform.claude.com/settings/billing" },
  { key: "meta", name: "WhatsApp (Meta)", link: "https://business.facebook.com/billing_hub/" },
];

function cell(over: Partial<UsageMonthCell> = {}): UsageMonthCell {
  return { state: "ok", usd: null, amount: "", estimate: false, note: null, error: "", ...over };
}

function history(): UsageMonths {
  return {
    ok: true,
    hosts: HOSTS,
    months: [
      {
        month: "2026-11", label: { ar: "نوفمبر 2026", en: "November 2026" }, running: true, closed: false,
        cells: {
          bunny: cell({ usd: 0.12 }), neon: cell({ usd: 0.5 }), render: cell({ usd: 1.0, estimate: true }),
          claude: cell({ usd: 0.03, estimate: true }), meta: cell({ state: "off" }),
        },
        total_usd: 1.65, complete: true, estimate: true, at: { ar: "02/11 11:00 ص", en: "02/11 11:00 AM" },
      },
      {
        month: "2026-10", label: { ar: "أكتوبر 2026", en: "October 2026" }, running: false, closed: true,
        cells: {
          bunny: cell({ state: "unknown" }),
          neon: cell({ usd: 5.33 }),
          render: cell({ usd: 1234.5, estimate: true }),
          claude: cell({ usd: 3, estimate: true, note: { ar: "بيتعد من 22/10", en: "Counted since 22/10" } }),
          meta: cell({ state: "error", error: "unreachable" }),
        },
        total_usd: 1242.83, complete: false, estimate: true, at: null,
      },
    ],
  };
}

function serve(who: Role) {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role: who, is_admin: who === "admin" })),
    "/api/v1/admin/usage/months/": () => jsonResponse(history()),
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function open() {
  return renderWithProviders(
    <Routes>
      <Route path="/admin/usage-months" element={<UsageMonthsPage />} />
      <Route path="/" element={<div>home page</div>} />
    </Routes>,
    { route: "/admin/usage-months" },
  );
}

describe("UsageMonthsPage", () => {
  it("draws a row a month, a column a host, and the month's total", async () => {
    serve("admin");
    const { container } = open();
    await screen.findByText("أكتوبر 2026");
    for (const host of HOSTS) expect(screen.getByRole("link", { name: host.name })).toHaveAttribute("href", host.link);
    const october = container.querySelector('[data-month="2026-10"]') as HTMLElement;
    expect(october.querySelector('[data-host="neon"]')).toHaveTextContent("$5.33");
    expect(october.querySelector('[data-host="render"]')).toHaveTextContent("≈ $1,234.50");
    expect(october.querySelector('[data-host="claude"]')).toHaveTextContent("بيتعد من 22/10");
    expect(october.querySelector("[data-total]")).toHaveTextContent("≈ $1,242.83");
    const november = container.querySelector('[data-month="2026-11"]') as HTMLElement;
    expect(november).toHaveTextContent("لحد 02/11 11:00 ص");
    expect(november.querySelector('[data-host="meta"]')).toHaveTextContent("مش متربط");
    expect(november.querySelector("[data-total]")).not.toHaveTextContent("من غير اللي مش متقاس");
  });

  it("reads «مش متقاس» for what is not known, never a zero, and says the total is missing it", async () => {
    serve("admin");
    const { container } = open();
    await screen.findByText("أكتوبر 2026");
    const october = container.querySelector('[data-month="2026-10"]') as HTMLElement;
    expect(october.querySelector('[data-host="bunny"]')).toHaveTextContent("مش متقاس");
    expect(october.querySelector('[data-host="bunny"]')).not.toHaveTextContent("$0");
    expect(october.querySelector('[data-host="meta"]')).toHaveTextContent("مش متاح");
    expect(october.querySelector("[data-total]")).toHaveTextContent("من غير اللي مش متقاس");
  });

  it("is technical support's too", async () => {
    serve("support");
    const { container } = open();
    await screen.findByText("أكتوبر 2026");
    expect(container.querySelector('[data-month="2026-10"] [data-host="neon"]')).toHaveTextContent("$5.33");
  });

  it("is nobody else's: anybody else goes home without asking", async () => {
    for (const role of ["accounting", "operation", "hr"] as Role[]) {
      const mocked = serve(role);
      const view = open();
      expect(await screen.findByText("home page")).toBeInTheDocument();
      expect(mocked.calls.some((call) => call.url.startsWith("/api/v1/admin/usage/months/"))).toBe(false);
      view.unmount();
      vi.unstubAllGlobals();
    }
  });
});
