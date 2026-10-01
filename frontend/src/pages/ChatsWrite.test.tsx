import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { qk } from "../api/keys";
import { sendPath } from "../api/queries";
import type { ThreadEntry } from "../api/types";
import { forgetDrafts } from "../components/chat/Composer";
import { entry, renderChats as render, row, visible } from "../test/chat";
import { jsonResponse, me } from "../test/helpers";

beforeEach(() => {
  visible("visible");
  forgetDrafts();
});
afterEach(() => {
  vi.unstubAllGlobals();
  visible("visible");
});

const SEND = "/api/v1/clients/CL-0001/send/";

type Call = { url: string; init?: RequestInit };
const posts = (calls: Call[], suffix = "/send/") => calls.filter((c) => c.init?.method === "POST" && c.url.endsWith(suffix));
const form = (call: Call) => Object.fromEntries(new URLSearchParams(String(call.init?.body)));

/** A message of ours, as the server writes it into a client's thread. */
const ours = (id: number, body: string, extra: Partial<ThreadEntry> = {}) =>
  entry(id, { uid: `out-${id}`, kind: "out", body, sender: "Nour", sender_id: 7, status: "sent", ...extra });

const answer = (messages: ThreadEntry[], delivered = true, error = "", code = "CL-0001") =>
  jsonResponse({ ok: true, delivered, error, messages, client: row(code) });

const box = () => screen.getByRole("textbox", { name: "الرسالة" });
const sendButton = () => screen.getByRole("button", { name: "إرسال" });

async function open(extra: Parameters<typeof render>[2] = {}, setup: Parameters<typeof render>[1] = {}, options: Parameters<typeof render>[3] = {}) {
  const view = render(
    "/chats/CL-0001",
    { thread: { client: row("CL-0001"), messages: [entry(1)] }, ...setup },
    extra,
    options,
  );
  // The box is there once the thread has loaded.
  await screen.findByRole("textbox", { name: "الرسالة" });
  return view;
}

describe("where a message is written", () => {
  it("is the client's door, a group's room, or the colleague's - and nothing else", () => {
    expect(sendPath("CL-0001")).toBe("/api/v1/clients/CL-0001/send/");
    expect(sendPath("g12")).toBe("/api/v1/groups/12/send/");
    expect(sendPath("u5")).toBe("/api/v1/staff/5/send/");
    for (const bad of ["../etc", "CL 0001", "a/b", "", "x".repeat(41), "g12/../x"]) expect(sendPath(bad), bad).toBeNull();
  });
});

