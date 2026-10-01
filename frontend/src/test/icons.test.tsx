import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Shell } from "../components/Shell";
import { HomePage } from "../pages/HomePage";
import { NotFound } from "../pages/NotFound";
import { NotificationsPage } from "../pages/NotificationsPage";
import { jsonResponse, me, mockFetch, note, renderWithProviders } from "./helpers";

afterEach(() => vi.unstubAllGlobals());

/** The `i-…` ids the server's sprite really defines (templates/partials/icons.html). */
const sprite = new Set(
  [...readFileSync(resolve(import.meta.dirname, "../../../templates/partials/icons.html"), "utf-8").matchAll(/id="i-([a-z0-9-]+)"/g)].map(
    (match) => match[1]!,
  ),
);

function iconsDrawn(container: HTMLElement): string[] {
  return [...container.querySelectorAll("use")].map((node) => (node.getAttribute("href") ?? "").replace(/^#i-/, ""));
}

describe("icons", () => {
  it("the sprite file is found and has the names this app relies on", () => {
    expect(sprite.size).toBeGreaterThan(40);
    expect(sprite.has("message")).toBe(true);
    expect(sprite.has("chat")).toBe(false); // the classic trap: there is no "chat" icon
  });

  it("every icon the app draws exists in the sprite", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch({
        "/api/v1/me/": () => jsonResponse(me({}, 2)),
        "/api/v1/notifications/": () =>
          jsonResponse({
            ok: true,
            items: [
              note(1, { level: "info" }),
              note(2, { level: "success" }),
              note(3, { level: "warning" }),
              note(4, { level: "danger" }),
            ],
            next_before: null,
            unread: 4,
          }),
      }).fn,
    );
    const drawn = new Set<string>();

    for (const theme of ["dark", "light"] as const) {
      const shell = renderWithProviders(
        <Routes>
          <Route element={<Shell />}>
            <Route index element={<HomePage />} />
            <Route path="notifications" element={<NotificationsPage />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>,
        { theme },
      );
      await screen.findByText("Nour");
      iconsDrawn(shell.container).forEach((name) => drawn.add(name));
      shell.unmount();
    }
    for (const route of ["/notifications", "/nowhere"]) {
      const view = renderWithProviders(
        <Routes>
          <Route element={<Shell />}>
            <Route path="notifications" element={<NotificationsPage />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>,
        { route },
      );
      await waitFor(() => expect(view.container.querySelector(".content")!.textContent).not.toBe(""));
      await new Promise((done) => setTimeout(done, 50));
      iconsDrawn(view.container).forEach((name) => drawn.add(name));
      view.unmount();
    }

    expect(drawn.size).toBeGreaterThan(8);
    const missing = [...drawn].filter((name) => !sprite.has(name));
    expect(missing).toEqual([]);
  });
});
