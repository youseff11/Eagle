import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { qk } from "../api/keys";
import { jsonResponse, me, mockFetch, renderWithProviders, type Routes as FetchRoutes } from "../test/helpers";
import { Shell } from "./Shell";

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute("dir");
  document.documentElement.removeAttribute("data-theme");
});

function renderShell(routes: FetchRoutes, options: Parameters<typeof renderWithProviders>[1] = {}) {
  const mocked = mockFetch({
    "/api/prefs/": () => jsonResponse({ ok: true }),
    ...routes,
  });
  vi.stubGlobal("fetch", mocked.fn);
  const view = renderWithProviders(
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<div>home page</div>} />
        <Route path="notifications" element={<div>notifications page</div>} />
      </Route>
    </Routes>,
    options,
  );
  return { ...view, calls: mocked.calls };
}

describe("Shell", () => {
  it("says in the menu, from any page, that a message did not go - and only then", async () => {
    const item = (state: "sending" | "refused" | "unsure") => ({
      key: 1,
      body: "x",
      reply: null,
      files: [],
      task: "",
      voice: null,
      before: [],
      state,
      error: "",
    });
    const view = renderShell({ "/api/v1/me/": () => jsonResponse(me({}, 0, ["chats"])) });
    await screen.findByText("الشات");
    const chats = () => screen.getByText("الشات").closest("a") as HTMLElement;
    expect(chats().querySelector(".nav__count")).toBeNull();

    act(() => view.client.setQueryData(qk.outbox("CL-0001"), [item("sending")]));
    expect(chats().querySelector(".nav__count")).toBeNull();

    act(() => view.client.setQueryData(qk.outbox("CL-0001"), [item("unsure")]));
    expect(chats().querySelector(".nav__count")).not.toBeNull();
    expect(chats().querySelector('[title="فيه رسالة ماتبعتتش"]')).not.toBeNull();

    act(() => view.client.setQueryData(qk.outbox("CL-0001"), []));
    expect(chats().querySelector(".nav__count")).toBeNull();
  });

  it("shows who is signed in, with the role in the page's language", async () => {
    renderShell({ "/api/v1/me/": () => jsonResponse(me({ role: "team_lead", short_name: "Mona", initials: "MS" })) });
    expect(await screen.findByText("Mona")).toBeInTheDocument();
    expect(screen.getByText("MS")).toBeInTheDocument();
    expect(screen.getByText("تيم ليدر")).toBeInTheDocument();
  });

  it("labels every role the server can send", async () => {
    const roles = ["admin", "operation", "team_lead", "translator", "hr", "reviewer", "accounting", "sales"] as const;
    for (const role of roles) {
      const view = renderShell({ "/api/v1/me/": () => jsonResponse(me({ role })) }, { lang: "en" });
      const chip = await waitFor(() => {
        const found = view.container.querySelector(".chip");
        expect(found).not.toBeNull();
        return found!;
      });
      expect(chip.textContent, role).not.toBe(role);
      view.unmount();
    }
  });

  it("shows the unread count on the bell and in the menu, and hides it at zero", async () => {
    const view = renderShell({ "/api/v1/me/": () => jsonResponse(me({}, 3)) });
    await waitFor(() => expect(view.container.querySelector(".icon-btn__dot")).toHaveTextContent("3"));
    expect(view.container.querySelector(".nav__count")).toHaveTextContent("3");
    view.unmount();

    const none = renderShell({ "/api/v1/me/": () => jsonResponse(me({}, 0)) });
    await screen.findByText("Nour");
    expect(none.container.querySelector(".icon-btn__dot")).toBeNull();
    expect(none.container.querySelector(".nav__count")).toBeNull();
  });

  it("switches language: the words, the direction, and it saves the choice", async () => {
    const { container, calls } = renderShell({ "/api/v1/me/": () => jsonResponse(me()) });
    await screen.findByText("Nour");
    expect(within(container).getAllByText("الرئيسية").length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: "EN" }));
    expect(within(container).getAllByText("Home").length).toBeGreaterThan(0);
    expect(document.documentElement.dir).toBe("ltr");
    expect(document.documentElement.lang).toBe("en");
    await waitFor(() => expect(calls.some((c) => c.url === "/api/prefs/")).toBe(true));
    expect(String(calls.find((c) => c.url === "/api/prefs/")!.init?.body)).toBe("lang=en");
    await userEvent.click(screen.getByRole("button", { name: "عربي" }));
    expect(document.documentElement.dir).toBe("rtl");
  });

  it("toggles the theme and saves it", async () => {
    const { calls } = renderShell({ "/api/v1/me/": () => jsonResponse(me()) }, { theme: "dark" });
    await screen.findByText("Nour");
    expect(document.documentElement.dataset.theme).toBe("dark");
    await userEvent.click(screen.getByTitle("تبديل الوضع الليلي"));
    expect(document.documentElement.dataset.theme).toBe("light");
    await waitFor(() => expect(calls.some((c) => c.url === "/api/prefs/")).toBe(true));
    expect(String(calls.find((c) => c.url === "/api/prefs/")!.init?.body)).toBe("theme=light");
  });

  it("opens and closes the phone menu", async () => {
    const { container } = renderShell({ "/api/v1/me/": () => jsonResponse(me()) });
    await screen.findByText("Nour");
    const sidebar = container.querySelector(".sidebar")!;
    expect(sidebar).not.toHaveClass("is-open");
    await userEvent.click(container.querySelector(".menu-toggle")!);
    expect(sidebar).toHaveClass("is-open");
    expect(container.querySelector(".drawer-scrim")).toHaveClass("is-open");
    await userEvent.keyboard("{Escape}");
    expect(sidebar).not.toHaveClass("is-open");
    await userEvent.click(container.querySelector(".menu-toggle")!);
    await userEvent.click(container.querySelector(".drawer-scrim")!);
    expect(sidebar).not.toHaveClass("is-open");
  });

  it("closes the menu when you go somewhere", async () => {
    const { container } = renderShell({ "/api/v1/me/": () => jsonResponse(me()) });
    await screen.findByText("Nour");
    await userEvent.click(container.querySelector(".menu-toggle")!);
    await userEvent.click(container.querySelector('.sidebar a[href="/notifications"]')!);
    expect(await screen.findByText("notifications page")).toBeInTheDocument();
    expect(container.querySelector(".sidebar")).not.toHaveClass("is-open");
    expect(container.querySelector(".nav__item.is-active")).toHaveTextContent("التنبيهات");
  });

  it("shows whether the live connection is up", async () => {
    const { container } = renderShell({ "/api/v1/me/": () => jsonResponse(me()) });
    await screen.findByText("Nour");
    // No provider above it in this test: the default is "closed", drawn as offline.
    expect(container.querySelector(".realtime-dot")).toHaveAttribute("data-state", "closed");
  });

  it("offers the way back to the classic interface", async () => {
    const { container } = renderShell({ "/api/v1/me/": () => jsonResponse(me()) });
    await screen.findByText("Nour");
    const link = within(container.querySelector(".sidebar") as HTMLElement).getByRole("link", { name: "الواجهة الحالية" });
    // A plain link, not a router link: it leaves the app for the classic pages.
    expect(link).toHaveAttribute("href", "/?classic=1");
  });

  it("lists a ported screen in the menu only when the server switched it on for this person", async () => {
    const off = renderShell({ "/api/v1/me/": () => jsonResponse(me({ role: "translator" }, 0, [])) });
    await screen.findByText("Nour");
    expect(off.container.querySelector('.sidebar a[href="/translator"]')).toBeNull();
    off.unmount();

    const on = renderShell({ "/api/v1/me/": () => jsonResponse(me({ role: "translator" }, 0, ["translator_home"])) });
    const link = await waitFor(() => {
      const found = on.container.querySelector('.sidebar a[href="/translator"]');
      expect(found).not.toBeNull();
      return found!;
    });
    expect(link).toHaveTextContent("شغلي");
  });

  it("keeps the menu, and everything above the page, when a page fails to render", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const mocked = mockFetch({ "/api/prefs/": () => jsonResponse({ ok: true }), "/api/v1/me/": () => jsonResponse(me()) });
    vi.stubGlobal("fetch", mocked.fn);
    function Broken(): never {
      throw new Error("boom");
    }
    const view = renderWithProviders(
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<Broken />} />
          <Route path="notifications" element={<div>notifications page</div>} />
        </Route>
      </Routes>,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("حصلت مشكلة في عرض الصفحة دي.");
    // The menu is still there, and it still works.
    await screen.findByText("Nour");
    await userEvent.click(view.container.querySelector('.sidebar a[href="/notifications"]')!);
    expect(await screen.findByText("notifications page")).toBeInTheDocument();
    vi.restoreAllMocks();
  });

  it("titles the page from its address, even before the server has said who the person is", async () => {
    const mocked = mockFetch({ "/api/prefs/": () => jsonResponse({ ok: true }), "/api/v1/me/": () => new Promise<Response>(() => undefined) });
    vi.stubGlobal("fetch", mocked.fn);
    const view = renderWithProviders(
      <Routes>
        <Route element={<Shell />}>
          <Route path="translator" element={<div>desk</div>} />
        </Route>
      </Routes>,
      { route: "/translator" },
    );
    expect(view.container.querySelector(".topbar__title")).toHaveTextContent("شغلي");
  });

  it("knows the pages of the translator's screen: the title follows the page, and 'my work' stays lit on a task", async () => {
    const mocked = mockFetch({
      "/api/prefs/": () => jsonResponse({ ok: true }),
      "/api/v1/me/": () => jsonResponse(me({ role: "translator" }, 0, ["translator_home"])),
    });
    vi.stubGlobal("fetch", mocked.fn);
    const at = (route: string) =>
      renderWithProviders(
        <Routes>
          <Route element={<Shell />}>
            <Route path="translator" element={<div>desk</div>} />
            <Route path="payroll" element={<div>payslip</div>} />
            <Route path="tasks/:code" element={<div>task</div>} />
            <Route path="translators-by-mistake" element={<div>not a screen</div>} />
          </Route>
        </Routes>,
        { route },
      );

    let view = at("/payroll");
    expect(view.container.querySelector(".topbar__title")).toHaveTextContent("مستحقاتي");
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/payroll"].is-active')).not.toBeNull());
    expect(view.container.querySelector('.sidebar a[href="/translator"]')).not.toHaveClass("is-active");
    view.unmount();

    view = at("/tasks/TSK-00001");
    expect(view.container.querySelector(".topbar__title")).toHaveTextContent("شغلي");
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/translator"].is-active')).not.toBeNull());
    expect(view.container.querySelector('.sidebar a[href="/payroll"]')).not.toHaveClass("is-active");
    view.unmount();

    // An address that only starts like a screen's is not that screen.
    view = at("/translators-by-mistake");
    expect(view.container.querySelector(".topbar__title")).toHaveTextContent("الرئيسية");
  });

  it("draws the payslip line only for a person whose translator screen is switched on", async () => {
    const view = renderShell({ "/api/v1/me/": () => jsonResponse(me({ role: "translator" }, 0, [])) });
    await screen.findByText("Nour");
    expect(view.container.querySelector('.sidebar a[href="/payroll"]')).toBeNull();
    expect(view.container.querySelector('.sidebar a[href="/translator"]')).toBeNull();
  });

  it("never draws a screen it does not know, whatever the server lists", async () => {
    const view = renderShell({
      "/api/v1/me/": () => jsonResponse({ ...me({ role: "translator" }), screens: ["no_such_screen", "constructor", "translator_home"] }),
    });
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/translator"]')).not.toBeNull());
    // home, my work, my payroll (the same screen's other page), notifications, classic
    expect(view.container.querySelectorAll(".nav__item")).toHaveLength(5);
    expect(view.container.querySelector('.sidebar a[href="/payroll"]')).not.toBeNull();
  });
});