describe("writing", () => {
  it("sends the words, and shows the thread the server answers with", async () => {
    const { calls } = await open({ [SEND]: () => answer([entry(1), ours(9, "We can do it")]) });
    await userEvent.type(box(), "  We can do it  ");
    await userEvent.click(sendButton());

    expect(await screen.findByText("We can do it")).toBeInTheDocument();
    expect(posts(calls)).toHaveLength(1);
    expect(form(posts(calls)[0]!)).toEqual({ body: "We can do it" });
    // The server's bubble replaced the one that was on its way: one, not two, and the box is empty again.
    expect(document.querySelectorAll(".bub--pending")).toHaveLength(0);
    expect(screen.getAllByText("We can do it")).toHaveLength(1);
    expect(document.querySelector('[data-uid="out-9"]')).toHaveClass("bub--out");
    expect(box()).toHaveValue("");
  });

  it("asks for the lists again after a send: the row says what was just written", async () => {
    const { calls } = await open({ [SEND]: () => answer([entry(1), ours(9, "fresh")]) }, { lists: { clients: [row("CL-0001")] } });
    const lists = () => calls.filter((c) => c.url.startsWith("/api/v1/chats/")).length;
    await waitFor(() => expect(lists()).toBeGreaterThan(0));
    const before = lists();
    await userEvent.type(box(), "fresh{Enter}");
    await screen.findByText("fresh");
    await waitFor(() => expect(lists()).toBeGreaterThan(before));
  });

  it("carries the CSRF token and writes nothing on a GET", async () => {
    document.cookie = "csrftoken=tok123";
    const { calls } = await open({ [SEND]: () => answer([entry(1), ours(9, "x")]) });
    await userEvent.type(box(), "x{Enter}");
    await screen.findByText("x");
    const call = posts(calls)[0]!;
    expect(new Headers(call.init?.headers).get("X-CSRFToken")).toBe("tok123");
    expect(calls.filter((c) => c.url.endsWith("/send/") && c.init?.method !== "POST")).toEqual([]);
    document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("sends on Enter, makes a new line on Shift+Enter, and does neither while an input method is composing", async () => {
    const { calls } = await open({ [SEND]: () => answer([entry(1), ours(9, "first")]) });
    await userEvent.type(box(), "first{Shift>}{Enter}{/Shift}second");
    expect(box()).toHaveValue("first\nsecond");
    expect(posts(calls)).toHaveLength(0);

    fireEvent.keyDown(box(), { key: "Enter", isComposing: true });
    expect(posts(calls)).toHaveLength(0);

    await userEvent.type(box(), "{Enter}");
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(form(posts(calls)[0]!).body).toBe("first\nsecond");
  });

  it("will not send nothing: the button is off for an empty box or one with only spaces", async () => {
    const { calls } = await open();
    expect(sendButton()).toBeDisabled();
    await userEvent.type(box(), "   ");
    expect(sendButton()).toBeDisabled();
    await userEvent.type(box(), "{Enter}");
    expect(posts(calls)).toHaveLength(0);
  });

  it("shows the message as on its way until the server answers, and sends it once however often Enter is pressed", async () => {
    let release: (value: Response) => void = () => undefined;
    const { calls } = await open({ [SEND]: () => new Promise<Response>((resolve) => (release = resolve)) });
    await userEvent.type(box(), "slow one{Enter}");

    const pending = await screen.findByText("slow one");
    expect(pending.closest(".bub")).toHaveClass("bub--pending");
    expect(screen.getByText("بيتبعت...")).toBeInTheDocument();
    // The box can be written in, but a second message waits for the first.
    await userEvent.type(box(), "another{Enter}");
    expect(posts(calls)).toHaveLength(1);
    expect(sendButton()).toBeDisabled();

    release(answer([entry(1), ours(9, "slow one")]));
    await waitFor(() => expect(document.querySelectorAll(".bub--pending")).toHaveLength(0));
    expect(screen.getAllByText("slow one")).toHaveLength(1);
    // What was typed meanwhile is still there to send.
    expect(box()).toHaveValue("another");
    await waitFor(() => expect(sendButton()).toBeEnabled());
  });

  it("draws what was written as text, never as markup", async () => {
    let release: (value: Response) => void = () => undefined;
    await open({ [SEND]: () => new Promise<Response>((resolve) => (release = resolve)) });
    await userEvent.type(box(), "<img src=x onerror=alert(1)><b>bold</b>{Enter}");
    expect(await screen.findByText("<img src=x onerror=alert(1)><b>bold</b>")).toBeInTheDocument();
    expect(document.querySelector(".cchat__stream img")).toBeNull();
    expect(document.querySelector(".cchat__stream b")).toBeNull();
    release(answer([entry(1)]));
  });

  it("writes to a group and to a colleague at their own doors", async () => {
    const group = render(
      "/chats/g12",
      { thread: { client: row("g12", { group: true, team: true, channel: "" }), messages: [entry(1, { uid: "g12-1" })] } },
      { "/api/v1/groups/12/send/": () => jsonResponse({ ok: true, delivered: true, error: "", messages: [entry(1, { uid: "g12-1" })], client: row("g12", { group: true }) }) },
    );
    await screen.findByText("message 1");
    await userEvent.type(box(), "to the group{Enter}");
    await waitFor(() => expect(posts(group.calls)).toHaveLength(1));
    expect(posts(group.calls)[0]!.url).toBe("/api/v1/groups/12/send/");
    group.unmount();

    const staff = render(
      "/chats/u5",
      { thread: { client: row("u5", { staff: true, room: 0 }), messages: [] } },
      { "/api/v1/staff/5/send/": () => jsonResponse({ ok: true, delivered: true, error: "", messages: [], client: row("u5", { staff: true, room: 9 }) }) },
    );
    await screen.findByText("مفيش رسايل لسه.");
    await userEvent.type(box(), "to a colleague{Enter}");
    await waitFor(() => expect(posts(staff.calls)).toHaveLength(1));
    expect(posts(staff.calls)[0]!.url).toBe("/api/v1/staff/5/send/");
  });
});

describe("replying", () => {
  it("quotes the message that was chosen: shown above the box, sent by its uid, gone after the send", async () => {
    const { calls } = await open(
      { [SEND]: () => answer([entry(1), ours(9, "an answer", { quote: "message 1", quote_who: "العميل" })]) },
      { thread: { client: row("CL-0001"), messages: [entry(1, { uid: "in-1", body: "Please quote this" })] } },
    );
    await screen.findByText("Please quote this");
    await userEvent.click(screen.getByRole("button", { name: "رد" }));
    const bar = document.querySelector(".cchat__replybar") as HTMLElement;
    expect(bar).toHaveTextContent("العميل");
    expect(bar).toHaveTextContent("Please quote this");
    expect(box()).toHaveFocus();

    await userEvent.type(box(), "an answer{Enter}");
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(form(posts(calls)[0]!)).toEqual({ body: "an answer", reply_uid: "in-1" });
    await waitFor(() => expect(document.querySelector(".cchat__replybar")).toBeNull());
    // The next message is not a reply unless somebody says so.
    await waitFor(() => expect(sendButton()).toBeDisabled());
  });

  it("shows the quote inside the message that is on its way", async () => {
    let release: (value: Response) => void = () => undefined;
    await open({ [SEND]: () => new Promise<Response>((resolve) => (release = resolve)) });
    await userEvent.click(screen.getByRole("button", { name: "رد" }));
    await userEvent.type(box(), "yes{Enter}");
    const pending = (await screen.findByText("yes")).closest(".bub") as HTMLElement;
    expect(pending.querySelector(".bub__quote")).toHaveTextContent("message 1");
    release(answer([entry(1)]));
  });

  it("can be dropped with the cross or with Escape, and then the message is not a reply", async () => {
    const { calls } = await open({ [SEND]: () => answer([entry(1), ours(9, "plain")]) });
    await userEvent.click(screen.getByRole("button", { name: "رد" }));
    await userEvent.click(screen.getByRole("button", { name: "إلغاء الرد" }));
    expect(document.querySelector(".cchat__replybar")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "رد" }));
    await userEvent.keyboard("{Escape}");
    expect(document.querySelector(".cchat__replybar")).toBeNull();

    await userEvent.type(box(), "plain{Enter}");
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(form(posts(calls)[0]!)).toEqual({ body: "plain" });
  });

  it("names a colleague's message by their name and a file by its name", async () => {
    const group = row("g12", { group: true, team: true, channel: "" });
    render("/chats/g12", {
      thread: {
        client: group,
        messages: [
          entry(1, { uid: "g12-1", kind: "out", sender: "Mona", body: "from Mona" }),
          entry(2, { uid: "g12-2", kind: "out", sender: "Mona", body: "", files: [{ id: 1, url: "/files/x", name: "plan.pdf", size: 1, mime: "", voice: false, audio: false, length: "", image: false }] }),
        ],
      },
    });
    await screen.findByText("from Mona");
    await userEvent.click(screen.getAllByRole("button", { name: "رد" })[1]!);
    const bar = document.querySelector(".cchat__replybar") as HTMLElement;
    expect(bar).toHaveTextContent("Mona");
    expect(bar).toHaveTextContent("plan.pdf");
  });
});

