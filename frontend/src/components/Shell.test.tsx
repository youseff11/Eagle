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

  it("has no way back to the classic interface and no home line: the logo goes to the app", async () => {
    const { container } = renderShell({ "/api/v1/me/": () => jsonResponse(me()) });
    await screen.findByText("Nour");
    const sidebar = container.querySelector(".sidebar") as HTMLElement;
    expect(sidebar.querySelector('a[href="/?classic=1"]')).toBeNull();
    expect(within(sidebar).queryByText("الواجهة الحالية")).toBeNull();
    expect(sidebar.querySelector('a[href="/"]')).toBeNull();
    expect(sidebar.querySelector('a.brand[href="/app/"]')).not.toBeNull();
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
    // Two screens share this address: until the server has said whose it is, it is not named at all.
    expect(view.container.querySelector(".topbar__title")).toHaveTextContent(/^$/);
    await waitFor(() => expect(view.container.querySelector(".topbar__title")).toHaveTextContent("شغلي"));
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
    // my work, my payroll (the same screen's other page), notifications
    expect(view.container.querySelectorAll(".nav__item")).toHaveLength(3);
    expect(view.container.querySelector('.sidebar a[href="/payroll"]')).not.toBeNull();
  });

  describe("the operation's screen", () => {
    const opsMe = (extra: Record<string, unknown> = {}, role: "operation" | "admin" = "operation", screens: string[] = ["operation", "chats"]) =>
      jsonResponse({ ...me({ role, is_admin: role === "admin" }, 0, screens as never), ...extra });
    const at = (route: string, who: () => Response) => {
      const mocked = mockFetch({ "/api/prefs/": () => jsonResponse({ ok: true }), "/api/v1/me/": who });
      vi.stubGlobal("fetch", mocked.fn);
      return renderWithProviders(
        <Routes>
          <Route element={<Shell />}>
            <Route path="inbox" element={<div>mailbox</div>} />
            <Route path="inbox/thread/:id" element={<div>conversation</div>} />
            <Route path="tasks" element={<div>tasks</div>} />
            <Route path="tasks/:code" element={<div>task</div>} />
            <Route path="team" element={<div>team</div>} />
            <Route path="clients" element={<div>clients</div>} />
            <Route path="clients/:code" element={<div>client</div>} />
            <Route path="translator" element={<div>desk</div>} />
          </Route>
        </Routes>,
        { route },
      );
    };
    const links = (container: HTMLElement) => Array.from(container.querySelectorAll(".sidebar .nav__item")).map((a) => a.getAttribute("href"));

    it("lists the mail, the chats, the tasks, the teams and the client codes in the classic menu's order", async () => {
      const view = at("/inbox", () => opsMe());
      await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/clients"]')).not.toBeNull());
      expect(links(view.container)).toEqual(["/inbox", "/chats", "/tasks", "/team", "/clients", "/notifications"]);
      expect(within(view.container.querySelector('.sidebar a[href="/inbox"]') as HTMLElement).getByText("ميلات واردة")).toBeInTheDocument();
      expect(within(view.container.querySelector('.sidebar a[href="/clients"]') as HTMLElement).getByText("أكواد العملاء")).toBeInTheDocument();
    });

    it("shows the two badges beside the mail and the tasks, and none when there is nothing", async () => {
      const view = at("/inbox", () => opsMe({ mail_unseen: 4, tasks_new: 2 }));
      await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/inbox"] .nav__count')).toHaveTextContent("4"));
      expect(view.container.querySelector('.sidebar a[href="/tasks"] .nav__count')).toHaveTextContent("2");
      expect(view.container.querySelector('.sidebar a[href="/team"] .nav__count')).toBeNull();
      expect(view.container.querySelector('.sidebar a[href="/clients"] .nav__count')).toBeNull();
      view.unmount();
      const quiet = at("/inbox", () => opsMe());
      await waitFor(() => expect(quiet.container.querySelector('.sidebar a[href="/inbox"]')).not.toBeNull());
      expect(quiet.container.querySelector('.sidebar a[href="/inbox"] .nav__count')).toBeNull();
      expect(quiet.container.querySelector('.sidebar a[href="/tasks"] .nav__count')).toBeNull();
    });

    it("titles every page of the screen, and lights the line of the page the person is on", async () => {
      const pages: [string, string, string][] = [
        ["/inbox", "ميلات واردة", "/inbox"],
        ["/inbox/thread/12", "ميلات واردة", "/inbox"],
        ["/tasks", "التاسكات", "/tasks"],
        ["/tasks/TSK-00001", "التاسكات", "/tasks"],
        ["/team", "حالة الفرق", "/team"],
        ["/clients", "أكواد العملاء", "/clients"],
        ["/clients/CL-0001", "أكواد العملاء", "/clients"],
      ];
      for (const [route, title, lit] of pages) {
        const view = at(route, () => opsMe());
        await waitFor(() => expect(view.container.querySelector(".topbar__title")).toHaveTextContent(title));
        await waitFor(() => expect(view.container.querySelector(`.sidebar a[href="${lit}"].is-active`)).not.toBeNull());
        expect(view.container.querySelectorAll(".sidebar .nav__item.is-active"), route).toHaveLength(1);
        view.unmount();
      }
    });

    it("keeps the admin's task list as 'tasks' and not as the translator's 'my work', whatever else is switched on", async () => {
      const view = at("/tasks", () => opsMe({}, "admin", ["translator_home", "operation", "chats"]));
      await waitFor(() => expect(view.container.querySelector(".topbar__title")).toHaveTextContent("التاسكات"));
      await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/tasks"].is-active')).not.toBeNull());
      expect(view.container.querySelector('.sidebar a[href="/translator"]')).not.toHaveClass("is-active");
    });

    it("leaves a translator's task page as 'my work' even though the operation's tasks share the address", async () => {
      const view = at("/tasks/TSK-00001", () => jsonResponse(me({ role: "translator" }, 0, ["translator_home"])));
      await waitFor(() => expect(view.container.querySelector(".topbar__title")).toHaveTextContent("شغلي"));
      expect(view.container.querySelector('.sidebar a[href="/tasks"]')).toBeNull();
    });

    it("draws none of it for a person whose operation screen is not switched on", async () => {
      const view = at("/inbox", () => opsMe({}, "operation", ["chats"]));
      await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/chats"]')).not.toBeNull());
      for (const href of ["/inbox", "/tasks", "/team", "/clients"]) expect(view.container.querySelector(`.sidebar a[href="${href}"]`), href).toBeNull();
    });
  });
});

