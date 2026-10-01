import { QueryClient } from "@tanstack/react-query";
import { Route, Routes } from "react-router";
import { vi } from "vitest";
import type { ChatKind, ChatRow, ThreadEntry, ThreadFile } from "../api/types";
import { ChatsPage } from "../pages/ChatsPage";
import { jsonResponse, me, mockFetch, renderWithProviders, type Routes as FetchRoutes } from "./helpers";

export function visible(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
}

export function row(code: string, overrides: Partial<ChatRow> = {}): ChatRow {
  return {
    code,
    group: false,
    url: `/ops/chats/${code}/`,
    label: code,
    text: `last words of ${code}`,
    outgoing: false,
    status: "",
    receipt: "",
    time: "8:05 PM",
    date: "2026-10-01",
    channel: "whatsapp",
    window_open: true,
    minutes_left: 600,
    unread: 0,
    ...overrides,
  };
}

export function entry(id: number, overrides: Partial<ThreadEntry> = {}): ThreadEntry {
  return {
    uid: `in-${id}`,
    id,
    kind: "in",
    body: `message ${id}`,
    subject: "",
    channel: "whatsapp",
    status: "",
    error: "",
    sender: "",
    sender_id: 0,
    task_code: "",
    is_delivery: false,
    quote: "",
    quote_who: "",
    time: "8:00 AM",
    date: "2026-10-01",
    files: [],
    mine: false,
    receipt: "",
    seen_by: [],
    forwarded: false,
    reactions: [],
    ...overrides,
  };
}

export function file(overrides: Partial<ThreadFile> = {}): ThreadFile {
  return {
    id: 1,
    url: "/files/in/doc.pdf",
    name: "doc.pdf",
    size: 10,
    mime: "application/pdf",
    voice: false,
    audio: false,
    length: "",
    image: false,
    ...overrides,
  };
}

export interface Setup {
  lists?: Partial<Record<ChatKind, ChatRow[]>>;
  thread?: { client: ChatRow; messages: ThreadEntry[] } | Response;
  types?: ChatKind[];
  role?: Parameters<typeof me>[0];
}

export function renderChats(
  path: string,
  setup: Setup = {},
  extra: FetchRoutes = {},
  options: { lang?: "ar" | "en"; client?: QueryClient } = {},
) {
  const types = setup.types ?? ["clients", "groups", "staff"];
  const base = me(setup.role ?? { role: "operation" });
  const defaults: FetchRoutes = {
    "/api/v1/me/": () => jsonResponse({ ...base, chats: { types } }),
    "/api/v1/chats/": (url) => {
      const kind = (url.searchParams.get("type") ?? "clients") as ChatKind;
      return jsonResponse({ ok: true, items: setup.lists?.[kind] ?? [] });
    },
    "/api/v1/clients/": () =>
      setup.thread instanceof Response
        ? setup.thread
        : jsonResponse(setup.thread ? { ok: true, ...setup.thread } : { ok: false, error: "not_found" }, setup.thread ? 200 : 404),
    "/api/v1/groups/": () =>
      setup.thread instanceof Response ? setup.thread : jsonResponse({ ok: true, ...(setup.thread ?? { client: row("g1"), messages: [] }) }),
    "/api/v1/staff/": () =>
      setup.thread instanceof Response ? setup.thread : jsonResponse({ ok: true, ...(setup.thread ?? { client: row("u5"), messages: [] }) }),
  };
  // The first route that matches wins, so what a test adds goes in front of the defaults.
  const routes: FetchRoutes = { ...extra };
  for (const [prefix, answer] of Object.entries(defaults)) if (!(prefix in routes)) routes[prefix] = answer;
  const mocked = mockFetch(routes);
  vi.stubGlobal("fetch", mocked.fn);
  const view = renderWithProviders(
    <Routes>
      <Route path="chats" element={<ChatsPage />} />
      <Route path="chats/:code" element={<ChatsPage />} />
    </Routes>,
    { route: path, ...options },
  );
  return { ...view, calls: mocked.calls };
}
