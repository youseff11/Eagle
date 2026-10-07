import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatRow, ThreadEntry } from "../api/types";
import { forgetDrafts } from "../components/chat/Composer";
import { entry, renderChats as render, row, visible } from "../test/chat";
import { jsonResponse } from "../test/helpers";

beforeEach(() => {
  visible("visible");
  forgetDrafts();
});
afterEach(() => {
  vi.unstubAllGlobals();
  visible("visible");
});

type Call = { url: string; init?: RequestInit };
const posts = (calls: Call[], path: string) => calls.filter((c) => c.init?.method === "POST" && c.url === path);
const body = (call: Call) => JSON.parse(String(call.init?.body));

const MUTE = "/api/v1/chats/mute/";
const UNSEND = "/api/v1/chats/unsend/";

const team = row("g1", { group: true, team: true, room: 1, label: "Work", url: "/ops/chats/g/1/" });

/** A work group's thread that a test can change under the page: the row says whether it is muted. */
function group(messages: ThreadEntry[], extra: Partial<ChatRow> = {}) {
  const state = { muted: false, messages };
  const thread = () => jsonResponse({ ok: true, client: { ...team, ...extra, muted: state.muted }, messages: state.messages });
  const routes = {
    "/api/v1/groups/": (url: URL) => {
      if (url.pathname.endsWith("/members/")) return jsonResponse({ ok: true, members: [], can_add: false, addable: [] });
      if (url.pathname.endsWith("/handin-tasks/")) return jsonResponse({ ok: true, tasks: [] });
      return thread();
    },
  };
  return { state, routes };
}

describe("muting a conversation", () => {
  it("has a button that says what it will do, and asks the server with the conversation's own code", async () => {
    const { state, routes } = group([entry(1, { uid: "g1-1", body: "hello", kind: "out", sender: "Sam" })]);
    const { calls } = render("/chats/g1?type=groups", { role: { role: "operation" } }, {
      ...routes,
      [MUTE]: (_url, init) => {
        state.muted = JSON.parse(String(init?.body)).muted;
        return jsonResponse({ ok: true, muted: state.muted });
      },
    });
    const button = await screen.findByRole("button", { name: /كتم/ });
    expect(button).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(button);
    await waitFor(() => expect(posts(calls, MUTE)).toHaveLength(1));
    expect(body(posts(calls, MUTE)[0]!)).toEqual({ source: "g1", muted: true });
    // The row came back muted: the button says so and the next press un-mutes.
    const muted = await screen.findByRole("button", { name: /مكتوم/ });
    expect(muted).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(muted);
    await waitFor(() => expect(posts(calls, MUTE)).toHaveLength(2));
    expect(body(posts(calls, MUTE)[1]!)).toEqual({ source: "g1", muted: false });
    expect(await screen.findByRole("button", { name: /كتم/ })).toHaveAttribute("aria-pressed", "false");
  });

  it("is not offered for a colleague nobody has written to yet, which has no room to mute", async () => {
    render("/chats/u5?type=staff", {
      thread: { client: row("u5", { staff: true, label: "Sam", initials: "SM", room: 0 }), messages: [entry(1, { uid: "g0-1" })] },
    });
    await screen.findByText("message 1");
    expect(screen.queryByRole("button", { name: /كتم/ })).not.toBeInTheDocument();
  });

  it("marks a muted conversation in the list with a bell, and its number is the quiet kind", async () => {
    render("/chats?type=groups", {
      lists: { groups: [row("g1", { group: true, room: 1, label: "Work", unread: 3, muted: true }), row("g2", { group: true, room: 2, label: "Other", unread: 2 })] },
    });
    const muted = (await screen.findByText("Work")).closest("a") as HTMLElement;
    const other = screen.getByText("Other").closest("a") as HTMLElement;
    expect(within(muted).getByTitle("مكتوم")).toBeInTheDocument();
    expect(within(other).queryByTitle("مكتوم")).toBeNull();
    expect(within(muted).getByText("3")).toHaveClass("is-muted");
    expect(within(other).getByText("2")).not.toHaveClass("is-muted");
  });
});

describe("taking back a message", () => {
  const mine = entry(5, { uid: "g1-5", kind: "out", body: "oops wrong chat", mine: true, sender: "Nour", can_unsend: true });
  const theirs = entry(6, { uid: "g1-6", kind: "in", body: "a colleague wrote", sender: "Sam", can_unsend: false });
  const gone = entry(7, { uid: "g1-7", kind: "out", body: "", mine: true, sender: "Nour", unsent: true, can_unsend: false });

  it("puts the button only on the messages the server says may be taken back", async () => {
    const { routes } = group([mine, theirs]);
    render("/chats/g1?type=groups", {}, routes);
    await screen.findByText("oops wrong chat");
    expect(screen.getAllByRole("button", { name: "امسح الرسالة" })).toHaveLength(1);
    expect(within(document.querySelector('[data-uid="g1-5"]') as HTMLElement).getByRole("button", { name: "امسح الرسالة" })).toBeInTheDocument();
    expect(within(document.querySelector('[data-uid="g1-6"]') as HTMLElement).queryByRole("button", { name: "امسح الرسالة" })).toBeNull();
  });

  it("asks first, then takes it back and reads the thread again", async () => {
    const { state, routes } = group([mine, theirs]);
    const { calls } = render("/chats/g1?type=groups", {}, {
      ...routes,
      [UNSEND]: () => {
        state.messages = [gone, theirs];
        return jsonResponse({ ok: true, uid: "g1-5" });
      },
    });
    await userEvent.click(await screen.findByRole("button", { name: "امسح الرسالة" }));
    expect(posts(calls, UNSEND)).toHaveLength(0);
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "امسح" }));
    await waitFor(() => expect(posts(calls, UNSEND)).toHaveLength(1));
    expect(body(posts(calls, UNSEND)[0]!)).toEqual({ source: "g1", uid: "g1-5" });
    expect(await screen.findByText("الرسالة اتمسحت")).toBeInTheDocument();
    expect(screen.queryByText("oops wrong chat")).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("can be cancelled, and nothing is sent", async () => {
    const { routes } = group([mine]);
    const { calls } = render("/chats/g1?type=groups", {}, routes);
    await userEvent.click(await screen.findByRole("button", { name: "امسح الرسالة" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "إلغاء" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(posts(calls, UNSEND)).toHaveLength(0);
    expect(screen.getByText("oops wrong chat")).toBeInTheDocument();
  });

  it("says why when it is refused and leaves the question open", async () => {
    const { routes } = group([mine]);
    render("/chats/g1?type=groups", {}, { ...routes, [UNSEND]: () => jsonResponse({ ok: false, error: "not_allowed" }, 403) });
    await userEvent.click(await screen.findByRole("button", { name: "امسح الرسالة" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "امسح" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("مقدرتش أمسح الرسالة");
  });

  it("draws a message taken back as one line, with nothing to answer, react to, forward or open", async () => {
    const { routes } = group([gone, theirs]);
    render("/chats/g1?type=groups", {}, routes);
    await screen.findByText("الرسالة اتمسحت");
    const bubble = document.querySelector('[data-uid="g1-7"]') as HTMLElement;
    expect(bubble).toHaveClass("bub--gone");
    for (const name of ["رد", "رياكت", "تحويل", "امسح الرسالة"]) expect(within(bubble).queryByRole("button", { name })).toBeNull();
    // A message beside it is untouched.
    expect(within(document.querySelector('[data-uid="g1-6"]') as HTMLElement).getByRole("button", { name: "رد" })).toBeInTheDocument();
  });
});