describe("Shell: the attendance screen", () => {
  const at = (route: string, screens: string[]) => {
    const mocked = mockFetch({
      "/api/prefs/": () => jsonResponse({ ok: true }),
      "/api/v1/me/": () => jsonResponse(me({ role: "translator" }, 0, screens as never)),
    });
    vi.stubGlobal("fetch", mocked.fn);
    return renderWithProviders(
      <Routes>
        <Route element={<Shell />}>
          <Route path="attendance" element={<div>card</div>} />
          <Route path="translator" element={<div>desk</div>} />
        </Route>
      </Routes>,
      { route },
    );
  };

  it("lists «حضوري» for a person whose attendance screen is on, lit on its page and titled by it", async () => {
    const view = at("/attendance", ["translator_home", "attendance"]);
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/attendance"]')).not.toBeNull());
    expect(within(view.container.querySelector('.sidebar a[href="/attendance"]') as HTMLElement).getByText("حضوري")).toBeInTheDocument();
    expect(view.container.querySelector(".topbar__title")).toHaveTextContent("حضوري");
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/attendance"].is-active')).not.toBeNull());
    expect(view.container.querySelectorAll(".sidebar .nav__item.is-active")).toHaveLength(1);
  });

  it("does not list it for a person whose screen is off", async () => {
    const view = at("/translator", ["translator_home"]);
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/translator"]')).not.toBeNull());
    expect(view.container.querySelector('.sidebar a[href="/attendance"]')).toBeNull();
  });
});

