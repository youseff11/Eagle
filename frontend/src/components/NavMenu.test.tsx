import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useState, type ReactElement } from "react";
import { Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Lang, ScreenKey } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { Shell } from "./Shell";

beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.removeAttribute("dir");
  document.documentElement.removeAttribute("data-theme");
});

function Where() {
  const here = useLocation();
  return <div data-testid="where">{here.pathname + here.hash}</div>;
}

const TASK = { code: "TSK-00007", title: "Lease contract", origin: "email", status_ar: "جاري", status_en: "In progress", client: "CL-0001", href: "/tasks/TSK-00007/" };

interface Options {
  screens?: ScreenKey[];
  role?: "operation" | "admin" | "translator" | "hr" | "support";
  route?: string;
  lang?: Lang;
  /** What `/api/v1/me/` carries besides the usual (the counters). */
  extra?: Record<string, unknown>;
  unread?: number;
  tasks?: (query: string) => unknown[];
  page?: ReactElement;
}

function renderMenu(options: Options = {}) {
  const role = options.role ?? "operation";
  const mocked = mockFetch({
    "/api/prefs/": () => jsonResponse({ ok: true }),
    "/api/v1/me/": () =>
      jsonResponse({ ...me({ role, is_admin: role === "admin" }, options.unread ?? 0, options.screens ?? ["operation", "chats"]), ...options.extra }),
    "/api/search/tasks/": (url) => jsonResponse({ ok: true, items: options.tasks?.(url.searchParams.get("q") ?? "") ?? [] }),
  });
  vi.stubGlobal("fetch", mocked.fn);
  const view = renderWithProviders(
    <Routes>
      <Route element={<Shell />}>
        <Route path="*" element={options.page ?? <Where />} />
      </Route>
    </Routes>,
    { route: options.route, lang: options.lang },
  );
  return { ...view, calls: mocked.calls };
}

const group = (container: HTMLElement, key: string) => container.querySelector(`[data-nav-group="${key}"]`) as HTMLElement;
const head = (container: HTMLElement, key: string) => group(container, key).querySelector(".nav__head") as HTMLElement;
const items = (container: HTMLElement, key: string) => group(container, key).querySelector(".nav__items") as HTMLElement;
const isOpen = (container: HTMLElement, key: string) => head(container, key).getAttribute("aria-expanded") === "true";
const saved = () => JSON.parse(localStorage.getItem("eagle_nav_open") ?? "{}") as Record<string, boolean>;

