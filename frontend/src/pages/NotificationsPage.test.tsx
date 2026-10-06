import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { NotificationsResponse } from "../api/types";
import { jsonResponse, mockFetch, note, renderWithProviders, type Routes } from "../test/helpers";
import { NotificationsPage } from "./NotificationsPage";

afterEach(() => vi.unstubAllGlobals());

function page(items: ReturnType<typeof note>[], next: number | null = null, unread = items.filter((n) => !n.read).length): NotificationsResponse {
  return { ok: true, items, next_before: next, unread };
}

function serve(routes: Routes) {
  const mocked = mockFetch(routes);
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

describe("NotificationsPage", () => {
  it("lists the notifications in the chosen language with the server's date and time", async () => {
    serve({ "/api/v1/notifications/": () => jsonResponse(page([note(1), note(2, { read: true })])) });
    const { unmount } = renderWithProviders(<NotificationsPage />, { lang: "ar" });
    expect(await screen.findByText("عنوان 1")).toBeInTheDocument();
    expect(screen.getByText("نص 2")).toBeInTheDocument();
    expect(screen.getAllByText(/2026-10-01 8:00 AM/)).toHaveLength(2);
    unmount();

    serve({ "/api/v1/notifications/": () => jsonResponse(page([note(1)])) });
    renderWithProviders(<NotificationsPage />, { lang: "en" });
    expect(await screen.findByText("Title 1")).toBeInTheDocument();
    expect(screen.queryByText("عنوان 1")).not.toBeInTheDocument();
  });

  it("marks the unread ones so they stand out", async () => {
    serve({ "/api/v1/notifications/": () => jsonResponse(page([note(1), note(2, { read: true })])) });
    const { container } = renderWithProviders(<NotificationsPage />);
    await screen.findByText("عنوان 1");
    expect(container.querySelector('[data-notification="1"]')).toHaveClass("is-unread");
    expect(container.querySelector('[data-notification="2"]')).not.toHaveClass("is-unread");
  });

  it("draws a link only for an address on this site", async () => {
    serve({
      "/api/v1/notifications/": () =>
        jsonResponse(
          page([
            note(1, { url: "/tasks/TSK-00001/?room=3" }),
            note(2, { url: "javascript:alert(document.cookie)" }),
            note(3, { url: "https://evil.example/phish" }),
            note(4, { url: "//evil.example" }),
            note(5, { url: "" }),
          ]),
        ),
    });
    renderWithProviders(<NotificationsPage />);
    await screen.findByText("عنوان 1");
    const links = screen.getAllByRole("link", { name: "افتح" });
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/tasks/TSK-00001/?room=3");
  });

  it("opening an unread notification marks just that one read", async () => {
    const { calls } = serve({
      "/api/v1/notifications/read/": () => jsonResponse({ ok: true, updated: 1, unread: 0 }),
      "/api/v1/notifications/": () => jsonResponse(page([note(1, { url: "/tasks/T/" })])),
    });
    renderWithProviders(<NotificationsPage />);
    const link = await screen.findByRole("link", { name: "افتح" });
    link.addEventListener("click", (event) => event.preventDefault()); // jsdom does not navigate
    await userEvent.click(link);
    await waitFor(() => expect(calls.some((c) => c.url === "/api/v1/notifications/read/")).toBe(true));
    const post = calls.find((c) => c.url === "/api/v1/notifications/read/")!;
    expect(post.init?.body).toBe('{"ids":[1]}');
  });

  it("names who sent a notification a person wrote, with their picture and role, and says nothing for the system's own", async () => {
    serve({
      "/api/v1/notifications/": () =>
        jsonResponse(
          page([
            note(1, { sender: { id: 5, name: "Sami Support", initials: "SS", avatar: "/files/avatars/sami.png", role: "support" } }),
            note(2, { sender: { id: 6, name: "Mona", initials: "MS", avatar: null, role: "team_lead" } }),
            note(3),
          ]),
        ),
    });
    const { container } = renderWithProviders(<NotificationsPage />);
    await screen.findByText("عنوان 1");
    const first = container.querySelector('[data-notification="1"] [data-sender]') as HTMLElement;
    expect(within(first).getByText("Sami Support")).toBeInTheDocument();
    expect(within(first).getByText("دعم فني")).toBeInTheDocument();
    expect(first.querySelector("img.avatar__img")).toHaveAttribute("src", "/files/avatars/sami.png");
    const second = container.querySelector('[data-notification="2"] [data-sender]') as HTMLElement;
    expect(within(second).getByText("MS")).toHaveClass("avatar");
    expect(within(second).getByText("تيم ليدر")).toBeInTheDocument();
    expect(container.querySelector('[data-notification="3"] [data-sender]')).toBeNull();
  });

  it("says the role in English when asked", async () => {
    serve({
      "/api/v1/notifications/": () =>
        jsonResponse(page([note(1, { sender: { id: 5, name: "Sami Support", initials: "SS", avatar: null, role: "support" } })])),
    });
    renderWithProviders(<NotificationsPage />, { lang: "en" });
    expect(await screen.findByText("Technical support")).toBeInTheDocument();
  });

  it("has a button beside each unread notification, and none beside a read one", async () => {
    serve({ "/api/v1/notifications/": () => jsonResponse(page([note(1), note(2, { read: true }), note(3)])) });
    const { container } = renderWithProviders(<NotificationsPage />);
    await screen.findByText("عنوان 1");
    expect(within(container.querySelector('[data-notification="1"]') as HTMLElement).getByRole("button", { name: /علّمه مقروء/ })).toBeInTheDocument();
    expect(within(container.querySelector('[data-notification="2"]') as HTMLElement).queryByRole("button", { name: /علّمه مقروء/ })).toBeNull();
    expect(screen.getAllByRole("button", { name: /علّمه مقروء/ })).toHaveLength(2);
  });

  it("the button marks just that notification read and does not open it", async () => {
    const { calls } = serve({
      "/api/v1/notifications/read/": () => jsonResponse({ ok: true, updated: 1, unread: 1 }),
      "/api/v1/notifications/": () => jsonResponse(page([note(1, { url: "/tasks/T/" }), note(2)])),
    });
    const { container } = renderWithProviders(<NotificationsPage />);
    await screen.findByText("عنوان 2");
    await userEvent.click(within(container.querySelector('[data-notification="2"]') as HTMLElement).getByRole("button", { name: /علّمه مقروء/ }));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/v1/notifications/read/")).toBe(true));
    const posts = calls.filter((c) => c.url === "/api/v1/notifications/read/");
    expect(posts).toHaveLength(1);
    expect(posts[0]!.init?.body).toBe('{"ids":[2]}');
  });

  it("marks everything read on request, and the button rests when nothing is unread", async () => {
    const { calls } = serve({
      "/api/v1/notifications/read/": () => jsonResponse({ ok: true, updated: 2, unread: 0 }),
      "/api/v1/notifications/": () => jsonResponse(page([note(1), note(2)])),
    });
    renderWithProviders(<NotificationsPage />);
    const button = await screen.findByRole("button", { name: /علّم الكل مقروء/ });
    await waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);
    await waitFor(() => expect(calls.some((c) => c.url === "/api/v1/notifications/read/")).toBe(true));
    expect(calls.find((c) => c.url === "/api/v1/notifications/read/")!.init?.body).toBe('{"all":true}');
  });

  it("has nothing to mark when everything is read", async () => {
    serve({ "/api/v1/notifications/": () => jsonResponse(page([note(1, { read: true })], null, 0)) });
    renderWithProviders(<NotificationsPage />);
    await screen.findByText("عنوان 1");
    expect(screen.getByRole("button", { name: /علّم الكل مقروء/ })).toBeDisabled();
  });

  it("loads the next page with the cursor and adds it below", async () => {
    const { calls } = serve({
      "/api/v1/notifications/": (url) =>
        url.searchParams.get("before") === "2"
          ? jsonResponse(page([note(1)], null, 3))
          : jsonResponse(page([note(3), note(2)], 2, 3)),
    });
    renderWithProviders(<NotificationsPage />);
    await screen.findByText("عنوان 3");
    expect(screen.queryByText("عنوان 1")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "المزيد" }));
    expect(await screen.findByText("عنوان 1")).toBeInTheDocument();
    expect(calls.map((c) => c.url)).toContain("/api/v1/notifications/?limit=20&before=2");
    expect(screen.queryByRole("button", { name: "المزيد" })).not.toBeInTheDocument();
  });

  it("says so when there is nothing, and when it could not load", async () => {
    serve({ "/api/v1/notifications/": () => jsonResponse(page([])) });
    const first = renderWithProviders(<NotificationsPage />);
    expect(await screen.findByText("مفيش تنبيهات.")).toBeInTheDocument();
    first.unmount();

    serve({ "/api/v1/notifications/": () => jsonResponse({ ok: false, error: "server" }, 500) });
    renderWithProviders(<NotificationsPage />);
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("حصلت مشكلة في التحميل.")).toBeInTheDocument();
  });
});