describe("Shell: the Sales screen", () => {
  const at = (route: string, screens: string[], extra: Record<string, unknown> = {}) => {
    const mocked = mockFetch({
      "/api/prefs/": () => jsonResponse({ ok: true }),
      "/api/v1/me/": () => jsonResponse({ ...me({ role: "sales" }, 0, screens as never), ...extra }),
    });
    vi.stubGlobal("fetch", mocked.fn);
    return renderWithProviders(
      <Routes>
        <Route element={<Shell />}>
          <Route path="inbox" element={<div>mailbox</div>} />
          <Route path="inbox/thread/:id" element={<div>conversation</div>} />
          <Route path="line" element={<div>line</div>} />
          <Route path="clients" element={<div>clients</div>} />
          <Route path="clients/:code" element={<div>client</div>} />
        </Route>
      </Routes>,
      { route },
    );
  };
  const links = (container: HTMLElement) => Array.from(container.querySelectorAll(".sidebar .nav__item")).map((a) => a.getAttribute("href"));

  it("lists their mail, the chats, their number and mail, and the client codes in the classic menu's order and words", async () => {
    const view = at("/inbox", ["sales", "chats"]);
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/clients"]')).not.toBeNull());
    expect(links(view.container)).toEqual(["/inbox", "/chats", "/line", "/clients", "/notifications"]);
    expect(within(view.container.querySelector('.sidebar a[href="/inbox"]') as HTMLElement).getByText("ميلاتي")).toBeInTheDocument();
    expect(within(view.container.querySelector('.sidebar a[href="/line"]') as HTMLElement).getByText("رقمي وإيميلي")).toBeInTheDocument();
    expect(within(view.container.querySelector('.sidebar a[href="/clients"]') as HTMLElement).getByText("أكواد العملاء")).toBeInTheDocument();
  });

  it("shows the badge of the mail they have not opened, and no tasks line", async () => {
    const view = at("/inbox", ["sales"], { mail_unseen: 3 });
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/inbox"] .nav__count')).toHaveTextContent("3"));
    expect(view.container.querySelector('.sidebar a[href="/tasks"]')).toBeNull();
    expect(view.container.querySelector('.sidebar a[href="/team"]')).toBeNull();
  });

  it("titles every page of the screen and lights exactly the line of the page they are on", async () => {
    const pages: [string, string, string][] = [
      ["/inbox", "ميلاتي", "/inbox"],
      ["/inbox/thread/12", "ميلاتي", "/inbox"],
      ["/line", "رقمي وإيميلي", "/line"],
      ["/clients", "أكواد العملاء", "/clients"],
      ["/clients/CL-0001", "أكواد العملاء", "/clients"],
    ];
    for (const [route, title, lit] of pages) {
      const view = at(route, ["sales"]);
      await waitFor(() => expect(view.container.querySelector(".topbar__title")).toHaveTextContent(title));
      await waitFor(() => expect(view.container.querySelector(`.sidebar a[href="${lit}"].is-active`)).not.toBeNull());
      expect(view.container.querySelectorAll(".sidebar .nav__item.is-active"), route).toHaveLength(1);
      view.unmount();
    }
  });

  it("draws none of it for a person whose Sales screen is not switched on", async () => {
    const view = at("/inbox", ["chats"]);
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/chats"]')).not.toBeNull());
    for (const href of ["/inbox", "/line", "/clients"]) expect(view.container.querySelector(`.sidebar a[href="${href}"]`), href).toBeNull();
  });
});