describe("when it does not go", () => {
  it("says a refused message was not sent, why, and lets the person try again or give it up", async () => {
    let answerWith: () => Response = () => jsonResponse({ ok: false, error: "forbidden" }, 403);
    const { calls } = await open({ [SEND]: () => answerWith() });
    await userEvent.type(box(), "no entry{Enter}");

    const bubble = (await screen.findByText("no entry")).closest(".bub") as HTMLElement;
    await waitFor(() => expect(bubble).toHaveClass("bub--failed"));
    expect(bubble).toHaveTextContent("مش مسموحلك ترد في المحادثة دي.");
    // A refusal means nothing was written: no looking at the thread is needed.
    expect(calls.filter((c) => c.url.endsWith("/messages/")).length).toBeLessThanOrEqual(1);

    answerWith = () => answer([entry(1), ours(9, "no entry")]);
    await userEvent.click(screen.getByRole("button", { name: "حاول تاني" }));
    await waitFor(() => expect(document.querySelectorAll(".bub--pending")).toHaveLength(0));
    expect(posts(calls)).toHaveLength(2);
    expect(screen.getAllByText("no entry")).toHaveLength(1);
  });

  it("lets the person give a refused message up", async () => {
    await open({ [SEND]: () => jsonResponse({ ok: false, error: "not_found" }, 404) });
    await userEvent.type(box(), "never mind{Enter}");
    await screen.findByRole("button", { name: "امسح" });
    await userEvent.click(screen.getByRole("button", { name: "امسح" }));
    expect(screen.queryByText("never mind")).not.toBeInTheDocument();
  });

  it("does not say 'try again' for a session that has ended: it says so", async () => {
    await open({ [SEND]: () => jsonResponse({ ok: false, error: "csrf" }, 403) });
    await userEvent.type(box(), "stale{Enter}");
    expect(await screen.findByText(/الجلسة محتاجة تتحدّث/)).toBeInTheDocument();
  });

  it("is not sure when nothing came back, looks at the thread, and finds the message there when it arrived", async () => {
    let arrived = false;
    await open({
      [SEND]: () => Promise.reject(new TypeError("Failed to fetch")),
      "/api/v1/clients/CL-0001/messages/": () =>
        jsonResponse({ ok: true, client: row("CL-0001"), messages: arrived ? [entry(1), ours(9, "did it arrive")] : [entry(1)] }),
    });
    // The server wrote it, and the answer was lost on the way.
    arrived = true;
    await userEvent.type(box(), "did it arrive{Enter}");
    await waitFor(() => expect(document.querySelector('[data-uid="out-9"]')).not.toBeNull());
    await waitFor(() => expect(document.querySelectorAll(".bub--pending")).toHaveLength(0));
    expect(screen.getAllByText("did it arrive")).toHaveLength(1);
    expect(screen.queryByText(/مش متأكدين/)).not.toBeInTheDocument();
  });

  it("stays 'not sure' when the thread does not show it, warns before sending again, and looks again before it does", async () => {
    let threadHasIt = false;
    let sendCalls = 0;
    const { calls } = await open(
      {
        [SEND]: () => {
          sendCalls += 1;
          return sendCalls === 1 ? Promise.reject(new TypeError("Failed to fetch")) : answer([entry(1), ours(9, "maybe")]);
        },
        "/api/v1/clients/CL-0001/messages/": () =>
          jsonResponse({ ok: true, client: row("CL-0001"), messages: threadHasIt ? [entry(1), ours(9, "maybe")] : [entry(1)] }),
      },
    );
    await userEvent.type(box(), "maybe{Enter}");
    expect(await screen.findByText(/مش متأكدين إن الرسالة وصلت/)).toBeInTheDocument();
    expect(posts(calls)).toHaveLength(1);

    // It turns out it did arrive (a minute later, by the doorbell): "try again" must not send it a second time.
    threadHasIt = true;
    await userEvent.click(screen.getByRole("button", { name: "حاول تاني" }));
    await waitFor(() => expect(document.querySelectorAll(".bub--pending")).toHaveLength(0));
    expect(posts(calls)).toHaveLength(1);
    expect(screen.getAllByText("maybe")).toHaveLength(1);
  });

  it("looks again with a request of its own, not one that was asked before the message was written", async () => {
    // The look that follows the lost answer never comes back; the one that "Try again" starts must not wait for it.
    let arrived = false;
    let gets = 0;
    const { calls } = await open({
      [SEND]: () => Promise.reject(new TypeError("Failed to fetch")),
      "/api/v1/clients/CL-0001/messages/": () => {
        gets += 1;
        if (gets === 2) return new Promise<Response>(() => undefined);
        return jsonResponse({ ok: true, client: row("CL-0001"), messages: arrived ? [entry(1), ours(9, "slow look")] : [entry(1)] });
      },
    });
    await userEvent.type(box(), "slow look{Enter}");
    await screen.findByText(/مش متأكدين/);
    arrived = true;
    await userEvent.click(screen.getByRole("button", { name: "حاول تاني" }));
    await waitFor(() => expect(document.querySelectorAll(".bub--pending")).toHaveLength(0));
    expect(posts(calls)).toHaveLength(1);
    expect(screen.getAllByText("slow look")).toHaveLength(1);
  });

  it("sends it again when the thread still does not show it", async () => {
    let sendCalls = 0;
    const { calls } = await open({
      [SEND]: () => {
        sendCalls += 1;
        return sendCalls === 1 ? jsonResponse({ ok: false, error: "server" }, 500) : answer([entry(1), ours(9, "lost")]);
      },
    });
    await userEvent.type(box(), "lost{Enter}");
    expect(await screen.findByText(/مش متأكدين/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "حاول تاني" }));
    await waitFor(() => expect(posts(calls)).toHaveLength(2));
    await waitFor(() => expect(document.querySelectorAll(".bub--pending")).toHaveLength(0));
    expect(screen.getAllByText("lost")).toHaveLength(1);
  });

  it("shows a delivery that failed as the server recorded it, with the reason, and empties the box", async () => {
    await open({
      [SEND]: () =>
        answer([entry(1), ours(9, "stuck", { status: "failed", error: "Meta refused it" })], false, "Meta refused it"),
    });
    await userEvent.type(box(), "stuck{Enter}");
    expect(await screen.findByText("Meta refused it")).toBeInTheDocument();
    expect(document.querySelector('[data-uid="out-9"]')).toHaveClass("bub--failed");
    expect(document.querySelectorAll(".bub--pending")).toHaveLength(0);
    expect(box()).toHaveValue("");
  });

  it("keeps a message on its way when the person goes to another conversation, and shows how it ended", async () => {
    let fail: (value: Response) => void = () => undefined;
    const first = await open({ [SEND]: () => new Promise<Response>((resolve) => (fail = resolve)) });
    await userEvent.type(box(), "on its way{Enter}");
    await screen.findByText("on its way");
    first.unmount();

    // The answer comes while nobody is looking, and it is a refusal.
    await act(async () => fail(jsonResponse({ ok: false, error: "forbidden" }, 403)));

    // Back in the conversation: the message is there, failed, not lost.
    render("/chats/CL-0001", { thread: { client: row("CL-0001"), messages: [entry(1)] } }, {}, { client: first.client });
    const bubble = (await screen.findByText("on its way")).closest(".bub") as HTMLElement;
    expect(bubble).toHaveClass("bub--failed");
    expect(bubble).toHaveTextContent("مش مسموحلك ترد");
  });

  it("does not show a message twice when the doorbell brings it before the server's answer does", async () => {
    let release: (value: Response) => void = () => undefined;
    const view = await open({ [SEND]: () => new Promise<Response>((resolve) => (release = resolve)) });
    await userEvent.type(box(), "twice?{Enter}");
    await screen.findByText("twice?");
    act(() => {
      view.client.setQueryData(qk.thread("CL-0001"), { ok: true, client: row("CL-0001"), messages: [entry(1), ours(9, "twice?")] });
    });
    await waitFor(() => expect(screen.getAllByText("twice?")).toHaveLength(1));
    expect(document.querySelector('[data-uid="out-9"]')).not.toBeNull();
    expect(document.querySelectorAll(".bub--pending")).toHaveLength(0);
    release(answer([entry(1), ours(9, "twice?")]));
    await waitFor(() => expect(screen.getAllByText("twice?")).toHaveLength(1));
  });

  it("shows a line on its way even when the same words were sent before", async () => {
    // Our "ok" is already in the thread: the new one must not be taken for it and hidden.
    let release: (value: Response) => void = () => undefined;
    await open(
      { [SEND]: () => new Promise<Response>((resolve) => (release = resolve)) },
      { thread: { client: row("CL-0001"), messages: [entry(1), ours(9, "ok")] } },
    );
    await userEvent.type(box(), "ok{Enter}");
    expect(await screen.findByText("بيتبعت...")).toBeInTheDocument();
    expect(document.querySelectorAll(".bub--pending")).toHaveLength(1);
    release(answer([entry(1), ours(9, "ok"), ours(10, "ok")]));
    await waitFor(() => expect(document.querySelectorAll(".bub--pending")).toHaveLength(0));
    expect(screen.getAllByText("ok")).toHaveLength(2);
  });

  it("shows two identical lines sent one after the other as two messages", async () => {
    let n = 0;
    await open({
      [SEND]: () => {
        n += 1;
        return answer([entry(1), ...Array.from({ length: n }, (_, i) => ours(9 + i, "ok"))]);
      },
    });
    await userEvent.type(box(), "ok{Enter}");
    await waitFor(() => expect(screen.getAllByText("ok")).toHaveLength(1));
    await waitFor(() => expect(sendButton()).toBeDisabled());
    await userEvent.type(box(), "ok{Enter}");
    await waitFor(() => expect(screen.getAllByText("ok")).toHaveLength(2));
  });
});

