import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";
import type { Lang, MeResponse, NotificationItem, Theme } from "../api/types";
import { PreferencesProvider } from "../i18n/Preferences";

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export function me(overrides: Partial<MeResponse["user"]> = {}, unread = 0): MeResponse {
  return {
    ok: true,
    version: 1,
    user: {
      id: 7,
      username: "person_ops",
      name: "Nour Operation",
      short_name: "Nour",
      initials: "NO",
      role: "operation",
      is_admin: false,
      lang: "ar",
      theme: "dark",
      ...overrides,
    },
    chats: { types: ["clients", "groups", "staff"] },
    unread_notifications: unread,
    realtime: { path: "/ws/events/", ping_seconds: 25 },
    server_time: "8:00 AM",
  };
}

export function note(id: number, overrides: Partial<NotificationItem> = {}): NotificationItem {
  return {
    id,
    level: "info",
    title_ar: `عنوان ${id}`,
    title_en: `Title ${id}`,
    body_ar: `نص ${id}`,
    body_en: `Body ${id}`,
    url: "",
    sound: false,
    created: "8:00 AM",
    date: "2026-10-01",
    read: false,
    ...overrides,
  };
}

/** Answers `fetch` by path: a function per path prefix, the first match wins. */
export type Routes = Record<string, (url: URL, init: RequestInit | undefined) => Response | Promise<Response>>;

export function mockFetch(routes: Routes) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fn = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = new URL(String(input), "http://localhost");
    calls.push({ url: url.pathname + url.search, init });
    const key = Object.keys(routes).find((prefix) => url.pathname.startsWith(prefix));
    if (!key) return jsonResponse({ ok: false, error: "not_found" }, 404);
    return routes[key]!(url, init);
  };
  return { fn, calls };
}

export function renderWithProviders(
  ui: ReactElement,
  options: { route?: string; lang?: Lang; theme?: Theme } = {},
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 } } });
  const result = render(
    <QueryClientProvider client={client}>
      <PreferencesProvider initialLang={options.lang ?? "ar"} initialTheme={options.theme ?? "dark"}>
        <MemoryRouter initialEntries={[options.route ?? "/"]}>{ui}</MemoryRouter>
      </PreferencesProvider>
    </QueryClientProvider>,
  );
  return { ...result, client };
}