describe("Shell: the team leader's screen", () => {
  const at = (route: string, screens: string[], extra: Record<string, unknown> = {}) => {
    const mocked = mockFetch({
      "/api/prefs/": () => jsonResponse({ ok: true }),
      "/api/v1/me/": () => jsonResponse({ ...me({ role: "team_lead" }, 0, screens as never), ...extra }),
    });
    vi.stubGlobal("fetch", mocked.fn);
    return renderWithProviders(
      <Routes>
        <Route element={<Shell />}>
          <Route path="lead" element={<div>board</div>} />
          <Route path="lead/translators" element={<div>translators</div>} />
          <Route path="tasks/:code" element={<div>task</div>} />
          <Route path="clients" element={<div>clients</div>} />
          <Route path="clients/:code" element={<div>client</div>} />
          <Route path="reviewer/*" element={<div>tests</div>} />
        </Route>
      </Routes>,
      { route },
    );
  };
  const links = (container: HTMLElement) => Array.from(container.querySelectorAll(".sidebar .nav__item")).map((a) => a.getAttribute("href"));

  it("lists their tasks, who is free, the chats and the client codes in the classic menu's order, the candidate tests under recruitment", async () => {
    const view = at("/lead", ["lead", "chats"]);
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/clients"]')).not.toBeNull());
    expect(links(view.container)).toEqual(["/lead", "/lead/translators", "/chats", "/clients", "/reviewer/tests", "/notifications"]);
    expect(Array.from(view.container.querySelectorAll(".sidebar .nav__label")).map((one) => one.textContent)).toEqual(["الشغل", "التوظيف", "حسابي"]);
    expect(within(view.container.querySelector('.sidebar a[href="/lead"]') as HTMLElement).getByText("تاسكاتي")).toBeInTheDocument();
    expect(within(view.container.querySelector('.sidebar a[href="/lead/translators"]') as HTMLElement).getByText("حالة المترجمين")).toBeInTheDocument();
  });

  it("shows how many of their tasks are being worked beside the first line", async () => {
    const view = at("/lead", ["lead"], { tasks_open: 4 });
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/lead"] .nav__count')).toHaveTextContent("4"));
    const quiet = at("/lead", ["lead"]);
    await waitFor(() => expect(quiet.container.querySelectorAll('.sidebar a[href="/lead"]').length).toBeGreaterThan(0));
  });

  it("titles every page of the screen, the task page is 'my tasks' and exactly one line is lit", async () => {
    const pages: [string, string, string][] = [
      ["/lead", "تاسكاتي", "/lead"],
      ["/lead/translators", "حالة المترجمين", "/lead/translators"],
      ["/tasks/TSK-00001", "تاسكاتي", "/lead"],
      ["/clients", "أكواد العملاء", "/clients"],
      ["/clients/CL-0001", "أكواد العملاء", "/clients"],
      ["/reviewer/tests", "اختبارات المرشحين", "/reviewer/tests"],
      ["/reviewer/tests/5", "اختبارات المرشحين", "/reviewer/tests"],
    ];
    for (const [route, title, lit] of pages) {
      const view = at(route, ["lead"]);
      await waitFor(() => expect(view.container.querySelector(".topbar__title")).toHaveTextContent(title));
      await waitFor(() => expect(view.container.querySelector(`.sidebar a[href="${lit}"].is-active`)).not.toBeNull());
      expect(view.container.querySelectorAll(".sidebar .nav__item.is-active"), route).toHaveLength(1);
      view.unmount();
    }
  });

  it("draws none of it for a leader whose screen is not switched on", async () => {
    const view = at("/lead", ["chats"]);
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/chats"]')).not.toBeNull());
    for (const href of ["/lead", "/lead/translators", "/clients", "/reviewer/tests"]) expect(view.container.querySelector(`.sidebar a[href="${href}"]`), href).toBeNull();
  });
});