describe("how long", () => {
  const paste = async (text: string) => {
    await userEvent.click(box());
    await userEvent.paste(text);
  };

  it("says how long the message is when it nears what WhatsApp carries, and will not send what is over it", async () => {
    const { calls } = await open({ [SEND]: () => answer([entry(1), ours(9, "x")]) });
    await paste("x".repeat(3000));
    expect(document.querySelector(".cchat__count")).toBeNull();
    await userEvent.clear(box());
    await paste("x".repeat(3700));
    expect(document.querySelector(".cchat__count")).toHaveTextContent("3700 / 4000");
    expect(sendButton()).toBeEnabled();

    await userEvent.clear(box());
    await paste("x".repeat(4001));
    expect(document.querySelector(".cchat__count")).toHaveTextContent("4001 / 4000");
    expect(screen.getByRole("alert", { name: "" })).toHaveTextContent("قصّرها");
    expect(sendButton()).toBeDisabled();
    await userEvent.type(box(), "{Enter}");
    expect(posts(calls)).toHaveLength(0);
    // The spaces around it do not count.
    await userEvent.clear(box());
    await paste("  " + "x".repeat(4000) + "  ");
    expect(sendButton()).toBeEnabled();
  });

  it("allows more inside: a colleague, or a work group, up to its own limit", async () => {
    render("/chats/g2", { thread: { client: row("g2", { group: true, team: true, channel: "" }), messages: [entry(1)] } });
    await screen.findByRole("textbox", { name: "الرسالة" });
    await paste("x".repeat(4001));
    expect(sendButton()).toBeEnabled();
    expect(document.querySelector(".cchat__count")).toBeNull();
    await userEvent.clear(box());
    await paste("x".repeat(10001));
    expect(document.querySelector(".cchat__count")).toHaveTextContent("10001 / 10000");
    expect(sendButton()).toBeDisabled();
  });

  it("takes the limit from the server, and a client group's is shorter by the role that goes in front of the words", async () => {
    const limits = { ...me().limits, to_client_group: 3987 };
    render(
      "/chats/g1",
      { thread: { client: row("g1", { group: true, reaches_client: true }), messages: [entry(1)] } },
      { "/api/v1/me/": () => jsonResponse({ ...me({ role: "team_lead" }), limits }) },
    );
    await screen.findByRole("textbox", { name: "الرسالة" });
    await paste("x".repeat(3987));
    expect(sendButton()).toBeEnabled();
    expect(document.querySelector(".cchat__count")).toHaveTextContent("3987 / 3987");
    await userEvent.type(box(), "y");
    expect(document.querySelector(".cchat__count")).toHaveTextContent("3988 / 3987");
    expect(sendButton()).toBeDisabled();
  });

  it("says why when the server refuses a message as too long", async () => {
    await open({ [SEND]: () => jsonResponse({ ok: false, error: "too_long" }, 400) });
    await userEvent.type(box(), "short but refused{Enter}");
    expect(await screen.findByText(/أطول من الحد المسموح/)).toBeInTheDocument();
  });
});

