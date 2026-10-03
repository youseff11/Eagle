import { screen } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Role } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { TaskRoute } from "./TaskRoute";

afterEach(() => vi.unstubAllGlobals());

function serve(role: Role | null, admin = false) {
  const mocked = mockFetch({
    "/api/v1/me/": () => (role ? jsonResponse(me({ role, is_admin: admin })) : jsonResponse({ ok: false, error: "server" }, 500)),
    "/api/v1/translator/tasks/": () => jsonResponse({ ok: false, error: "not_found" }, 404),
    "/api/v1/tasks/": () => jsonResponse({ ok: false, error: "not_found" }, 404),
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function open() {
  return renderWithProviders(
    <Routes>
      <Route path="/tasks/:code" element={<TaskRoute />} />
      <Route path="/" element={<div>home page</div>} />
    </Routes>,
    { route: "/tasks/TSK-00001" },
  );
}

describe("TaskRoute: /tasks/<code> is two pages", () => {
  it("is the translator's own page for a translator", async () => {
    const mocked = serve("translator");
    open();
    expect(await screen.findByText("التاسك دي مش متاحة ليك.")).toBeInTheDocument();
    expect(mocked.calls.some((c) => c.url === "/api/v1/translator/tasks/TSK-00001/")).toBe(true);
    expect(mocked.calls.some((c) => c.url === "/api/v1/tasks/TSK-00001/")).toBe(false);
  });

  it("is the operation's page for the operation", async () => {
    const mocked = serve("operation");
    open();
    expect(await screen.findByText("التاسك دي مش موجودة.")).toBeInTheDocument();
    expect(mocked.calls.some((c) => c.url === "/api/v1/tasks/TSK-00001/")).toBe(true);
    expect(mocked.calls.some((c) => c.url.startsWith("/api/v1/translator/"))).toBe(false);
  });

  it("is the operation's page for the admin: the translator's is theirs only to look at", async () => {
    const mocked = serve("admin", true);
    open();
    expect(await screen.findByText("التاسك دي مش موجودة.")).toBeInTheDocument();
    expect(mocked.calls.some((c) => c.url === "/api/v1/tasks/TSK-00001/")).toBe(true);
    expect(mocked.calls.some((c) => c.url.startsWith("/api/v1/translator/"))).toBe(false);
  });

  it("sends anybody else home without asking for a task", async () => {
    for (const role of ["team_lead", "hr", "reviewer", "accounting", "sales"] as const) {
      const mocked = serve(role);
      const view = open();
      expect(await screen.findByText("home page"), role).toBeInTheDocument();
      expect(mocked.calls.some((c) => c.url.includes("/tasks/")), role).toBe(false);
      view.unmount();
      vi.unstubAllGlobals();
    }
  });

  it("says it is loading before it knows who the person is, and does not choose a page for them", async () => {
    vi.stubGlobal("fetch", () => new Promise(() => undefined));
    open();
    expect(await screen.findByText("بيحمّل...")).toBeInTheDocument();
  });

  it("says it could not load when it cannot find out who the person is", async () => {
    serve(null);
    open();
    expect(await screen.findByRole("alert")).toHaveTextContent("حصلت مشكلة في التحميل.");
  });
});