describe("Shell: the admin's panel", () => {
  const at = (route: string, screens: string[], role: "admin" | "operation" = "admin") => {
    const mocked = mockFetch({
      "/api/prefs/": () => jsonResponse({ ok: true }),
      "/api/v1/me/": () => jsonResponse(me({ role, is_admin: role === "admin" }, 0, screens as never)),
    });
    vi.stubGlobal("fetch", mocked.fn);
    return renderWithProviders(
      <Routes>
        <Route element={<Shell />}>
          <Route path="admin" element={<div>overview</div>} />
          <Route path="admin/*" element={<div>a page of the panel</div>} />
        </Route>
      </Routes>,
      { route },
    );
  };
  const links = (container: HTMLElement) => Array.from(container.querySelectorAll(".sidebar .nav__item")).map((a) => a.getAttribute("href"));

  it("lists every page of the panel in the classic menu's sections and words, the two that delete last and in red", async () => {
    const view = at("/admin", ["admin", "chats"]);
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/admin/audit"]')).not.toBeNull());
    // The overview opens the work (the chats after it, the client records at its end), the people and the settings are
    // settings, and the two that delete for good are last of all, in a section of their own.
    expect(links(view.container)).toEqual([
      "/admin", "/chats", "/admin/clients",
      "/admin/users", "/admin/settings", "/admin/simulate", "/admin/audit",
      "/notifications", "/admin/reset-mail", "/admin/reset-tasks",
    ]);
    expect(Array.from(view.container.querySelectorAll(".sidebar .nav__label")).map((one) => one.textContent)).toEqual([
      "الشغل", "الإعدادات", "حسابي", "منطقة خطر",
    ]);
    const words: [string, string][] = [
      ["/admin", "نظرة عامة"], ["/admin/clients", "بيانات العملاء"], ["/admin/users", "المستخدمين والشيفتات"],
      ["/admin/settings", "الإعدادات و AI"], ["/admin/simulate", "محاكاة رسالة"], ["/admin/audit", "سجل النشاط"],
      ["/admin/reset-mail", "مسح الميلات"], ["/admin/reset-tasks", "ريستارت التاسكات"],
    ];
    for (const [href, label] of words) {
      expect(within(view.container.querySelector(`.sidebar a[href="${href}"]`) as HTMLElement).getByText(label), href).toBeInTheDocument();
    }
    for (const href of ["/admin/reset-mail", "/admin/reset-tasks"]) {
      expect(view.container.querySelector(`.sidebar a[href="${href}"]`), href).toHaveClass("nav__item--danger");
    }
    expect(view.container.querySelector('.sidebar a[href="/admin/users"]')).not.toHaveClass("nav__item--danger");
  });

  it("titles every page and lights exactly one line on each", async () => {
    for (const [route, title, lit] of [
      ["/admin", "نظرة عامة", "/admin"],
      ["/admin/audit", "سجل النشاط", "/admin/audit"],
      ["/admin/users", "المستخدمين والشيفتات", "/admin/users"],
      ["/admin/users/5", "المستخدمين والشيفتات", "/admin/users"],
      ["/admin/clients/CL-0001/edit", "بيانات العملاء", "/admin/clients"],
      ["/admin/settings", "الإعدادات و AI", "/admin/settings"],
      ["/admin/simulate", "محاكاة رسالة", "/admin/simulate"],
      ["/admin/reset-tasks", "ريستارت التاسكات", "/admin/reset-tasks"],
    ] as const) {
      const view = at(route, ["admin"]);
      await waitFor(() => expect(view.container.querySelector(".topbar__title")).toHaveTextContent(title));
      await waitFor(() => expect(view.container.querySelector(`.sidebar a[href="${lit}"].is-active`)).not.toBeNull());
      expect(view.container.querySelectorAll(".sidebar .nav__item.is-active"), route).toHaveLength(1);
      view.unmount();
    }
  });
});

describe("Shell: the money screens", () => {
  const at = (route: string, screens: string[], role: "admin" | "accounting" | "translator" = "accounting") => {
    const mocked = mockFetch({
      "/api/prefs/": () => jsonResponse({ ok: true }),
      "/api/v1/me/": () => jsonResponse(me({ role, is_admin: role === "admin" }, 0, screens as never)),
    });
    vi.stubGlobal("fetch", mocked.fn);
    return renderWithProviders(
      <Routes>
        <Route element={<Shell />}>
          <Route path="accounts/*" element={<div>a money page</div>} />
          <Route path="translator" element={<div>my work</div>} />
        </Route>
      </Routes>,
      { route },
    );
  };
  const links = (container: HTMLElement) => Array.from(container.querySelectorAll(".sidebar .nav__item")).map((a) => a.getAttribute("href"));

  it("gives accounting the sheet and the deductions, and keeps attendance and the rules for the admin", async () => {
    const view = at("/accounts", ["accounts", "chats"]);
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/accounts/violations"]')).not.toBeNull());
    expect(links(view.container)).toEqual(["/chats", "/accounts", "/accounts/violations", "/notifications"]);
    expect(links(view.container)).not.toContain("/accounts/attendance");
    expect(links(view.container)).not.toContain("/accounts/rules");
    view.unmount();
    const admin = at("/accounts", ["accounts", "chats"], "admin");
    await waitFor(() => expect(admin.container.querySelector('.sidebar a[href="/accounts/rules"]')).not.toBeNull());
    // The rules are a setting: they stand with the places and rules set once, not with the month's sheet.
    expect(links(admin.container)).toEqual(["/chats", "/accounts", "/accounts/attendance", "/accounts/violations", "/accounts/rules", "/notifications"]);
  });

  it("titles every page and lights exactly one line on each", async () => {
    for (const [route, title, lit] of [
      ["/accounts", "كشف الشهر", "/accounts"],
      ["/accounts/lines/9", "كشف الشهر", "/accounts"],
      ["/accounts/salary/4", "كشف الشهر", "/accounts"],
      ["/accounts/violations", "المخالفات والخصومات", "/accounts/violations"],
      ["/accounts/attendance", "الحضور والإنتاج", "/accounts/attendance"],
      ["/accounts/rules", "قواعد الحساب", "/accounts/rules"],
    ] as const) {
      const view = at(route, ["accounts"], "admin");
      await waitFor(() => expect(view.container.querySelector(".topbar__title")).toHaveTextContent(title));
      await waitFor(() => expect(view.container.querySelector(`.sidebar a[href="${lit}"].is-active`), route).not.toBeNull());
      expect(view.container.querySelectorAll(".sidebar .nav__item.is-active"), route).toHaveLength(1);
      view.unmount();
    }
  });

  it("lights a translator's own payslip under 'my work', since no money screen is theirs", async () => {
    const view = at("/accounts/lines/9", ["translator_home", "chats"], "translator");
    await waitFor(() => expect(view.container.querySelector(".topbar__title")).toHaveTextContent("شغلي"));
    expect(view.container.querySelector('.sidebar a[href="/translator"].is-active')).not.toBeNull();
    expect(view.container.querySelector('.sidebar a[href="/accounts"]')).toBeNull();
  });

  it("draws none of it for accounting that has not been switched on", async () => {
    const view = at("/accounts", ["chats"]);
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/chats"]')).not.toBeNull());
    for (const href of ["/accounts", "/accounts/violations", "/accounts/rules"]) expect(view.container.querySelector(`.sidebar a[href="${href}"]`), href).toBeNull();
  });
});

