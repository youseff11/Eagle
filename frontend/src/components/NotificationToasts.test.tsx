import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { qk } from "../api/keys";
import type { NotificationItem } from "../api/types";
import { chime } from "../lib/chime";
import { navigation } from "../lib/navigation";
import { jsonResponse, mockFetch, note, renderWithProviders } from "../test/helpers";
import { NotificationToasts } from "./NotificationToasts";
import { MAX_TOASTS, ToastProvider } from "./Toasts";

vi.mock("../lib/chime", () => ({
  chime: vi.fn(),
  armSound: vi.fn(() => () => undefined),
  resetSound: vi.fn(),
}));

/** What the server will answer for the list, changed between looks the way a doorbell makes it. */
function listing(initial: NotificationItem[]) {
  const state = { items: initial };
  const mocked = mockFetch({
    "/api/v1/notifications/": () =>
      jsonResponse({ ok: true, items: [...state.items].sort((a, b) => b.id - a.id), next_before: null, unread: 0 }),
  });
  vi.stubGlobal("fetch", mocked.fn);
  return { state, calls: mocked.calls };
}

/** The page is open and the first answer is in: what is listed now is what the page opened with. */
async function open(initial: NotificationItem[], options: Parameters<typeof renderWithProviders>[1] = {}) {
  const server = listing(initial);
  const view = renderWithProviders(
    <ToastProvider>
      <NotificationToasts />
    </ToastProvider>,
    options,
  );
  await waitFor(() => expect(server.calls).toHaveLength(1));
  // The query hands its answer to the component on a timer of its own: wait for it, or a later
  // answer would be the first the component ever sees (and so be taken for "what the page opened with").
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
  return {
    server,
    view,
    /** The doorbell: the list is asked for again, and the answer is in when this returns. */
    async ring() {
      const before = server.calls.length;
      await act(async () => {
        await view.client.invalidateQueries({ queryKey: qk.notifications });
      });
      expect(server.calls.length).toBeGreaterThan(before);
    },
  };
}

const titles = () => Array.from(document.querySelectorAll(".toast__title")).map((node) => node.textContent);

