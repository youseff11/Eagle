import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ThreadEntry } from "../api/types";
import { forgetDrafts } from "../components/chat/Composer";
import { entry, renderChats as render, row, visible } from "../test/chat";

/** In a group, under a message of ours, the names of the others who have read it. */

beforeEach(() => {
  visible("visible");
  forgetDrafts();
});
afterEach(() => {
  vi.unstubAllGlobals();
  visible("visible");
});

const mine = (id: number, seen: string[], extra: Partial<ThreadEntry> = {}) =>
  entry(id, { uid: `g2-${id}`, kind: "out", mine: true, sender: "Nour", sender_id: 7, body: `plan ${id}`, seen_by: seen, ...extra });

async function openGroup(messages: ThreadEntry[], lang: "ar" | "en" = "ar", group: Partial<Parameters<typeof row>[1]> = {}) {
  const view = render(
    "/chats/g2",
    { thread: { client: row("g2", { group: true, team: true, channel: "", ...group }), messages } },
    {},
    { lang },
  );
  await screen.findByRole("textbox", { name: lang === "ar" ? "الرسالة" : "Message" });
  return view;
}

const lines = () => [...document.querySelectorAll(".bub__seen")];

describe("who has seen it, in a group", () => {
  it("names the others who have read a message of ours, under it", async () => {
    await openGroup([mine(5, ["Mona", "Sam"])]);
    expect(lines()).toHaveLength(1);
    expect(lines()[0]).toHaveTextContent("شافها: Mona، Sam");
    // Under that message, not elsewhere.
    expect(document.querySelector('[data-uid="g2-5"] .bub__seen')).not.toBeNull();
  });

  it("says it in English too", async () => {
    await openGroup([mine(5, ["Mona", "Sam"])], "en");
    expect(lines()[0]).toHaveTextContent("Seen by: Mona, Sam");
  });

  it("names three and counts the rest, with everybody's name on a hover", async () => {
    await openGroup([mine(5, ["Mona", "Sam", "Hadi", "Lara", "Omar"])]);
    expect(lines()[0]).toHaveTextContent("شافها: Mona، Sam، Hadi و2 كمان");
    expect(lines()[0]).toHaveAttribute("title", "Mona، Sam، Hadi، Lara، Omar");
  });

  it("is under each message by what has read it, and not at all under one nobody has read", async () => {
    await openGroup([mine(4, ["Mona", "Sam"]), mine(5, ["Mona"]), mine(6, [])]);
    expect(document.querySelector('[data-uid="g2-4"] .bub__seen')).toHaveTextContent("Mona، Sam");
    expect(document.querySelector('[data-uid="g2-5"] .bub__seen')).toHaveTextContent("شافها: Mona");
    expect(document.querySelector('[data-uid="g2-5"] .bub__seen')).not.toHaveTextContent("Sam");
    expect(document.querySelector('[data-uid="g2-6"] .bub__seen')).toBeNull();
  });

  it("is not drawn under what somebody else wrote", async () => {
    await openGroup([entry(7, { uid: "g2-7", kind: "out", mine: false, sender: "Mona", sender_id: 8, seen_by: ["Sam"] })]);
    expect(lines()).toHaveLength(0);
  });

  it("is drawn in a group that reaches a client as well", async () => {
    await openGroup([mine(5, ["Mona"], { receipt: "delivered" })], "ar", { reaches_client: true });
    expect(lines()[0]).toHaveTextContent("شافها: Mona");
  });

  it("is not drawn in a chat with one colleague, where the blue ticks are all there is to say", async () => {
    render(
      "/chats/u5",
      { thread: { client: row("u5", { staff: true, room: 9, channel: "", window_open: false }), messages: [mine(5, ["Mona"], { uid: "g9-5" })] } },
    );
    await screen.findByRole("textbox", { name: "الرسالة" });
    expect(document.querySelector('[data-uid="g9-5"]')).not.toBeNull();
    expect(lines()).toHaveLength(0);
  });

  it("is not drawn in a client's conversation", async () => {
    render("/chats/CL-0001", {
      thread: { client: row("CL-0001"), messages: [entry(5, { uid: "out-5", kind: "out", mine: true, sender: "Nour", sender_id: 7, seen_by: ["Mona"] })] },
    });
    await screen.findByRole("textbox", { name: "الرسالة" });
    expect(lines()).toHaveLength(0);
  });

  it("is not drawn under a message that did not go, and the ticks keep the names to themselves while it is drawn", async () => {
    await openGroup([mine(5, ["Mona"], { status: "failed", error: "WhatsApp said no" }), mine(6, ["Sam"], { status: "sent" })]);
    expect(document.querySelector('[data-uid="g2-5"] .bub__seen')).toBeNull();
    expect(document.querySelector('[data-uid="g2-6"] .bub__seen')).toHaveTextContent("Sam");
    // The names are under the message once, and not again in the title of the ticks.
    expect(document.querySelector('[data-uid="g2-6"] .tick')).not.toHaveAttribute("title", expect.stringContaining("Sam"));
  });

  it("is not drawn under a message that was taken back", async () => {
    await openGroup([mine(5, ["Mona"], { unsent: true, body: "" })]);
    expect(lines()).toHaveLength(0);
  });
});