describe("a message that did not go is not hidden", () => {
  it("is marked in the list, so it is seen from another conversation, and the mark goes when it is given up", async () => {
    const view = await open(
      { [SEND]: () => jsonResponse({ ok: false, error: "forbidden" }, 403) },
      { lists: { clients: [row("CL-0001"), row("CL-0002")] } },
    );
    await userEvent.type(box(), "stuck{Enter}");
    await screen.findByRole("button", { name: "امسح" });
    const marked = () => Array.from(document.querySelectorAll(".cthread")).filter((r) => r.querySelector(".cthread__problem")).map((r) => r.getAttribute("data-code"));
    await waitFor(() => expect(marked()).toEqual(["CL-0001"]));
    await userEvent.click(screen.getByRole("button", { name: "امسح" }));
    await waitFor(() => expect(marked()).toEqual([]));
    view.unmount();
  });

  it("is not marked while it is only on its way", async () => {
    let release: (value: Response) => void = () => undefined;
    await open(
      { [SEND]: () => new Promise<Response>((resolve) => (release = resolve)) },
      { lists: { clients: [row("CL-0001")] } },
    );
    await userEvent.type(box(), "on its way{Enter}");
    await screen.findByText("بيتبعت...");
    expect(document.querySelector(".cthread__problem")).toBeNull();
    release(answer([entry(1)]));
  });
});