beforeEach(() => {
  vi.mocked(chime).mockClear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("NotificationToasts", () => {
  it("does not announce what was already there when the page opened", async () => {
    await open([note(1), note(2)]);
    expect(document.querySelector(".toast")).toBeNull();
    expect(chime).not.toHaveBeenCalled();
  });

  it("shows a toast and rings once for a notification that arrives afterwards", async () => {
    const page = await open([note(1)]);
    page.server.state.items.push(note(2, { title_ar: "مهمة جديدة", body_ar: "اتسلّمت" }));
    await page.ring();

    expect(await screen.findByText("مهمة جديدة")).toBeInTheDocument();
    expect(screen.getByText("اتسلّمت")).toBeInTheDocument();
    expect(screen.queryByText("عنوان 1")).toBeNull();
    // An ordinary notice: the soft single chime, not the loud pair.
    expect(chime).toHaveBeenCalledTimes(1);
    expect(chime).toHaveBeenCalledWith(1, 988, true);
  });

  it("rings the loud pair when the server marked the notification with a sound", async () => {
    const page = await open([note(1)]);
    page.server.state.items.push(note(2, { sound: true }));
    await page.ring();

    await screen.findByText("عنوان 2");
    expect(chime).toHaveBeenCalledTimes(1);
    expect(chime).toHaveBeenCalledWith(2, 784);
  });

  it("rings once for a batch, and shows them oldest first", async () => {
    const page = await open([note(1)]);
    page.server.state.items.push(note(2), note(3, { sound: true }), note(4));
    await page.ring();

    await screen.findByText("عنوان 4");
    expect(chime).toHaveBeenCalledTimes(1);
    expect(chime).toHaveBeenCalledWith(2, 784);
    expect(titles()).toEqual(["عنوان 2", "عنوان 3", "عنوان 4"]);
  });

  it("keeps at most four toasts, the newest", async () => {
    const page = await open([note(1)]);
    page.server.state.items.push(...[2, 3, 4, 5, 6, 7].map((id) => note(id)));
    await page.ring();

    await screen.findByText("عنوان 7");
    expect(titles()).toHaveLength(MAX_TOASTS);
    expect(titles()).toEqual(["عنوان 4", "عنوان 5", "عنوان 6", "عنوان 7"]);
  });

  it("says nothing about a notification that is already read", async () => {
    const page = await open([note(1)]);
    page.server.state.items.push(note(2, { read: true }));
    await page.ring();

    expect(document.querySelector(".toast")).toBeNull();
    expect(chime).not.toHaveBeenCalled();
    // ... and it is not announced later either, when something else arrives.
    page.server.state.items.push(note(3));
    await page.ring();
    await screen.findByText("عنوان 3");
    expect(titles()).toEqual(["عنوان 3"]);
  });

  it("announces a notification once, however often the list is asked for", async () => {
    const page = await open([note(1)]);
    page.server.state.items.push(note(2));
    await page.ring();
    await screen.findByText("عنوان 2");
    await page.ring();
    await page.ring();

    expect(titles()).toEqual(["عنوان 2"]);
    expect(chime).toHaveBeenCalledTimes(1);
  });

  it("is not fooled by an empty page: the first notification ever is announced", async () => {
    const page = await open([]);
    page.server.state.items.push(note(1));
    await page.ring();

    expect(await screen.findByText("عنوان 1")).toBeInTheDocument();
  });

  it("writes the toast in the page's language", async () => {
    const page = await open([note(1)], { lang: "en" });
    page.server.state.items.push(note(2));
    await page.ring();

    expect(await screen.findByText("Title 2")).toBeInTheDocument();
    expect(screen.getByText("Body 2")).toBeInTheDocument();
  });

  it("looks like the level: a danger notice is an alert", async () => {
    const page = await open([note(1)]);
    page.server.state.items.push(note(2, { level: "danger" }), note(3, { level: "success" }));
    await page.ring();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveClass("toast", "toast--danger");
    expect(screen.getByText("عنوان 3").closest(".toast")).toHaveClass("toast--success");
  });

  it("opens a path on this site when the toast is clicked", async () => {
    const assign = vi.spyOn(navigation, "assign").mockImplementation(() => undefined);
    const page = await open([note(1)]);
    page.server.state.items.push(note(2, { url: "/ops/chats/u/9/" }));
    await page.ring();
    await userEvent.click(await screen.findByText("عنوان 2"));

    expect(assign).toHaveBeenCalledWith("/ops/chats/u/9/");
  });

  it("does not follow an address that leaves this site", async () => {
    const assign = vi.spyOn(navigation, "assign").mockImplementation(() => undefined);
    const page = await open([note(1)]);
    page.server.state.items.push(
      note(2, { url: "https://evil.example/x" }),
      note(3, { url: "javascript:alert(1)" }),
      note(4, { url: "//evil.example" }),
    );
    await page.ring();
    for (const id of [2, 3, 4]) {
      const toast = (await screen.findByText(`عنوان ${id}`)).closest(".toast") as HTMLElement;
      await userEvent.click(toast);
      expect(toast.style.cursor).toBe("");
    }

    expect(assign).not.toHaveBeenCalled();
  });

  it("closes with its button, and a click on the button does not open the link", async () => {
    const assign = vi.spyOn(navigation, "assign").mockImplementation(() => undefined);
    const page = await open([note(1)]);
    page.server.state.items.push(note(2, { url: "/ops/chats/" }));
    await page.ring();
    await screen.findByText("عنوان 2");
    await userEvent.click(screen.getByRole("button", { name: "اقفل" }));

    await waitFor(() => expect(screen.queryByText("عنوان 2")).toBeNull());
    expect(assign).not.toHaveBeenCalled();
  });

  it("asks again every 15 seconds while the socket is down", async () => {
    // Only the interval is faked: it is what the fallback poll is made of, and the rest of the
    // machinery (the query's own scheduling, the toast) keeps real time.
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const page = await open([note(1)]);
    page.server.state.items.push(note(2));
    expect(document.querySelector(".toast")).toBeNull();

    await act(async () => {
      vi.advanceTimersByTime(15000);
    });

    expect(await screen.findByText("عنوان 2")).toBeInTheDocument();
  });
});