describe("the menu's sections", () => {
  it("gives technical support the tasks, the team board and the chats, and no attendance, no leave and no pay", async () => {
    const { container } = renderMenu({ role: "support", screens: ["support", "chats"], route: "/tasks" });
    await screen.findByRole("link", { name: "التاسكات" });
    const links = Array.from(container.querySelectorAll(".nav__item")).map((link) => link.textContent);
    expect(links).toEqual(expect.arrayContaining(["التاسكات", "حالة الفرق", "الشات", "التنبيهات"]));
    for (const absent of ["حضوري", "إجازاتي", "مستحقاتي", "ميلات واردة", "أكواد العملاء"]) {
      expect(links.some((text) => text?.includes(absent)), absent).toBe(false);
    }
    // And the chip says what they are.
    expect(screen.getAllByText("دعم فني").length).toBeGreaterThan(0);
  });

  it("opens the section the person is standing in and keeps the others shut", async () => {
    const { container } = renderMenu({ route: "/tasks" });
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    expect(isOpen(container, "work")).toBe(true);
    expect(isOpen(container, "mine")).toBe(false);
    expect(items(container, "work")).not.toHaveAttribute("hidden");
    expect(items(container, "mine")).toHaveAttribute("hidden");
    // A shut section still has its lines in the page (the search and the title read them), it is only out of sight.
    expect(items(container, "mine").querySelector('a[href="/notifications"]')).not.toBeNull();
  });

  it("draws no menu, not even the bell, until the server has said who this is, and then settles on the whole of it", async () => {
    let answer: (response: Response) => void = () => undefined;
    const mocked = mockFetch({
      "/api/prefs/": () => jsonResponse({ ok: true }),
      "/api/v1/me/": () => new Promise<Response>((resolve) => (answer = resolve)),
    });
    vi.stubGlobal("fetch", mocked.fn);
    const { container } = renderWithProviders(
      <Routes>
        <Route element={<Shell />}>
          <Route path="*" element={<Where />} />
        </Route>
      </Routes>,
      { route: "/tasks" },
    );
    expect(container.querySelector(".nav__group")).toBeNull();
    expect(container.querySelector("#navFoldAll")).toBeNull();
    // A menu that settled on its first look with only the bell in it would have opened «حسابي» and kept it open.
    act(() => answer(jsonResponse(me({}, 0, ["operation", "chats"]))));
    await waitFor(() => expect(group(container, "work")).not.toBeNull());
    expect(isOpen(container, "work")).toBe(true);
    expect(isOpen(container, "mine")).toBe(false);
  });

  it("opens the first section on a page that is in none of them, so the menu is not all shut", async () => {
    const { container } = renderMenu({ route: "/" });
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    expect(isOpen(container, "work")).toBe(true);
    expect(isOpen(container, "mine")).toBe(false);
  });

  it("folds and unfolds with a click on the heading, and remembers the choice", async () => {
    const first = renderMenu({ route: "/tasks" });
    await waitFor(() => expect(group(first.container, "mine")).not.toBeNull());
    await userEvent.click(head(first.container, "mine"));
    expect(isOpen(first.container, "mine")).toBe(true);
    expect(saved()).toEqual({ mine: true });
    await userEvent.click(head(first.container, "work"));
    expect(isOpen(first.container, "work")).toBe(false);
    expect(saved()).toEqual({ mine: true, work: false });
    first.unmount();

    // Another visit: the person's own choices are kept (the section they are standing in is open anyway).
    const again = renderMenu({ route: "/notifications" });
    await waitFor(() => expect(group(again.container, "mine")).not.toBeNull());
    expect(isOpen(again.container, "mine")).toBe(true);
    expect(isOpen(again.container, "work")).toBe(false);
  });

  it("opens the section of the page the person is on whatever was saved, and keeps what was saved for the rest", async () => {
    localStorage.setItem("eagle_nav_open", JSON.stringify({ work: false, mine: true }));
    const { container } = renderMenu({ route: "/tasks" });
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    expect(isOpen(container, "work")).toBe(true);
    expect(isOpen(container, "mine")).toBe(true);
    // The page forced it open; the person did not choose that, so what was saved for it is still what they chose.
    expect(saved().work).toBe(false);
  });

  it("opens a section when the person goes to a page in it, without writing that down as their choice", async () => {
    const { container } = renderMenu({ route: "/tasks" });
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    expect(isOpen(container, "mine")).toBe(false);
    await userEvent.click(container.querySelector('.topbar a[href="/notifications"]') as HTMLElement);
    await waitFor(() => expect(isOpen(container, "mine")).toBe(true));
    expect(saved()).toEqual({});
    // ...and the one they left is not shut behind them.
    expect(isOpen(container, "work")).toBe(true);
  });

  it("shuts every section with one button and opens them all with the next click", async () => {
    const { container } = renderMenu({ route: "/tasks" });
    const button = await waitFor(() => {
      const found = container.querySelector("#navFoldAll") as HTMLElement | null;
      expect(found).not.toBeNull();
      return found!;
    });
    expect(button).toHaveTextContent("اقفل كل القوايم");
    expect(button).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(button);
    expect(isOpen(container, "work")).toBe(false);
    expect(isOpen(container, "mine")).toBe(false);
    expect(button).toHaveTextContent("افتح كل القوايم");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveClass("is-folded");
    expect(saved()).toEqual({ work: false, mine: false });
    await userEvent.click(button);
    expect(isOpen(container, "work")).toBe(true);
    expect(isOpen(container, "mine")).toBe(true);
    expect(button).toHaveTextContent("اقفل كل القوايم");
    expect(button).not.toHaveClass("is-folded");
  });

  it("follows the sections one by one: the button says «open all» once the last one is shut", async () => {
    const { container } = renderMenu({ route: "/tasks" });
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    await userEvent.click(head(container, "work"));
    expect(container.querySelector("#navFoldAll")).toHaveTextContent("افتح كل القوايم");
    await userEvent.click(head(container, "mine"));
    expect(container.querySelector("#navFoldAll")).toHaveTextContent("اقفل كل القوايم");
  });

  it("says in English too", async () => {
    const { container } = renderMenu({ route: "/tasks", lang: "en" });
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    expect(container.querySelector("#navFoldAll")).toHaveTextContent("Collapse all");
    expect(head(container, "work")).toHaveTextContent("Work");
    expect(head(container, "mine")).toHaveTextContent("My account");
  });

  it("shows what is waiting in a section that is shut, and nothing once it is open", async () => {
    const { container } = renderMenu({
      route: "/tasks",
      unread: 5,
      extra: { mail_unseen: 4, tasks_new: 2, unread_chats: 3 },
    });
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    // The work is open and counts on its own lines; the shut one carries the bell's number on its heading.
    expect(head(container, "work").querySelector(".nav__roll")).toBeNull();
    expect(head(container, "mine").querySelector(".nav__roll")).toHaveTextContent("5");
    await userEvent.click(head(container, "work"));
    // mail 4 + tasks 2 + the chats 3
    expect(head(container, "work").querySelector(".nav__roll")).toHaveTextContent("9");
    await userEvent.click(head(container, "mine"));
    expect(head(container, "mine").querySelector(".nav__roll")).toBeNull();
  });

  it("counts a message that did not go among what is waiting in the work", async () => {
    const { container, client } = renderMenu({ route: "/notifications" });
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    expect(head(container, "work").querySelector(".nav__roll")).toBeNull();
    act(() =>
      client.setQueryData(["outbox", "CL-0001"], [{ key: 1, body: "x", reply: null, files: [], task: "", voice: null, before: [], state: "refused", error: "" }]),
    );
    await waitFor(() => expect(head(container, "work").querySelector(".nav__roll")).toHaveTextContent("1"));
  });

  it("is not thrown by what somebody left in the browser's storage", async () => {
    for (const rubbish of ["[1,2", "null", "[true]", '"yes"', '{"work":"yes","mine":1}']) {
      localStorage.setItem("eagle_nav_open", rubbish);
      const { container, unmount } = renderMenu({ route: "/tasks" });
      await waitFor(() => expect(group(container, "mine")).not.toBeNull());
      expect(isOpen(container, "work"), rubbish).toBe(true);
      expect(isOpen(container, "mine"), rubbish).toBe(false);
      unmount();
    }
  });

  it("keeps the three public pages at the foot of the menu", async () => {
    const { container } = renderMenu();
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    const foot = container.querySelector(".side-foot .side-legal") as HTMLElement;
    expect(Array.from(foot.querySelectorAll("a")).map((link) => link.getAttribute("href"))).toEqual(["/privacy/", "/terms/", "/data-deletion/"]);
    expect(within(foot).getByText("الخصوصية")).toBeInTheDocument();
  });

  it("draws no empty section", async () => {
    const { container } = renderMenu({ role: "translator", screens: ["translator_home"], route: "/translator" });
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    expect(Array.from(container.querySelectorAll(".nav__head")).map((one) => one.getAttribute("data-section"))).toEqual(["work", "mine"]);
  });
});