describe("Shell: human resources", () => {
  const at = (route: string, screens: string[], role: "hr" | "admin" | "reviewer" = "hr") => {
    const mocked = mockFetch({
      "/api/prefs/": () => jsonResponse({ ok: true }),
      "/api/v1/me/": () => jsonResponse(me({ role, is_admin: role === "admin" }, 0, screens as never)),
    });
    vi.stubGlobal("fetch", mocked.fn);
    return renderWithProviders(
      <Routes>
        <Route element={<Shell />}>
          <Route path="hr/*" element={<div>an HR page</div>} />
          <Route path="reviewer/*" element={<div>a reviewer page</div>} />
        </Route>
      </Routes>,
      { route },
    );
  };
  const links = (container: HTMLElement) => Array.from(container.querySelectorAll(".sidebar .nav__item")).map((a) => a.getAttribute("href"));

  it("lists the pages for HR in the classic menu's groups: recruitment, the people, then the settings", async () => {
    const view = at("/hr/attendance", ["hr", "chats"]);
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/hr/devices"]')).not.toBeNull());
    expect(links(view.container)).toEqual([
      "/chats",
      "/hr/recruitment", "/hr/vacancies", "/hr/candidates",
      "/hr/employees", "/hr/attendance", "/hr/schedules", "/hr/shifts", "/hr/leave", "/hr/overtime", "/hr/report", "/hr/probation",
      "/hr/performance", "/hr/complaints", "/hr/salary-requests",
      "/hr/offices", "/hr/devices", "/hr/recruitment/settings", "/hr/questions", "/notifications",
    ]);
    // Each group has its heading, and the heading comes before the group's first line.
    expect(Array.from(view.container.querySelectorAll(".sidebar .nav__label")).map((one) => one.textContent)).toEqual([
      "الشغل", "التوظيف", "الموظفين", "الإعدادات", "حسابي",
    ]);
    // The salary plans move money: the admin's line, not HR's.
    expect(links(view.container)).not.toContain("/hr/salary-plans");
    // The hiring decision and the tests are the owner's: HR does not have those lines.
    expect(links(view.container)).not.toContain("/hr/approvals");
    expect(links(view.container)).not.toContain("/reviewer/tests");
  });

  it("titles every page and lights exactly one line on each", async () => {
    for (const [route, title, lit] of [
      ["/hr/attendance", "لوحة الحضور", "/hr/attendance"],
      ["/hr/attendance/5", "لوحة الحضور", "/hr/attendance"],
      ["/hr/report", "التقرير الشهري", "/hr/report"],
      ["/hr/schedules", "جداول العمل", "/hr/schedules"],
      ["/hr/shifts", "الشيفتات", "/hr/shifts"],
      ["/hr/employees", "ملفات الموظفين", "/hr/employees"],
      ["/hr/employees/7", "ملفات الموظفين", "/hr/employees"],
      ["/hr/probation", "فترة الاختبار", "/hr/probation"],
      ["/hr/performance", "الأداء", "/hr/performance"],
      ["/hr/complaints", "شكاوى العملاء", "/hr/complaints"],
      ["/hr/salary-requests", "طلبات تغيير الراتب", "/hr/salary-requests"],
      ["/hr/leave", "طلبات الإجازة", "/hr/leave"],
      ["/hr/overtime", "الأوفرتايم", "/hr/overtime"],
      ["/hr/offices", "مواقع المكاتب", "/hr/offices"],
      ["/hr/devices", "أجهزة الحضور", "/hr/devices"],
      ["/hr/recruitment", "لوحة التوظيف", "/hr/recruitment"],
      ["/hr/recruitment/settings", "إعدادات التوظيف", "/hr/recruitment/settings"],
      ["/hr/vacancies", "الوظائف", "/hr/vacancies"],
      ["/hr/vacancies/VAC-0001", "الوظائف", "/hr/vacancies"],
      ["/hr/questions", "بنك الأسئلة", "/hr/questions"],
      ["/hr/candidates", "المرشحين", "/hr/candidates"],
      ["/hr/candidates/CAN-0007", "المرشحين", "/hr/candidates"],
      ["/hr/candidates/CAN-0007/hire", "المرشحين", "/hr/candidates"],
      ["/hr/interviews/21", "المرشحين", "/hr/candidates"],
    ] as const) {
      const view = at(route, ["hr"]);
      await waitFor(() => expect(view.container.querySelector(".topbar__title")).toHaveTextContent(title));
      await waitFor(() => expect(view.container.querySelector(`.sidebar a[href="${lit}"].is-active`), route).not.toBeNull());
      expect(view.container.querySelectorAll(".sidebar .nav__item.is-active"), route).toHaveLength(1);
      view.unmount();
    }
  });

  it("draws none of it for HR that has not been switched on", async () => {
    const view = at("/hr/attendance", ["chats"]);
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/chats"]')).not.toBeNull());
    for (const href of ["/hr/attendance", "/hr/report", "/hr/schedules", "/hr/shifts", "/hr/leave", "/hr/overtime", "/hr/offices", "/hr/devices", "/hr/employees", "/hr/probation", "/hr/recruitment", "/hr/vacancies", "/hr/questions", "/hr/recruitment/settings", "/hr/candidates"]) {
      expect(view.container.querySelector(`.sidebar a[href="${href}"]`), href).toBeNull();
    }
  });

  it("gives the admin the same lines once ticked", async () => {
    const view = at("/hr/report", ["hr"], "admin");
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/hr/report"]')).not.toBeNull());
    expect(links(view.container).slice(0, 5)).toEqual(["/hr/recruitment", "/hr/vacancies", "/hr/candidates", "/reviewer/tests", "/hr/approvals"]);
    // ...and the owner's own line, the salary plans, which HR does not have.
    expect(links(view.container)).toContain("/hr/salary-plans");
    // ...and the owner's hiring decisions and the candidate tests, which are theirs too.
    expect(links(view.container)).toContain("/hr/approvals");
    expect(links(view.container)).toContain("/reviewer/tests");
  });

  it("titles the owner's pages and lights one line on each", async () => {
    for (const [route, title, lit] of [
      ["/hr/approvals", "موافقات التعيين", "/hr/approvals"],
      ["/reviewer/tests", "اختبارات المرشحين", "/reviewer/tests"],
      ["/reviewer/tests/5", "اختبارات المرشحين", "/reviewer/tests"],
    ] as const) {
      const view = at(route, ["hr"], "admin");
      await waitFor(() => expect(view.container.querySelector(".topbar__title")).toHaveTextContent(title));
      await waitFor(() => expect(view.container.querySelector(`.sidebar a[href="${lit}"].is-active`), route).not.toBeNull());
      expect(view.container.querySelectorAll(".sidebar .nav__item.is-active"), route).toHaveLength(1);
      view.unmount();
    }
  });

  it("gives the reviewer one page, lit on the queue and on a test", async () => {
    for (const route of ["/reviewer/tests", "/reviewer/tests/5"]) {
      const view = at(route, ["reviewer"], "reviewer");
      await waitFor(() => expect(view.container.querySelector(".topbar__title")).toHaveTextContent("اختبارات المرشحين"));
      expect(links(view.container).filter((href) => href?.startsWith("/reviewer") || href?.startsWith("/hr"))).toEqual(["/reviewer/tests"]);
      await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/reviewer/tests"].is-active')).not.toBeNull());
      expect(view.container.querySelectorAll(".sidebar .nav__item.is-active")).toHaveLength(1);
      view.unmount();
    }
  });
});