describe("the 24-hour window", () => {
  it("turns the box off for a client whose window is closed, and says why", async () => {
    const { calls } = render("/chats/CL-0001", { thread: { client: row("CL-0001", { window_open: false }), messages: [entry(1)] } });
    await screen.findByText("message 1");
    expect(box()).toBeDisabled();
    expect(box()).toHaveAttribute("placeholder", expect.stringContaining("نافذة الـ24 ساعة قفلت"));
    expect(sendButton()).toBeDisabled();
    expect(posts(calls)).toHaveLength(0);
  });

  it("does the same for a group that reaches the client", async () => {
    render("/chats/g1", { thread: { client: row("g1", { group: true, reaches_client: true, window_open: false }), messages: [entry(1)] } });
    await screen.findByText("message 1");
    expect(box()).toBeDisabled();
  });

  it("leaves the box on for e-mail, for a work group - even one that belongs to a client's task - and for a colleague", async () => {
    const mail = render("/chats/CL-0004", { thread: { client: row("CL-0004", { channel: "email", window_open: false }), messages: [entry(1)] } });
    await screen.findByText("message 1");
    expect(box()).toBeEnabled();
    mail.unmount();

    const work = render("/chats/g2", { thread: { client: row("g2", { group: true, team: true, channel: "whatsapp", window_open: false }), messages: [entry(1)] } });
    await screen.findByText("message 1");
    expect(box()).toBeEnabled();
    expect(screen.queryByText("نافذة الـ24 ساعة قفلت")).not.toBeInTheDocument();
    work.unmount();

    render("/chats/u5", { thread: { client: row("u5", { staff: true, channel: "", window_open: false }), messages: [entry(1)] } });
    await screen.findByText("message 1");
    expect(box()).toBeEnabled();
  });

  it("leaves the box on while the window is open", async () => {
    render("/chats/CL-0001", { thread: { client: row("CL-0001", { window_open: true }), messages: [entry(1)] } });
    await screen.findByText("message 1");
    expect(box()).toBeEnabled();
  });
});

