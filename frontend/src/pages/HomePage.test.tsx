import { screen } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Role, ScreenKey } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { HomePage } from "./HomePage";

afterEach(() => vi.unstubAllGlobals());

function renderHome(role: Role, screens: ScreenKey[]) {
  const mocked = mockFetch({ "/api/v1/me/": () => jsonResponse(me({ role, is_admin: role === "admin", short_name: "Nour" }, 0, screens)) });
  vi.stubGlobal("fetch", mocked.fn);
  return renderWithProviders(
    <Routes>
      <Route index element={<HomePage />} />
      <Route path="translator" element={<div>the translator desk</div>} />
      <Route path="admin" element={<div>the admin overview</div>} />
      <Route path="hr/recruitment" element={<div>the recruitment board</div>} />
      <Route path="reviewer/tests" element={<div>the reviewer queue</div>} />
    </Routes>,
  );
}

describe("HomePage", () => {
  it("starts a translator whose desk was switched over on the desk, as the classic / does", async () => {
    renderHome("translator", ["translator_home"]);
    expect(await screen.findByText("the translator desk")).toBeInTheDocument();
  });

  it("keeps a translator whose desk was not switched over on the home page", async () => {
    renderHome("translator", []);
    expect(await screen.findByText(/Nour/)).toBeInTheDocument();
    expect(screen.queryByText("the translator desk")).not.toBeInTheDocument();
  });

  it("starts the admin whose panel was switched over on the overview, as the classic / does", async () => {
    renderHome("admin", ["admin"]);
    expect(await screen.findByText("the admin overview")).toBeInTheDocument();
  });

  it("keeps an admin whose panel was not switched over on the home page, and no other role is moved by it", async () => {
    renderHome("admin", ["chats"]);
    expect(await screen.findByText(/Nour/)).toBeInTheDocument();
    for (const role of ["operation", "team_lead", "hr"] as const) {
      const view = renderHome(role, ["admin"]);
      expect(await screen.findByText(/Nour/), role).toBeInTheDocument();
      expect(screen.queryByText("the admin overview"), role).not.toBeInTheDocument();
      view.unmount();
    }
  });

  it("starts HR on the recruitment board and a reviewer on the queue once those screens are switched on, and only them", async () => {
    renderHome("hr", ["hr"]);
    expect(await screen.findByText("the recruitment board")).toBeInTheDocument();
    renderHome("reviewer", ["reviewer"]);
    expect(await screen.findByText("the reviewer queue")).toBeInTheDocument();
  });

  it("keeps HR and a reviewer on the home page while their screens are off, and the admin where the admin's own screen puts them", async () => {
    for (const [role, screens] of [["hr", []], ["hr", ["chats"]], ["reviewer", []], ["admin", ["hr"]], ["admin", ["reviewer"]], ["operation", ["hr"]]] as const) {
      const view = renderHome(role, [...screens]);
      expect(await screen.findByText(/Nour/), `${role} ${screens.join()}`).toBeInTheDocument();
      expect(screen.queryByText("the recruitment board")).not.toBeInTheDocument();
      expect(screen.queryByText("the reviewer queue")).not.toBeInTheDocument();
      view.unmount();
    }
  });

  it("does not move anyone else, whatever the server lists for them", async () => {
    for (const role of ["admin", "operation", "team_lead", "hr", "reviewer", "accounting", "sales"] as const) {
      const view = renderHome(role, ["translator_home"]);
      expect(await screen.findByText(/Nour/), role).toBeInTheDocument();
      expect(screen.queryByText("the translator desk"), role).not.toBeInTheDocument();
      view.unmount();
    }
  });

  it("links to the classic interface by the address that does not bounce back", async () => {
    renderHome("admin", []);
    const link = await screen.findByRole("link", { name: "افتح الواجهة الحالية" });
    expect(link).toHaveAttribute("href", "/?classic=1");
  });
});
