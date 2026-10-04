import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * `static/js/pages.js`: the language and theme switch of the pages that are still plain Django (sign-in, the legal pages, the 403
 * page). Run as the browser runs it: read the file, execute it against a page that looks like theirs, fire DOMContentLoaded.
 */
const source = readFileSync(resolve(import.meta.dirname, "../../../static/js/pages.js"), "utf-8");

const PAGE = `
  <div class="seg">
    <button type="button" data-lang-btn="ar">AR</button>
    <button type="button" data-lang-btn="en">EN</button>
  </div>
  <button id="themeToggle" type="button" data-ar-title="تبديل" data-en-title="Toggle"><span id="themeIcon"><svg><use href="#i-moon"></use></svg></span></button>
  <h1 id="title" data-ar="مرحبا" data-en="Welcome">مرحبا</h1>
  <input id="user" data-ar-ph="اسم" data-en-ph="Name">
  <p id="rich" data-html data-ar="<b>عربي</b>" data-en="<b>English</b>"></p>
`;

function boot(cfg: Record<string, string>) {
  document.documentElement.setAttribute("lang", "ar");
  document.documentElement.setAttribute("dir", "rtl");
  document.documentElement.setAttribute("data-theme", cfg.theme ?? "dark");
  document.body.innerHTML = PAGE;
  (window as unknown as { EAGLE_CFG: unknown }).EAGLE_CFG = cfg;
  // The script waits for DOMContentLoaded. Take its handler instead of leaving a listener on `document` for the next test.
  let start: EventListener | undefined;
  const add = vi.spyOn(document, "addEventListener").mockImplementation((type: string, listener: unknown) => {
    if (type === "DOMContentLoaded") start = listener as EventListener;
  });
  new Function(source)();
  add.mockRestore();
  start!(new Event("DOMContentLoaded"));
}

const text = (id: string) => document.getElementById(id)!.textContent;
const click = (selector: string) => (document.querySelector(selector) as HTMLElement).click();

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: true })));
  vi.stubGlobal("fetch", fetchMock);
  document.cookie = "csrftoken=token123";
  document.cookie = "eagle_lang=; max-age=0; path=/";
  document.cookie = "eagle_theme=; max-age=0; path=/";
});

afterEach(() => {
  vi.unstubAllGlobals();
  delete (window as unknown as { EAGLE_CFG?: unknown }).EAGLE_CFG;
});

describe("pages.js", () => {
  it("draws the page in the language the server said and sends nothing while doing it", () => {
    boot({ lang: "en", theme: "dark", prefsUrl: "/api/prefs/" });
    expect(text("title")).toBe("Welcome");
    expect(document.documentElement.getAttribute("lang")).toBe("en");
    expect(document.documentElement.getAttribute("dir")).toBe("ltr");
    expect((document.getElementById("user") as HTMLInputElement).getAttribute("placeholder")).toBe("Name");
    expect(document.getElementById("themeToggle")!.getAttribute("title")).toBe("Toggle");
    expect(document.getElementById("rich")!.innerHTML).toBe("<b>English</b>");
    expect(document.querySelector('[data-lang-btn="en"]')!.classList.contains("is-active")).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("switches the language, keeps it in the cookie and tells the account with the CSRF token", () => {
    boot({ lang: "ar", theme: "dark", prefsUrl: "/api/prefs/" });
    click('[data-lang-btn="en"]');
    expect(text("title")).toBe("Welcome");
    expect(document.documentElement.getAttribute("dir")).toBe("ltr");
    expect(document.cookie).toContain("eagle_lang=en");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0]! as [string, RequestInit];
    expect(url).toBe("/api/prefs/");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["X-CSRFToken"]).toBe("token123");
    expect((init.body as FormData).get("lang")).toBe("en");
    click('[data-lang-btn="ar"]');
    expect(text("title")).toBe("مرحبا");
    expect(document.documentElement.getAttribute("dir")).toBe("rtl");
  });

  it("switches the theme, swaps the icon and remembers it", () => {
    boot({ lang: "ar", theme: "dark", prefsUrl: "/api/prefs/" });
    expect(document.querySelector("#themeIcon use")!.getAttribute("href")).toBe("#i-moon");
    click("#themeToggle");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(document.querySelector("#themeIcon use")!.getAttribute("href")).toBe("#i-sun");
    expect(document.cookie).toContain("eagle_theme=light");
    expect((fetchMock.mock.calls[0]![1] as RequestInit).body instanceof FormData).toBe(true);
    expect(((fetchMock.mock.calls[0]![1] as RequestInit).body as FormData).get("theme")).toBe("light");
    click("#themeToggle");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("is not stopped by a refused or failed save: the cookie already holds the choice", async () => {
    const failing = Promise.reject(new Error("offline"));
    const handled = vi.spyOn(failing, "catch");
    fetchMock.mockReturnValue(failing);
    boot({ lang: "ar", theme: "dark", prefsUrl: "/api/prefs/" });
    click('[data-lang-btn="en"]');
    await Promise.resolve();
    // The rejection is answered by the script itself, not left for the browser to report.
    expect(handled).toHaveBeenCalledTimes(1);
    expect(text("title")).toBe("Welcome");
    expect(document.cookie).toContain("eagle_lang=en");
  });

  it("does not call anything when the page has no prefs address", () => {
    boot({ lang: "ar", theme: "light" });
    click('[data-lang-btn="en"]');
    click("#themeToggle");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(document.cookie).toContain("eagle_lang=en");
    expect(document.cookie).toContain("eagle_theme=dark");
  });
});
