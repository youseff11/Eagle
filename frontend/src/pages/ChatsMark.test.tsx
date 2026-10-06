import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Reaction, ThreadEntry } from "../api/types";
import { forgetDrafts } from "../components/chat/Composer";
import { entry, file, renderChats as render, row, visible } from "../test/chat";
import { jsonResponse } from "../test/helpers";

beforeEach(() => {
  visible("visible");
  forgetDrafts();
});
afterEach(() => {
  vi.unstubAllGlobals();
  visible("visible");
});

const REACT = "/api/v1/chats/react/";
const FORWARD = "/api/v1/chats/forward/";

type Call = { url: string; init?: RequestInit };
const posts = (calls: Call[], path: string) => calls.filter((c) => c.init?.method === "POST" && c.url === path);
const body = (call: Call) => JSON.parse(String(call.init?.body));

/** Two messages of a work group, as the server writes them. */
const first = entry(5, { uid: "g1-5", body: "first words", sender: "Sam", sender_id: 9 });
const second = entry(6, { uid: "g1-6", body: "second words", sender: "Sam", sender_id: 9 });
const group = () => ({ client: row("g1", { group: true, team: true, label: "Work" }), messages: [first, second] });

const mine = (kind = "like", count = 1): Reaction => ({ kind, count, mine: true, who: ["Nour"] });
const answer = (uid: string, reactions: Reaction[]) => jsonResponse({ ok: true, uid, reactions });

async function open(extra: Parameters<typeof render>[2] = {}, setup: Parameters<typeof render>[1] = {}, path = "/chats/g1") {
  const view = render(path, { thread: group(), types: ["clients", "staff", "groups"], ...setup }, extra);
  await screen.findByText("first words");
  return view;
}

const reactButtons = () => screen.getAllByRole("button", { name: "رياكت" });
const bar = () => screen.getByRole("group", { name: "رياكت" });
const pill = (uid: string) => document.querySelector(`[data-uid="${uid}"] .bub__reacts`) as HTMLElement | null;
const bubble = (uid: string) => document.querySelector(`[data-uid="${uid}"]`) as HTMLElement;