describe("writing is not reading", () => {
  const readPosts = (calls: Call[]) => posts(calls, "/read/");
  const readBodies = (calls: Call[]) => readPosts(calls).map((c) => JSON.parse(String(c.init?.body)));

  it("marks read what was on screen when it was opened, and what the answer to a send shows, and nothing more", async () => {
    // The server's own state: the send adds our message, and the client has written once more meanwhile.
    let server: ThreadEntry[] = [entry(1, { uid: "in-1" })];
    const { calls } = await open(
      {
        [SEND]: () => {
          server = [entry(1, { uid: "in-1" }), ours(9, "reply"), entry(6, { uid: "in-6", body: "arrived meanwhile" })];
          return answer(server);
        },
        "/api/v1/clients/CL-0001/messages/": () => jsonResponse({ ok: true, client: row("CL-0001"), messages: server }),
        "/api/v1/clients/CL-0001/read/": () => jsonResponse({ ok: true, moved: true }),
      },
    );
    await waitFor(() => expect(readBodies(calls)).toEqual([{ upto: 1 }]));
    await userEvent.type(box(), "reply{Enter}");
    await screen.findByText("arrived meanwhile");
    // The send itself marked nothing; what the answer showed is what is read - up to it, in a POST of its own.
    await waitFor(() => expect(readBodies(calls)).toEqual([{ upto: 1 }, { upto: 6 }]));
    expect(posts(calls)).toHaveLength(1);
  });

  it("does not post a read for a send whose answer shows nothing new", async () => {
    const { calls } = await open(
      {
        [SEND]: () => answer([entry(1, { uid: "in-1" }), ours(9, "reply")]),
        "/api/v1/clients/CL-0001/read/": () => jsonResponse({ ok: true, moved: false }),
      },
      { thread: { client: row("CL-0001"), messages: [entry(1, { uid: "in-1" })] } },
    );
    await waitFor(() => expect(readBodies(calls)).toEqual([{ upto: 1 }]));
    await userEvent.type(box(), "reply{Enter}");
    await screen.findByText("reply");
    await new Promise((resolve) => setTimeout(resolve, 60));
    expect(readBodies(calls)).toEqual([{ upto: 1 }]);
  });
});

describe("what was typed and not sent", () => {
  it("is still in the box when the person comes back to the conversation", async () => {
    const first = await open();
    await userEvent.type(box(), "half a thought");
    first.unmount();
    render("/chats/CL-0001", { thread: { client: row("CL-0001"), messages: [entry(1)] } });
    await screen.findByText("message 1");
    expect(box()).toHaveValue("half a thought");
  });

  it("is kept for each conversation on its own", async () => {
    const first = await open();
    await userEvent.type(box(), "for the client");
    first.unmount();
    render("/chats/g12", { thread: { client: row("g12", { group: true, team: true, channel: "" }), messages: [entry(1)] } });
    await screen.findByText("message 1");
    expect(box()).toHaveValue("");
  });

  it("is gone once it is sent", async () => {
    const first = await open({ [SEND]: () => answer([entry(1), ours(9, "sent text")]) });
    await userEvent.type(box(), "sent text{Enter}");
    await screen.findByText("sent text");
    first.unmount();
    render("/chats/CL-0001", { thread: { client: row("CL-0001"), messages: [entry(1)] } });
    await screen.findByText("message 1");
    expect(box()).toHaveValue("");
  });
});