describe("the menu's search", () => {
  const box = (container: HTMLElement) => container.querySelector("#navSearchInput") as HTMLInputElement;
  const rows = (container: HTMLElement) => Array.from(container.querySelectorAll(".nav-search__row"));
  const where = () => screen.getByTestId("where");

  it("sits above the menu and says what it looks for", async () => {
    const { container } = renderMenu();
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    expect(box(container)).toHaveAttribute("placeholder", "دوّر على صفحة أو تاسك…");
    expect(container.querySelector(".sidebar .brand + .nav-search")).not.toBeNull();
    expect(container.querySelector(".nav-search__results")).toBeNull();
  });

  it("finds a page by its name, goes there on a click, and clears the box", async () => {
    const { container } = renderMenu({ route: "/inbox" });
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    await userEvent.type(box(container), "التاسكات");
    const row = await screen.findByRole("option", { name: /التاسكات/ });
    expect(row).toHaveTextContent("الشغل");
    await userEvent.click(row);
    expect(where()).toHaveTextContent("/tasks");
    expect(box(container)).toHaveValue("");
    expect(container.querySelector(".nav-search__results")).toBeNull();
    expect(container.querySelector(".topbar__title")).toHaveTextContent("التاسكات");
  });

  it("goes to the first answer on Enter, and to the next after the arrow", async () => {
    const { container } = renderMenu({ role: "admin", screens: ["admin", "accounts"], route: "/admin" });
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    await userEvent.type(box(container), "المخالفات");
    await waitFor(() => expect(rows(container).length).toBeGreaterThan(0));
    expect(rows(container)[0]).toHaveClass("is-active");
    await userEvent.keyboard("{Enter}");
    expect(where()).toHaveTextContent("/accounts/violations");

    await userEvent.type(box(container), "ميل");
    await waitFor(() => expect(rows(container).length).toBeGreaterThan(1));
    const second = rows(container)[1]!;
    await userEvent.keyboard("{ArrowDown}");
    expect(second).toHaveClass("is-active");
    expect(rows(container)[0]).not.toHaveClass("is-active");
    await userEvent.keyboard("{ArrowUp}{ArrowUp}");
    // Past the first goes round to the last.
    expect(rows(container).at(-1)).toHaveClass("is-active");
    expect(box(container)).toHaveAttribute("aria-activedescendant", `nav-hit-${rows(container).length - 1}`);
  });

  it("clears and lets go on Escape", async () => {
    const { container } = renderMenu();
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    await userEvent.type(box(container), "تاسك");
    await waitFor(() => expect(rows(container).length).toBeGreaterThan(0));
    await userEvent.keyboard("{Escape}");
    expect(box(container)).toHaveValue("");
    expect(container.querySelector(".nav-search__results")).toBeNull();
    expect(box(container)).not.toHaveFocus();
  });

  it("closes the answers on a click anywhere else, and opens them again when you come back to the box", async () => {
    const { container } = renderMenu();
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    await userEvent.type(box(container), "تاسك");
    await waitFor(() => expect(rows(container).length).toBeGreaterThan(0));
    await userEvent.click(container.querySelector(".content") as HTMLElement);
    expect(container.querySelector(".nav-search__results")).toBeNull();
    expect(box(container)).toHaveValue("تاسك");
    await userEvent.click(box(container));
    expect(rows(container).length).toBeGreaterThan(0);
  });

  it("finds a section inside a page and lands on it", async () => {
    const { container } = renderMenu({ role: "admin", screens: ["admin"], route: "/admin" });
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    await userEvent.type(box(container), "كلمات الحظر");
    const row = await screen.findByRole("option", { name: /كلمات الحظر/ });
    // It says which page it is in, the way the classic menu did.
    expect(row).toHaveTextContent("الإعدادات و AI");
    await userEvent.keyboard("{Enter}");
    expect(where()).toHaveTextContent("/admin/settings#settings-rate_keywords");
  });

  it("finds nothing of a page the person has no line for", async () => {
    const { container } = renderMenu();
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    await userEvent.type(box(container), "سجل النشاط");
    expect(await screen.findByText("مفيش حاجة بالاسم ده.")).toBeInTheDocument();
    expect(rows(container)).toHaveLength(0);
  });

  it("looks for the same words in English, and shows the answers in English", async () => {
    const { container } = renderMenu({ lang: "en" });
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    expect(box(container)).toHaveAttribute("placeholder", "Search a page or a task…");
    await userEvent.type(box(container), "incoming mail");
    const row = await screen.findByRole("option", { name: /Incoming mail/ });
    expect(row).toHaveTextContent("Work");
  });

  it("brings the tasks in a moment after the pages, under their own heading, each as the server wrote it", async () => {
    const { container, calls } = renderMenu({ tasks: (query) => (query === "lease" ? [TASK] : []) });
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    await userEvent.type(box(container), "lease");
    const row = await screen.findByRole("option", { name: /Lease contract/ });
    expect(container.querySelector(".nav-search__head")).toHaveTextContent("تاسكات");
    expect(row.querySelector(".mono")).toHaveTextContent("TSK-00007");
    expect(row).toHaveTextContent("CL-0001 · جاري");
    // One question, once the typing paused: not one per letter.
    expect(calls.filter((call) => call.url.startsWith("/api/search/tasks/")).map((call) => call.url)).toEqual(["/api/search/tasks/?q=lease"]);
    await userEvent.click(row);
    expect(where()).toHaveTextContent("/tasks/TSK-00007");
    expect(box(container)).toHaveValue("");
  });

  it("shows the task's status in English when the page is", async () => {
    const { container } = renderMenu({ lang: "en", tasks: () => [TASK] });
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    await userEvent.type(box(container), "lease");
    expect(await screen.findByRole("option", { name: /Lease contract/ })).toHaveTextContent("CL-0001 · In progress");
  });

  it("never shows the tasks found for an older typing under a newer one", async () => {
    const { container } = renderMenu({ tasks: (query) => (query === "lease" ? [TASK] : []) });
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    await userEvent.type(box(container), "lease");
    await screen.findByRole("option", { name: /Lease contract/ });
    await userEvent.type(box(container), "x");
    // Gone at once, not after the next answer.
    expect(screen.queryByRole("option", { name: /Lease contract/ })).toBeNull();
  });

  it("does not ask the server about one letter", async () => {
    const { container, calls } = renderMenu({ tasks: () => [TASK] });
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    await userEvent.type(box(container), "l");
    await new Promise((done) => setTimeout(done, 400));
    expect(calls.filter((call) => call.url.startsWith("/api/search/tasks/"))).toEqual([]);
  });

  it("answers a task for someone whose pages found nothing", async () => {
    const { container } = renderMenu({ tasks: () => [TASK] });
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    await userEvent.type(box(container), "zzqq");
    expect(await screen.findByRole("option", { name: /Lease contract/ })).toBeInTheDocument();
    expect(screen.queryByText("مفيش حاجة بالاسم ده.")).toBeNull();
  });

  it("comes to the box on Ctrl+K from anywhere, opening the phone's menu on the way", async () => {
    const { container } = renderMenu();
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    expect(container.querySelector(".sidebar")).not.toHaveClass("is-open");
    await userEvent.keyboard("{Control>}k{/Control}");
    expect(box(container)).toHaveFocus();
    expect(container.querySelector(".sidebar")).toHaveClass("is-open");
  });

  it("comes to the box on «/», but not while the person is typing somewhere else", async () => {
    const page = <input data-testid="other" />;
    const { container } = renderMenu({ page });
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    await userEvent.click(screen.getByTestId("other"));
    await userEvent.keyboard("a/b");
    expect(screen.getByTestId("other")).toHaveValue("a/b");
    expect(box(container)).not.toHaveFocus();

    await userEvent.click(container.querySelector(".content") as HTMLElement);
    await userEvent.keyboard("/");
    expect(box(container)).toHaveFocus();
    expect(box(container)).toHaveValue("");
  });

  it("is a combobox over a list of options for a screen reader", async () => {
    const { container } = renderMenu();
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    expect(screen.getByRole("combobox")).toHaveAttribute("aria-expanded", "false");
    await userEvent.type(box(container), "تاسك");
    await screen.findByRole("listbox");
    expect(screen.getByRole("combobox")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getAllByRole("option")[0]).toHaveAttribute("aria-selected", "true");
  });
});

