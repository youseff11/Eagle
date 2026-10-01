import { screen } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Role, ScreenKey } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { HomePage } from "./HomePage";

afterEach(() => vi.unstubAllGlobals());

function renderHome(role: Role, screens: ScreenKey[]) {
  const mocked = mockFetch({ "/api/v1/me/": () => jsonResponse(me({ role, short_name: "Nour" }, 0, screens)) });
  vi.stubGlobal("fetch", mocked.fn);
  return renderWithProviders(
    <Routes>
      <Route index element={<HomePage />} />
      <Route path="translator" element={<div>the translator desk</div>} />
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
