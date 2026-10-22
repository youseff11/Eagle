import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { UsageCard, UsageReport } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders, type Routes as FetchRoutes } from "../test/helpers";
import { Shell } from "./Shell";
import { UsagePanel } from "./UsagePanel";

afterEach(() => vi.unstubAllGlobals());

const card = (key: UsageCard["key"], extra: Partial<UsageCard> = {}): UsageCard => ({
  key,
  name: { bunny: "Bunny.net", neon: "Neon", render: "Render" }[key],
  link: `https://${key}.example/billing`,
  state: "ok",
  month_usd: 1,
  estimate: false,
  lines: [],
  error: "",
  ...extra,
});

const report = (cards: UsageCard[], extra: Partial<UsageReport> = {}): UsageReport => ({
  ok: true,
  cards,
  total_usd: 16.85,
  estimate: true,
  at: { ar: "22/10 3:05 م", en: "22/10 3:05 PM" },
  ...extra,
});

function renderPanel(routes: FetchRoutes) {
  const mocked = mockFetch(routes);
  vi.stubGlobal("fetch", mocked.fn);
  return { ...renderWithProviders(<UsagePanel />), calls: mocked.calls };
}

describe("UsagePanel", () => {
  it("shows the month's total shut, and each host's card open", async () => {
    const answer = report([
      card("bunny", { month_usd: 0, lines: [{ ar: "الرصيد", en: "Balance", value: "$18.40" }] }),
      card("neon", { month_usd: 5.33, lines: [{ ar: "ساعات الكمبيوت", en: "Compute hours", value: "50.27" }] }),
      card("render", { month_usd: 11.52, estimate: true }),
    ]);
    renderPanel({ "/api/v1/admin/usage/": () => jsonResponse(answer) });
    expect(await screen.findByText("≈ $16.85")).toBeInTheDocument();
    expect(screen.queryByText("Neon")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: /استهلاك الشهر/ }));
    expect(screen.getByText("$5.33")).toBeInTheDocument();
    expect(screen.getByText("≈ $11.52")).toBeInTheDocument();
    expect(screen.getByText("50.27")).toBeInTheDocument();
    expect(screen.getByText("$18.40")).toBeInTheDocument();
    expect(screen.getByText("Neon").closest("a")).toHaveAttribute("href", "https://neon.example/billing");
    expect(screen.getByText(/22\/10 3:05 م/)).toBeInTheDocument();
  });

  it("says which host is not linked or failed, and why", async () => {
    const answer = report(
      [card("bunny", { state: "off", month_usd: null }), card("neon", { state: "error", error: "key_refused" }), card("render", { state: "error", error: "HTTP 502" })],
      { total_usd: null, estimate: false },
    );
    renderPanel({ "/api/v1/admin/usage/": () => jsonResponse(answer) });
    await userEvent.click(await screen.findByRole("button", { name: /استهلاك الشهر/ }));
    expect(await screen.findByText("مش متربط")).toBeInTheDocument();
    expect(screen.getByText("المفتاح مرفوض")).toBeInTheDocument();
    expect(screen.getByText("HTTP 502")).toBeInTheDocument();
    expect(screen.queryByText(/حط المفاتيح من الإعدادات/)).toBeNull();
  });

  it("points to the settings when no key is saved", async () => {
    const off = (key: UsageCard["key"]) => card(key, { state: "off", month_usd: null });
    renderPanel({ "/api/v1/admin/usage/": () => jsonResponse(report([off("bunny"), off("neon"), off("render")], { total_usd: null })) });
    await userEvent.click(await screen.findByRole("button", { name: /استهلاك الشهر/ }));
    expect(await screen.findByText(/حط المفاتيح من الإعدادات/)).toHaveAttribute("href", "/admin/settings");
  });

  it("asks the hosts again on «حدّث»", async () => {
    let total = 10;
    const view = renderPanel({ "/api/v1/admin/usage/": () => jsonResponse(report([card("neon")], { total_usd: total++, estimate: false })) });
    expect(await screen.findByText("$10.00")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /استهلاك الشهر/ }));
    await userEvent.click(screen.getByRole("button", { name: /حدّث/ }));
    expect(await screen.findByText("$11.00")).toBeInTheDocument();
    expect(view.calls.map((call) => call.url)).toEqual(["/api/v1/admin/usage/", "/api/v1/admin/usage/?fresh=1"]);
  });
});

describe("UsagePanel in the menu", () => {
  function renderShell(user: ReturnType<typeof me>) {
    const mocked = mockFetch({
      "/api/prefs/": () => jsonResponse({ ok: true }),
      "/api/v1/me/": () => jsonResponse(user),
      "/api/v1/admin/usage/": () => jsonResponse(report([card("neon")])),
    });
    vi.stubGlobal("fetch", mocked.fn);
    const view = renderWithProviders(
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<div>home page</div>} />
        </Route>
      </Routes>,
    );
    return { ...view, calls: mocked.calls };
  }

  it("is at the foot of the menu for the admin", async () => {
    const view = renderShell(me({ role: "admin", is_admin: true }));
    await waitFor(() => expect(view.container.querySelector(".side-foot .usage-panel")).not.toBeNull());
    expect(await screen.findByText("≈ $16.85")).toBeInTheDocument();
  });

  it("is not there, and is never asked for, for anybody else", async () => {
    for (const role of ["operation", "accounting", "hr", "sales", "team_lead", "translator", "support"] as const) {
      const view = renderShell(me({ role }));
      await waitFor(() => expect(view.container.querySelector(".side-foot")).not.toBeNull());
      await screen.findAllByText("home page");
      expect(view.container.querySelector(".usage-panel"), role).toBeNull();
      expect(view.calls.some((call) => call.url.startsWith("/api/v1/admin/usage/")), role).toBe(false);
      view.unmount();
    }
  });
});