describe("reacting", () => {
  it("opens one bar of six beside the message, posts the choice and draws what the server answers", async () => {
    const { calls } = await open({ [REACT]: () => answer("g1-5", [mine("love")]) });
    expect(screen.queryByRole("group", { name: "رياكت" })).not.toBeInTheDocument();

    await userEvent.click(reactButtons()[0]!);
    expect(within(bar()).getAllByRole("button").map((b) => b.getAttribute("aria-label"))).toEqual([
      "لايك", "حب", "ضحك", "واو", "زعلان", "شكرًا",
    ]);
    await userEvent.click(within(bar()).getByRole("button", { name: "حب" }));

    await waitFor(() => expect(pill("g1-5")).not.toBeNull());
    expect(pill("g1-5")).toHaveClass("is-mine");
    expect(pill("g1-5")!.querySelector("use")).toHaveAttribute("href", "#r-love");
    expect(pill("g1-5")).toHaveAttribute("title", "Nour");
    expect(screen.queryByRole("group", { name: "رياكت" })).not.toBeInTheDocument();
    expect(posts(calls, REACT)).toHaveLength(1);
    expect(body(posts(calls, REACT)[0]!)).toEqual({ source: "g1", uid: "g1-5", kind: "love" });
    // The other message was not touched, and nothing was asked again for it.
    expect(pill("g1-6")).toBeNull();
  });

  it("carries the CSRF token", async () => {
    document.cookie = "csrftoken=tok456";
    const { calls } = await open({ [REACT]: () => answer("g1-5", [mine()]) });
    await userEvent.click(reactButtons()[0]!);
    await userEvent.click(within(bar()).getByRole("button", { name: "لايك" }));
    await waitFor(() => expect(posts(calls, REACT)).toHaveLength(1));
    expect(new Headers(posts(calls, REACT)[0]!.init?.headers).get("X-CSRFToken")).toBe("tok456");
    document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("lights the reaction already given, and the same one again is what takes it back", async () => {
    const withMine = entry(5, { uid: "g1-5", body: "first words", reactions: [mine("wow")] });
    const { calls } = await open(
      { [REACT]: () => answer("g1-5", []) },
      { thread: { client: row("g1", { group: true, team: true }), messages: [withMine, second] } },
    );
    expect(pill("g1-5")).not.toBeNull();
    await userEvent.click(pill("g1-5")!);
    const lit = within(bar()).getByRole("button", { name: "واو" });
    expect(lit).toHaveAttribute("aria-pressed", "true");
    expect(within(bar()).getByRole("button", { name: "لايك" })).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(lit);
    await waitFor(() => expect(pill("g1-5")).toBeNull());
    expect(body(posts(calls, REACT)[0]!).kind).toBe("wow");
    expect(bubble("g1-5")).not.toHaveClass("has-reacts");
  });

  it("shows how many reacted, and who, on the pill", async () => {
    const crowd = entry(5, {
      uid: "g1-5", body: "first words",
      reactions: [
        { kind: "like", count: 2, mine: false, who: ["Sam", "Lee"] },
        { kind: "love", count: 1, mine: true, who: ["Nour"] },
      ],
    });
    await open({}, { thread: { client: row("g1", { group: true, team: true }), messages: [crowd, second] } });
    expect(pill("g1-5")).toHaveTextContent("3");
    expect(pill("g1-5")).toHaveAttribute("title", "Sam, Lee · Nour");
    expect(screen.getByRole("button", { name: /التفاعلات: Sam, Lee · Nour/ })).toBeInTheDocument();
  });

  it("closes on Escape (the focus goes back to the button), on a tap elsewhere, on a second tap on the button and on a scroll", async () => {
    await open();
    const trigger = reactButtons()[0]!;

    await userEvent.click(trigger);
    expect(bar()).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("group", { name: "رياكت" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();

    await userEvent.click(trigger);
    await userEvent.click(screen.getByText("second words"));
    expect(screen.queryByRole("group", { name: "رياكت" })).not.toBeInTheDocument();

    await userEvent.click(trigger);
    await userEvent.click(trigger);
    expect(screen.queryByRole("group", { name: "رياكت" })).not.toBeInTheDocument();

    await userEvent.click(trigger);
    expect(bar()).toBeInTheDocument();
    act(() => {
      window.dispatchEvent(new Event("scroll"));
    });
    expect(screen.queryByRole("group", { name: "رياكت" })).not.toBeInTheDocument();
  });

  it("moves between the six with the arrow keys", async () => {
    await open();
    await userEvent.click(reactButtons()[0]!);
    expect(within(bar()).getByRole("button", { name: "لايك" })).toHaveFocus();
    await userEvent.keyboard("{ArrowRight}");
    expect(within(bar()).getByRole("button", { name: "حب" })).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}{ArrowLeft}");
    expect(within(bar()).getByRole("button", { name: "شكرًا" })).toHaveFocus();
  });

  it("opens for the message that asked, not for another", async () => {
    const { calls } = await open({ [REACT]: () => answer("g1-6", [mine("sad")]) });
    await userEvent.click(reactButtons()[1]!);
    await userEvent.click(within(bar()).getByRole("button", { name: "زعلان" }));
    await waitFor(() => expect(pill("g1-6")).not.toBeNull());
    expect(body(posts(calls, REACT)[0]!).uid).toBe("g1-6");
    expect(pill("g1-5")).toBeNull();
  });

  it("says so when the reaction was not saved, and leaves the message as it was", async () => {
    await open({ [REACT]: () => jsonResponse({ ok: false, error: "not_found" }, 404) });
    await userEvent.click(reactButtons()[0]!);
    await userEvent.click(within(bar()).getByRole("button", { name: "لايك" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("التفاعل ماتسجلش");
    expect(pill("g1-5")).toBeNull();
    // The next try clears it.
    await userEvent.click(reactButtons()[0]!);
    expect(screen.queryByText("التفاعل ماتسجلش. جرّب تاني.")).not.toBeInTheDocument();
  });

  it("sends one at a time: a second choice while the first is on its way is not sent", async () => {
    let release: (value: Response) => void = () => undefined;
    const { calls } = await open({ [REACT]: () => new Promise<Response>((resolve) => (release = resolve)) });
    await userEvent.click(reactButtons()[0]!);
    await userEvent.click(within(bar()).getByRole("button", { name: "لايك" }));
    await userEvent.click(reactButtons()[1]!);
    await userEvent.click(within(bar()).getByRole("button", { name: "حب" }));
    expect(posts(calls, REACT)).toHaveLength(1);
    release(answer("g1-5", [mine()]));
    await waitFor(() => expect(pill("g1-5")).not.toBeNull());
    expect(pill("g1-6")).toBeNull();
  });

  it("is for whoever is in a work group, a colleague's chat and - for the operation and the admin - a client's thread", async () => {
    // A client's thread, as the operation.
    const client = render("/chats/CL-0001", { thread: { client: row("CL-0001"), messages: [entry(1)] } });
    await screen.findByText("message 1");
    expect(reactButtons()).toHaveLength(1);
    client.unmount();
  });

  it("is not offered to a Sales person in a client's thread, where it would be refused, but is in a work group", async () => {
    const client = render("/chats/CL-0001", {
      role: { role: "sales" }, types: ["clients", "staff", "groups"], thread: { client: row("CL-0001"), messages: [entry(1)] },
    });
    await screen.findByText("message 1");
    expect(screen.queryByRole("button", { name: "رياكت" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "تحويل" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "تحويل رسايل" })).not.toBeInTheDocument();
    // Replying is another matter: it is still there.
    expect(screen.getByRole("button", { name: "رد" })).toBeInTheDocument();
    client.unmount();

    await open({}, { role: { role: "sales" } });
    expect(reactButtons()).toHaveLength(2);
  });

  it("is for a translator in a colleague's chat", async () => {
    render("/chats/u5", {
      role: { role: "translator" }, types: ["groups", "staff"],
      thread: { client: row("u5", { staff: true, label: "Sam" }), messages: [entry(1, { uid: "g2-1", body: "hello from Sam" })] },
    });
    await screen.findByText("hello from Sam");
    expect(reactButtons()).toHaveLength(1);
    expect(screen.getByRole("button", { name: "تحويل رسايل" })).toBeInTheDocument();
  });

  it("closes when the message it is for goes from the thread", async () => {
    let messages: ThreadEntry[] = [first, second];
    const { client } = await open({
      "/api/v1/groups/": () => jsonResponse({ ok: true, client: row("g1", { group: true, team: true }), messages }),
    });
    await userEvent.click(reactButtons()[0]!);
    expect(bar()).toBeInTheDocument();
    messages = [second];
    await act(async () => {
      await client.invalidateQueries();
    });
    await waitFor(() => expect(screen.queryByText("first words")).not.toBeInTheDocument());
    expect(screen.queryByRole("group", { name: "رياكت" })).not.toBeInTheDocument();
  });
});

describe("picking messages", () => {
  const toggle = () => screen.getByRole("button", { name: "تحويل رسايل" });
  const count = () => within(screen.getByRole("toolbar", { name: "تحويل رسايل" })).getByText(/^\d+$/);
  const forwardButton = () => within(screen.getByRole("toolbar", { name: "تحويل رسايل" })).getByRole("button", { name: "تحويل" });
  const marks = () => screen.queryAllByRole("button", { name: "حدد الرسالة" });

  it("turns the bubbles into a list to tap, with a bar that says how many are picked", async () => {
    await open();
    expect(screen.queryByRole("toolbar")).not.toBeInTheDocument();
    expect(marks()).toHaveLength(0);

    await userEvent.click(toggle());
    expect(toggle()).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("toolbar", { name: "تحويل رسايل" })).toBeInTheDocument();
    expect(count()).toHaveTextContent("0");
    expect(forwardButton()).toBeDisabled();
    expect(marks()).toHaveLength(2);
    expect(document.querySelector(".cchat__stream")).toHaveClass("is-selecting");

    await userEvent.click(screen.getByText("second words"));
    expect(count()).toHaveTextContent("1");
    expect(bubble("g1-6")).toHaveClass("is-selected");
    expect(bubble("g1-5")).not.toHaveClass("is-selected");
    expect(forwardButton()).toBeEnabled();

    // A tap on the mark, as the keyboard does, and a second tap on the bubble: both drop it.
    await userEvent.click(within(bubble("g1-6")).getByRole("button", { name: "حدد الرسالة" }));
    expect(count()).toHaveTextContent("0");
    await userEvent.click(screen.getByText("first words"));
    await userEvent.click(screen.getByText("first words"));
    expect(count()).toHaveTextContent("0");
  });

  it("starts from the arrow beside a bubble, with that message picked", async () => {
    await open();
    await userEvent.click(screen.getAllByRole("button", { name: "تحويل" })[1]!);
    expect(count()).toHaveTextContent("1");
    expect(bubble("g1-6")).toHaveClass("is-selected");
    expect(bubble("g1-5")).not.toHaveClass("is-selected");
  });

  it("takes the box to write in away while picking, and gives it back with what was typed", async () => {
    await open();
    await userEvent.type(screen.getByRole("textbox", { name: "الرسالة" }), "half a thought");
    await userEvent.click(toggle());
    expect(screen.queryByRole("textbox", { name: "الرسالة" })).not.toBeInTheDocument();
    await userEvent.click(toggle());
    expect(screen.getByRole("textbox", { name: "الرسالة" })).toHaveValue("half a thought");
    expect(screen.queryByRole("toolbar")).not.toBeInTheDocument();
    expect(marks()).toHaveLength(0);
  });

  it("leaves with Cancel and with Escape, and forgets what was picked", async () => {
    await open();
    await userEvent.click(toggle());
    await userEvent.click(screen.getByText("first words"));
    await userEvent.click(screen.getByRole("button", { name: "إلغاء" }));
    expect(screen.queryByRole("toolbar")).not.toBeInTheDocument();
    expect(bubble("g1-5")).not.toHaveClass("is-selected");

    await userEvent.click(toggle());
    expect(count()).toHaveTextContent("0");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("toolbar")).not.toBeInTheDocument();
  });

  it("does not pick a message when a link inside it is the thing that was tapped", async () => {
    const withFile = entry(5, { uid: "g1-5", body: "first words", files: [file({ name: "plan.pdf", url: "/files/g/plan.pdf" })] });
    await open({}, { thread: { client: row("g1", { group: true, team: true }), messages: [withFile, second] } });
    await userEvent.click(toggle());
    const link = screen.getByRole("link", { name: "plan.pdf" });
    link.addEventListener("click", (event) => event.preventDefault());
    await userEvent.click(link);
    expect(count()).toHaveTextContent("0");
  });

  it("drops a picked message that is no longer in the thread", async () => {
    let messages: ThreadEntry[] = [first, second];
    const { client } = await open({
      "/api/v1/groups/": () => jsonResponse({ ok: true, client: row("g1", { group: true, team: true }), messages }),
    });
    await userEvent.click(toggle());
    await userEvent.click(screen.getByText("first words"));
    await userEvent.click(screen.getByText("second words"));
    expect(count()).toHaveTextContent("2");
    messages = [second];
    await act(async () => {
      await client.invalidateQueries();
    });
    await waitFor(() => expect(count()).toHaveTextContent("1"));
    expect(bubble("g1-6")).toHaveClass("is-selected");
  });

  it("has no use for the button in a conversation with nothing in it", async () => {
    render("/chats/g1", { thread: { client: row("g1", { group: true, team: true }), messages: [] } });
    await screen.findByText("مفيش رسايل لسه.");
    expect(screen.queryByRole("button", { name: "تحويل رسايل" })).not.toBeInTheDocument();
  });

  it("does not react while picking: the pill is inert", async () => {
    const withPill = entry(5, { uid: "g1-5", body: "first words", reactions: [mine()] });
    await open({}, { thread: { client: row("g1", { group: true, team: true }), messages: [withPill, second] } });
    await userEvent.click(toggle());
    expect(pill("g1-5")).toBeDisabled();
    await userEvent.click(pill("g1-5")!);
    expect(screen.queryByRole("group", { name: "رياكت" })).not.toBeInTheDocument();
  });
});

describe("forwarding", () => {
  const staffRow = row("u5", { staff: true, label: "Sam", initials: "SM" });
  const lists = {
    staff: [staffRow],
    groups: [row("g1", { group: true, team: true, label: "Work" }), row("g2", { group: true, reaches_client: true, label: "With Acme" })],
    clients: [row("CL-0002"), row("CL-0003")],
  };
  const arrived = { "/api/v1/staff/": () => jsonResponse({ ok: true, client: staffRow, messages: [entry(1, { uid: "g9-1", body: "arrived there", forwarded: true })] }) };

  const dialog = () => screen.getByRole("dialog");
  const choose = async (name: string) => userEvent.click(within(dialog()).getByRole("radio", { name: new RegExp(name) }));
  const send = () => within(dialog()).getByRole("button", { name: "ابعت" });

  async function pickBoth(extra: Parameters<typeof render>[2] = {}, setup: Parameters<typeof render>[1] = {}) {
    const view = await open({ ...arrived, ...extra }, { lists, ...setup });
    await userEvent.click(screen.getByRole("button", { name: "تحويل رسايل" }));
    await userEvent.click(screen.getByText("second words"));
    await userEvent.click(screen.getByText("first words"));
    const bar = screen.getByRole("toolbar", { name: "تحويل رسايل" });
    await userEvent.click(within(bar).getByRole("button", { name: "تحويل" }));
    await screen.findByRole("dialog");
    return view;
  }

  it("lists colleagues, groups and clients from the lists the page has - except the conversation it comes from", async () => {
    await pickBoth();
    await waitFor(() => expect(within(dialog()).getAllByRole("radio")).toHaveLength(4));
    expect(within(dialog()).getByText("2")).toBeInTheDocument();
    const names = within(dialog()).getAllByRole("radio").map((r) => r.closest("label")!.textContent);
    expect(names.join("|")).toContain("Sam");
    expect(names.join("|")).toContain("With Acme");
    expect(names.join("|")).toContain("CL-0002");
    // The group it comes from (g1) is not a place to forward to.
    expect(names.join("|")).not.toContain("Work");
    expect(within(dialog()).getByText("جروب مع العميل")).toBeInTheDocument();
    expect(within(dialog()).getByText("زميل")).toBeInTheDocument();
    expect(within(dialog()).getAllByText("عميل · واتساب")).toHaveLength(2);
    expect(send()).toBeDisabled();
  });

  it("searches by name or by code", async () => {
    await pickBoth();
    await waitFor(() => expect(within(dialog()).getAllByRole("radio")).toHaveLength(4));
    await userEvent.type(within(dialog()).getByRole("searchbox"), "acme");
    expect(within(dialog()).getAllByRole("radio")).toHaveLength(1);
    await userEvent.clear(within(dialog()).getByRole("searchbox"));
    await userEvent.type(within(dialog()).getByRole("searchbox"), "cl-0003");
    expect(within(dialog()).getAllByRole("radio")).toHaveLength(1);
    await userEvent.clear(within(dialog()).getByRole("searchbox"));
    await userEvent.type(within(dialog()).getByRole("searchbox"), "zzz");
    expect(within(dialog()).getByText("مفيش نتايج.")).toBeInTheDocument();
  });

  it("sends the picked messages in the order they were picked, with the note, and opens where they went", async () => {
    const { calls } = await pickBoth({ [FORWARD]: () => jsonResponse({ ok: true, delivered: true, message: "", code: "u5" }) });
    await waitFor(() => expect(within(dialog()).getAllByRole("radio")).toHaveLength(4));
    await choose("Sam");
    await userEvent.type(within(dialog()).getByRole("textbox", { name: "كلمة مع التحويل" }), "  have a look ");
    await userEvent.click(send());

    await waitFor(() => expect(posts(calls, FORWARD)).toHaveLength(1));
    expect(body(posts(calls, FORWARD)[0]!)).toEqual({ source: "g1", target: "u5", uids: ["g1-6", "g1-5"], note: "have a look" });
    // Where they went is on screen, and the picking is over.
    expect(await screen.findByText("arrived there")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("toolbar")).not.toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/v1/staff/5/messages/")).toBe(true);
  });

  it("calls the note a caption only where it is one: in a client's own conversation, with what the client will see", async () => {
    const { calls } = await pickBoth({ [FORWARD]: () => jsonResponse({ ok: true, delivered: true, message: "", code: "CL-0002" }) });
    await waitFor(() => expect(within(dialog()).getAllByRole("radio")).toHaveLength(4));
    const caption = () => within(dialog()).queryByRole("textbox", { name: "كابشن" });
    const note = () => within(dialog()).queryByRole("textbox", { name: "كلمة مع التحويل" });
    const hint = () => within(dialog()).queryByText(/الكابشن بيظهر للعميل تحت الملف/);
    // Nothing chosen yet, a colleague, and a group (even one that reaches the client: it is a line in the chat there).
    expect([caption(), hint()]).toEqual([null, null]);
    expect(note()).not.toBeNull();
    await choose("Sam");
    expect([caption(), hint()]).toEqual([null, null]);
    await choose("With Acme");
    expect([caption(), hint()]).toEqual([null, null]);
    expect(note()).not.toBeNull();

    await choose("CL-0002");
    expect(note()).toBeNull();
    expect(hint()).not.toBeNull();
    await userEvent.type(caption()!, "  Your translation ");
    await userEvent.click(send());
    await waitFor(() => expect(posts(calls, FORWARD)).toHaveLength(1));
    // It travels in the same field the server already reads, trimmed.
    expect(body(posts(calls, FORWARD)[0]!)).toEqual({ source: "g1", target: "CL-0002", uids: ["g1-6", "g1-5"], note: "Your translation" });
  });

  it("carries the CSRF token", async () => {
    document.cookie = "csrftoken=tok789";
    const { calls } = await pickBoth({ [FORWARD]: () => jsonResponse({ ok: true, delivered: true, message: "", code: "u5" }) });
    await waitFor(() => expect(within(dialog()).getAllByRole("radio")).toHaveLength(4));
    await choose("Sam");
    await userEvent.click(send());
    await waitFor(() => expect(posts(calls, FORWARD)).toHaveLength(1));
    expect(new Headers(posts(calls, FORWARD)[0]!.init?.headers).get("X-CSRFToken")).toBe("tok789");
    document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("says why, in the server's words, when it will not forward - and keeps the picking, so it can be changed", async () => {
    const { calls } = await pickBoth({
      [FORWARD]: () => jsonResponse({ ok: false, error: "refused", message: "مينفعش تحوّل رسايل أو ملفات عميل لعميل تاني." }, 400),
    });
    await waitFor(() => expect(within(dialog()).getAllByRole("radio")).toHaveLength(4));
    await choose("CL-0002");
    await userEvent.click(send());
    expect(await within(dialog()).findByText("مينفعش تحوّل رسايل أو ملفات عميل لعميل تاني.")).toBeInTheDocument();
    expect(send()).toBeEnabled();
    expect(posts(calls, FORWARD)).toHaveLength(1);
    // Still picking, nothing navigated.
    await userEvent.click(within(dialog()).getByRole("button", { name: "إلغاء" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("toolbar", { name: "تحويل رسايل" })).toBeInTheDocument();
    expect(within(screen.getByRole("toolbar")).getByText(/^\d+$/)).toHaveTextContent("2");
  });

  it("does not claim it failed when nothing came back: the messages may be there already", async () => {
    await pickBoth({ [FORWARD]: () => Promise.reject(new TypeError("network down")) });
    await waitFor(() => expect(within(dialog()).getAllByRole("radio")).toHaveLength(4));
    await choose("Sam");
    await userEvent.click(send());
    expect(await within(dialog()).findByText(/مش متأكدين إن التحويل تم/)).toBeInTheDocument();
  });

  it("is told apart from a refusal: a server that failed is not sure either", async () => {
    await pickBoth({ [FORWARD]: () => jsonResponse({ ok: false, error: "server" }, 500) });
    await waitFor(() => expect(within(dialog()).getAllByRole("radio")).toHaveLength(4));
    await choose("Sam");
    await userEvent.click(send());
    expect(await within(dialog()).findByText(/مش متأكدين إن التحويل تم/)).toBeInTheDocument();
  });

  it("is not a refusal when the messages got there and went no further: it says so and offers to open them, never to send again", async () => {
    const { calls } = await pickBoth({
      [FORWARD]: () => jsonResponse({ ok: true, delivered: false, message: "اتحوّلت للجروب بس مروحتش للعميل: واتساب رجّع خطأ", code: "u5" }),
    });
    await waitFor(() => expect(within(dialog()).getAllByRole("radio")).toHaveLength(4));
    await choose("Sam");
    await userEvent.click(send());
    expect(await within(dialog()).findByText(/اتحوّلت للجروب بس مروحتش للعميل/)).toBeInTheDocument();
    expect(within(dialog()).queryByRole("button", { name: "ابعت" })).not.toBeInTheDocument();
    expect(posts(calls, FORWARD)).toHaveLength(1);

    await userEvent.click(within(dialog()).getByRole("button", { name: "افتح المحادثة" }));
    expect(await screen.findByText("arrived there")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("toolbar")).not.toBeInTheDocument();
  });

  it("can be closed after a delivery that went no further, and the picking ends with it", async () => {
    await pickBoth({ [FORWARD]: () => jsonResponse({ ok: true, delivered: false, message: "x", code: "u5" }) });
    await waitFor(() => expect(within(dialog()).getAllByRole("radio")).toHaveLength(4));
    await choose("Sam");
    await userEvent.click(send());
    await within(dialog()).findByText("x");
    await userEvent.click(within(dialog()).getAllByRole("button", { name: "إغلاق" })[1]!);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("toolbar")).not.toBeInTheDocument();
    expect(screen.getByText("first words")).toBeInTheDocument();
  });

  it("sends once however often the button is pressed, and does not close while it is on its way", async () => {
    let release: (value: Response) => void = () => undefined;
    const { calls } = await pickBoth({ [FORWARD]: () => new Promise<Response>((resolve) => (release = resolve)) });
    await waitFor(() => expect(within(dialog()).getAllByRole("radio")).toHaveLength(4));
    await choose("Sam");
    await userEvent.click(send());
    expect(within(dialog()).getByRole("button", { name: "بيتحوّل..." })).toBeDisabled();
    await userEvent.click(within(dialog()).getByRole("button", { name: "بيتحوّل..." }));
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(posts(calls, FORWARD)).toHaveLength(1);
    release(jsonResponse({ ok: true, delivered: true, message: "", code: "u5" }));
    expect(await screen.findByText("arrived there")).toBeInTheDocument();
  });

  it("closes with Escape and keeps the picking; a second Escape ends it", async () => {
    await pickBoth();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("toolbar", { name: "تحويل رسايل" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("toolbar")).not.toBeInTheDocument();
  });

  it("closes on a tap on the backdrop but not on a tap inside", async () => {
    await pickBoth();
    await userEvent.click(within(dialog()).getByText("جروب مع العميل").closest("label")!);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.mouseDown(document.querySelector(".modal-backdrop")!);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("will not send before somewhere is chosen", async () => {
    const { calls } = await pickBoth();
    await waitFor(() => expect(within(dialog()).getAllByRole("radio")).toHaveLength(4));
    expect(send()).toBeDisabled();
    await userEvent.click(send());
    expect(posts(calls, FORWARD)).toHaveLength(0);
  });

  it("does not offer clients to a Sales person, who may not forward to them, and does not ask for their list", async () => {
    const { calls } = await open({ ...arrived }, { lists, role: { role: "sales" } });
    await userEvent.click(screen.getByRole("button", { name: "تحويل رسايل" }));
    await userEvent.click(screen.getByText("first words"));
    await userEvent.click(within(screen.getByRole("toolbar")).getByRole("button", { name: "تحويل" }));
    await screen.findByRole("dialog");
    await waitFor(() => expect(within(dialog()).getAllByRole("radio")).toHaveLength(2));
    expect(within(dialog()).queryByText("عميل · واتساب")).not.toBeInTheDocument();
    // The page itself asks for the groups list (the tab it is on); nobody asked for the clients one.
    expect(calls.some((c) => c.url.startsWith("/api/v1/chats/?type=clients"))).toBe(false);
  });

  it("does not offer clients to a translator, who has no client list at all", async () => {
    const { calls } = await open(
      { ...arrived },
      { lists: { staff: [staffRow], groups: lists.groups }, role: { role: "translator" }, types: ["groups", "staff"] },
    );
    await userEvent.click(screen.getByRole("button", { name: "تحويل رسايل" }));
    await userEvent.click(screen.getByText("first words"));
    await userEvent.click(within(screen.getByRole("toolbar")).getByRole("button", { name: "تحويل" }));
    await screen.findByRole("dialog");
    await waitFor(() => expect(within(dialog()).getAllByRole("radio")).toHaveLength(2));
    expect(calls.some((c) => c.url.includes("type=clients"))).toBe(false);
  });

  it("offers clients to the admin and to the operation", async () => {
    for (const role of [{ role: "operation" as const }, { role: "admin" as const, is_admin: true }]) {
      const view = await pickBoth({}, { role });
      await waitFor(() => expect(within(dialog()).getAllByRole("radio")).toHaveLength(4));
      expect(within(dialog()).getAllByText("عميل · واتساب")).toHaveLength(2);
      view.unmount();
    }
  });

  it("is also what a client's thread forwards from, to a colleague of the operation", async () => {
    const { calls } = render(
      "/chats/CL-0001",
      {
        lists, thread: { client: row("CL-0001"), messages: [entry(1, { uid: "in-1", body: "the client wrote" })] },
      },
      { ...arrived, [FORWARD]: () => jsonResponse({ ok: true, delivered: true, message: "", code: "u5" }) },
    );
    await screen.findByText("the client wrote");
    await userEvent.click(screen.getByRole("button", { name: "تحويل" }));
    await userEvent.click(within(screen.getByRole("toolbar")).getByRole("button", { name: "تحويل" }));
    await screen.findByRole("dialog");
    await waitFor(() => expect(within(dialog()).getAllByRole("radio")).toHaveLength(5));
    // The conversation it comes from is not offered; CL-0001 is not in these lists anyway, the others are.
    await choose("Sam");
    await userEvent.click(send());
    await waitFor(() => expect(posts(calls, FORWARD)).toHaveLength(1));
    expect(body(posts(calls, FORWARD)[0]!)).toEqual({ source: "CL-0001", target: "u5", uids: ["in-1"], note: "" });
  });

  it("warns when what is forwarded from a work group or a colleague is going to a client, and only then", async () => {
    await pickBoth();
    await waitFor(() => expect(within(dialog()).getAllByRole("radio")).toHaveLength(4));
    expect(within(dialog()).queryByRole("note")).not.toBeInTheDocument();
    await choose("Sam");
    expect(within(dialog()).queryByRole("note")).not.toBeInTheDocument();
    await choose("CL-0002");
    expect(within(dialog()).getByRole("note")).toHaveTextContent("ده هيتبعت للعميل على واتساب");
    // A group that reaches a client is a client's too.
    await choose("With Acme");
    expect(within(dialog()).getByRole("note")).toBeInTheDocument();
    await choose("Sam");
    expect(within(dialog()).queryByRole("note")).not.toBeInTheDocument();
  });

  it("does not warn when the messages come from the client's own conversation", async () => {
    render(
      "/chats/CL-0001",
      { lists, thread: { client: row("CL-0001"), messages: [entry(1, { uid: "in-1", body: "the client wrote" })] } },
      { ...arrived },
    );
    await screen.findByText("the client wrote");
    await userEvent.click(screen.getByRole("button", { name: "تحويل" }));
    await userEvent.click(within(screen.getByRole("toolbar")).getByRole("button", { name: "تحويل" }));
    await screen.findByRole("dialog");
    await waitFor(() => expect(within(dialog()).getAllByRole("radio")).toHaveLength(5));
    await choose("With Acme");
    expect(within(dialog()).queryByRole("note")).not.toBeInTheDocument();
  });

  it("draws nothing the server wrote as markup", async () => {
    await pickBoth({
      [FORWARD]: () => jsonResponse({ ok: false, error: "refused", message: "<img src=x onerror=alert(1)>" }, 400),
    });
    await waitFor(() => expect(within(dialog()).getAllByRole("radio")).toHaveLength(4));
    await choose("Sam");
    await userEvent.click(send());
    expect(await within(dialog()).findByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(dialog().querySelector("img")).toBeNull();
  });
});
