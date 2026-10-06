import { screen } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Role } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { HomePage, LANDING } from "./HomePage";

afterEach(() => vi.unstubAllGlobals());

const PLACES: Record<string, string> = {
  admin: "the admin overview",
  operation: "the operation mailbox",
  team_lead: "the leader board",
  translator: "the translator desk",
  hr: "the recruitment board",
  reviewer: "the reviewer queue",
  accounting: "the money sheet",
  sales: "the client codes",
  support: "the support tasks",
};

function renderHome(role: Role) {
  const mocked = mockFetch({ "/api/v1/me/": () => jsonResponse(me({ role, is_admin: role === "admin", short_name: "Nour" })) });
  vi.stubGlobal("fetch", mocked.fn);
  return renderWithProviders(
    <Routes>
      <Route index element={<HomePage />} />
      <Route path="admin" element={<div>{PLACES.admin}</div>} />
      <Route path="inbox" element={<div>{PLACES.operation}</div>} />
      <Route path="lead" element={<div>{PLACES.team_lead}</div>} />
      <Route path="translator" element={<div>{PLACES.translator}</div>} />
      <Route path="hr/recruitment" element={<div>{PLACES.hr}</div>} />
      <Route path="reviewer/tests" element={<div>{PLACES.reviewer}</div>} />
      <Route path="accounts" element={<div>{PLACES.accounting}</div>} />
      <Route path="clients" element={<div>{PLACES.sales}</div>} />
      <Route path="tasks" element={<div>{PLACES.support}</div>} />
      <Route path="notifications" element={<div>the notifications</div>} />
    </Routes>,
  );
}

describe("HomePage", () => {
  it("sends every role to the screen its work is on", async () => {
    for (const role of Object.keys(PLACES) as Role[]) {
      const view = renderHome(role);
      expect(await screen.findByText(PLACES[role]!), role).toBeInTheDocument();
      view.unmount();
    }
  });

  it("knows a landing for every role the server can send", () => {
    expect(Object.keys(LANDING).sort()).toEqual(Object.keys(PLACES).sort());
  });

  it("shows nothing of its own, and no way to the classic interface", async () => {
    const view = renderHome("operation");
    await screen.findByText(PLACES.operation!);
    expect(view.container.querySelector('a[href="/?classic=1"]')).toBeNull();
    expect(screen.queryByText(/الواجهة الحالية/)).toBeNull();
  });

  it("lands a role it does not know on the notifications, which every role has", async () => {
    const mocked = mockFetch({ "/api/v1/me/": () => jsonResponse(me({ role: "from_the_future" as Role })) });
    vi.stubGlobal("fetch", mocked.fn);
    renderWithProviders(
      <Routes>
        <Route index element={<HomePage />} />
        <Route path="notifications" element={<div>the notifications</div>} />
      </Routes>,
    );
    expect(await screen.findByText("the notifications")).toBeInTheDocument();
  });
});