describe("landing on a part of a page", () => {
  it("scrolls to it and lights it once the page has drawn it", async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    const { container } = renderMenu({ route: "/admin/settings#s-ai", role: "admin", screens: ["admin"], page: <div id="s-ai">the AI card</div> });
    await waitFor(() => expect(container.querySelector("#s-ai")).toHaveClass("is-found"));
    expect(scroll).toHaveBeenCalled();
  });

  it("waits for a part the page draws later, and lights the whole field, not the bare box", async () => {
    Element.prototype.scrollIntoView = vi.fn();
    function Late() {
      const [drawn, setDrawn] = useState(false);
      useEffect(() => {
        const timer = window.setTimeout(() => setDrawn(true), 80);
        return () => window.clearTimeout(timer);
      }, []);
      return drawn ? (
        <div className="field" data-testid="field">
          <input id="settings-rate_keywords" />
        </div>
      ) : (
        <div>loading</div>
      );
    }
    renderMenu({ route: "/admin/settings#settings-rate_keywords", role: "admin", screens: ["admin"], page: <Late /> });
    expect(screen.queryByTestId("field")).toBeNull();
    await waitFor(() => expect(screen.getByTestId("field")).toHaveClass("is-found"));
    expect(document.getElementById("settings-rate_keywords")).not.toHaveClass("is-found");
  });

  it("does nothing, and keeps nothing waiting, for a part that never comes", async () => {
    const { container } = renderMenu({ route: "/admin/settings#nowhere", role: "admin", screens: ["admin"] });
    await waitFor(() => expect(group(container, "mine")).not.toBeNull());
    expect(container.querySelector(".is-found")).toBeNull();
  });
});