describe("Shell: my leave", () => {
  const at = (route: string, screens: string[], role: "translator" | "hr" = "translator") => {
    const mocked = mockFetch({
      "/api/prefs/": () => jsonResponse({ ok: true }),
      "/api/v1/me/": () => jsonResponse(me({ role }, 0, screens as never)),
    });
    vi.stubGlobal("fetch", mocked.fn);
    return renderWithProviders(
      <Routes>
        <Route element={<Shell />}>
          <Route path="leave" element={<div>my leave page</div>} />
        </Route>
      </Routes>,
      { route },
    );
  };

  it("is one line for any role it is switched on for, titled and lit on its page", async () => {
    const view = at("/leave", ["translator_home", "leave", "chats"]);
    await waitFor(() => expect(view.container.querySelector(".topbar__title")).toHaveTextContent("إجازاتي"));
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/leave"].is-active')).not.toBeNull());
    expect(view.container.querySelectorAll(".sidebar .nav__item.is-active")).toHaveLength(1);
  });

  it("is not drawn when it has not been switched on", async () => {
    const view = at("/leave", ["translator_home", "chats"]);
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/chats"]')).not.toBeNull());
    expect(view.container.querySelector('.sidebar a[href="/leave"]')).toBeNull();
  });
});

describe("Shell: the performance board", () => {
  const at = (route: string, screens: string[], role: "translator" | "hr" | "operation" = "translator") => {
    const mocked = mockFetch({
      "/api/prefs/": () => jsonResponse({ ok: true }),
      "/api/v1/me/": () => jsonResponse(me({ role }, 0, screens as never)),
    });
    vi.stubGlobal("fetch", mocked.fn);
    return renderWithProviders(
      <Routes>
        <Route element={<Shell />}>
          <Route path="hr/performance" element={<div>the board</div>} />
        </Route>
      </Routes>,
      { route },
    );
  };

  it("is a line in anybody's own section, titled and lit on its page", async () => {
    for (const role of ["translator", "operation"] as const) {
      const view = at("/hr/performance", ["translator_home", "performance", "chats"], role);
      await waitFor(() => expect(view.container.querySelector(".topbar__title")).toHaveTextContent("الأداء"));
      const line = await waitFor(() => {
        const found = view.container.querySelector('.sidebar a[href="/hr/performance"]');
        expect(found).not.toBeNull();
        return found as HTMLElement;
      });
      expect(line).toHaveClass("is-active");
      expect(line.closest("[data-nav-group]")).toHaveAttribute("data-nav-group", "mine");
      expect(view.container.querySelectorAll(".sidebar .nav__item.is-active")).toHaveLength(1);
      view.unmount();
    }
  });

  it("is one line, in the people section, for HR, who have it twice over", async () => {
    const view = at("/hr/performance", ["hr", "performance", "chats"], "hr");
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/hr/performance"]')).not.toBeNull());
    const lines = view.container.querySelectorAll('.sidebar a[href="/hr/performance"]');
    expect(lines).toHaveLength(1);
    expect(lines[0]!.closest("[data-nav-group]")).toHaveAttribute("data-nav-group", "people");
    expect(view.container.querySelector(".topbar__title")).toHaveTextContent("الأداء");
  });

  it("is not drawn for a person it has not been switched on for", async () => {
    const view = at("/hr/performance", ["translator_home", "chats"]);
    await waitFor(() => expect(view.container.querySelector('.sidebar a[href="/chats"]')).not.toBeNull());
    expect(view.container.querySelector('.sidebar a[href="/hr/performance"]')).toBeNull();
  });
});
