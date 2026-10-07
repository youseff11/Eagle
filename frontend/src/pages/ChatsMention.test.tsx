import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ThreadEntry } from "../api/types";
import { forgetDrafts } from "../components/chat/Composer";
import { entry, renderChats as render, row, visible } from "../test/chat";
import { jsonResponse } from "../test/helpers";

/** In a work group, an "@" names a colleague: the list of the people in it, the ids sent, and the name drawn in the words. */

beforeEach(() => {
  visible("visible");
  forgetDrafts();
  window.localStorage.clear();
});
afterEach(() => {
  vi.unstubAllGlobals();
  visible("visible");
});

type Call = { url: string; init?: RequestInit };
const posts = (calls: Call[]) => calls.filter((c) => c.init?.method === "POST" && c.url.endsWith("/send/"));
const form = (call: Call) => Object.fromEntries(new URLSearchParams(String(call.init?.body)));

// The person at the screen is user 7 (Nour); the others in the group are Mona and Sam.
const MEMBERS = [
  { id: 7, name: "Nour", initials: "N", avatar: null, role: "operation" },
  { id: 8, name: "Mona", initials: "M", avatar: null, role: "translator" },
  { id: 9, name: "Sam", initials: "S", avatar: null, role: "team_lead" },
];

const ours = (id: number, body: string, extra: Partial<ThreadEntry> = {}) =>
  entry(id, { uid: `g2-${id}`, kind: "out", mine: true, body, sender: "Nour", sender_id: 7, status: "sent", ...extra });

const sentAnswer = (messages: ThreadEntry[], group = row("g2", { group: true, team: true, channel: "", room: 2 })) =>
  jsonResponse({ ok: true, delivered: true, error: "", messages, client: group });

const box = () => screen.getByRole("textbox", { name: "الرسالة" });
const listbox = () => screen.queryByRole("listbox");
const names = () => within(screen.getByRole("listbox")).getAllByRole("option").map((one) => one.querySelector("b")?.textContent);

async function openGroup(
  group: Partial<Parameters<typeof row>[1]> = {},
  messages: ThreadEntry[] = [],
  extra: Parameters<typeof render>[2] = {},
  members = MEMBERS,
) {
  const client = row("g2", { group: true, team: true, channel: "", room: 2, ...group });
  const view = render(
    "/chats/g2",
    { thread: { client, messages } },
    {
      "/api/v1/groups/2/members/": () => jsonResponse({ ok: true, members, can_add: false, addable: [] }),
      "/api/v1/groups/2/send/": () => sentAnswer([ours(9, "sent")], client),
      ...extra,
    },
  );
  await screen.findByRole("textbox", { name: "الرسالة" });
  // The people are known once their own request has been answered.
  await waitFor(() => expect(view.calls.some((call) => call.url === "/api/v1/groups/2/members/")).toBe(true));
  return view;
}

describe("the list of people under an @", () => {
  it("opens on an @ and names the others in the group, not the person writing", async () => {
    await openGroup();
    await userEvent.type(box(), "@");
    await waitFor(() => expect(listbox()).not.toBeNull());
    expect(names()).toEqual(["Mona", "Sam"]);
    // Each is told apart by the job they do, so two of one name are not a guess.
    expect(within(screen.getByRole("listbox")).getByText("مترجم")).toBeInTheDocument();
    expect(within(screen.getByRole("listbox")).getByText("تيم ليدر")).toBeInTheDocument();
  });

  it("narrows to what is typed after the @, and closes when nobody matches or the @ is left behind", async () => {
    await openGroup();
    await userEvent.type(box(), "hi @mo");
    await waitFor(() => expect(names()).toEqual(["Mona"]));
    await userEvent.type(box(), "zzz");
    await waitFor(() => expect(listbox()).toBeNull());
    await userEvent.clear(box());
    await userEvent.type(box(), "an e-mail me@sa");
    expect(listbox()).toBeNull();
  });

  it("puts the name in, with a space after it, on Enter - and Enter does not send the message", async () => {
    const { calls } = await openGroup();
    await userEvent.type(box(), "hi @mo{Enter}");
    expect(box()).toHaveValue("hi @Mona ");
    expect(listbox()).toBeNull();
    expect(posts(calls)).toHaveLength(0);
  });

  it("sends the id of the one picked, and the words with the name in them", async () => {
    const { calls } = await openGroup();
    await userEvent.type(box(), "@mo{Enter}please look{Enter}");
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(form(posts(calls)[0]!)).toEqual({ body: "@Mona please look", mentions: "8" });
    expect(box()).toHaveValue("");
  });

  it("takes a tap on a name as it takes Enter, and the cursor stays in the box", async () => {
    await openGroup();
    await userEvent.type(box(), "@");
    await userEvent.click(await screen.findByRole("option", { name: /Sam/ }));
    expect(box()).toHaveValue("@Sam ");
    await waitFor(() => expect(box()).toHaveFocus());
  });

  it("moves with the arrows, around the ends, and takes the one it stands on", async () => {
    const { calls } = await openGroup();
    await userEvent.type(box(), "@");
    await screen.findByRole("listbox");
    expect(screen.getByRole("option", { name: /Mona/ })).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("option", { name: /Sam/ })).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("option", { name: /Mona/ })).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{ArrowUp}{Enter}");
    expect(box()).toHaveValue("@Sam ");
    expect(posts(calls)).toHaveLength(0);
  });

  it("is closed by Escape without sending, clearing the words or dropping the reply", async () => {
    const { calls } = await openGroup({}, [entry(5, { uid: "g2-5", kind: "out", mine: false, sender: "Mona", sender_id: 8, body: "the file" })]);
    fireEvent.click(document.querySelector('[data-uid="g2-5"] .bub__reply')!);
    await screen.findByText("الرد على", { exact: false }).catch(() => undefined);
    await userEvent.type(box(), "@");
    await screen.findByRole("listbox");
    await userEvent.keyboard("{Escape}");
    expect(listbox()).toBeNull();
    expect(box()).toHaveValue("@");
    expect(document.querySelector(".cchat__replybar")).not.toBeNull();
    expect(posts(calls)).toHaveLength(0);
    // And the next Escape is the reply's, as it always was.
    await userEvent.keyboard("{Escape}");
    expect(document.querySelector(".cchat__replybar")).toBeNull();
  });

  it("does not take Enter while an input method is still composing", async () => {
    await openGroup();
    await userEvent.type(box(), "@mo");
    await screen.findByRole("listbox");
    fireEvent.keyDown(box(), { key: "Enter", isComposing: true });
    expect(box()).toHaveValue("@mo");
  });

  it("has a button for the @, for a keyboard where it is hard to reach", async () => {
    await openGroup();
    await userEvent.type(box(), "look");
    await userEvent.click(screen.getByRole("button", { name: "منشن لحد في الجروب" }));
    expect(box()).toHaveValue("look @");
    expect(await screen.findByRole("listbox")).toBeInTheDocument();
  });
});

describe("what is sent", () => {
  it("leaves a person out once their name is taken out of the words", async () => {
    const { calls } = await openGroup();
    await userEvent.type(box(), "@mo{Enter}");
    await userEvent.clear(box());
    await userEvent.type(box(), "never mind{Enter}");
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(form(posts(calls)[0]!)).toEqual({ body: "never mind" });
  });

  it("counts a name typed in full by hand, when nobody else in the group has it", async () => {
    const { calls } = await openGroup();
    await userEvent.type(box(), "@Sam{Escape} look{Enter}");
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(form(posts(calls)[0]!)).toEqual({ body: "@Sam look", mentions: "9" });
  });

  it("does not guess between two people of one name: only the one picked from the list is sent", async () => {
    const twins = [...MEMBERS, { id: 10, name: "Mona", initials: "M", avatar: null, role: "reviewer" }];
    const { calls } = await openGroup({}, [], {}, twins);
    await userEvent.type(box(), "@Mona{Escape} look{Enter}");
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(form(posts(calls)[0]!)).toEqual({ body: "@Mona look" });

    await userEvent.type(box(), "@mo");
    await userEvent.click(await screen.findByRole("option", { name: /مراجع/ }));
    await userEvent.type(box(), "now{Enter}");
    await waitFor(() => expect(posts(calls)).toHaveLength(2));
    expect(form(posts(calls)[1]!)).toEqual({ body: "@Mona now", mentions: "10" });
  });

  it("goes with the files as well", async () => {
    const { calls } = await openGroup();
    await userEvent.type(box(), "@mo{Enter}the file");
    await userEvent.upload(screen.getByLabelText("إرفاق ملفات"), new File(["x"], "doc.txt", { type: "text/plain" }));
    await userEvent.click(screen.getByRole("button", { name: "إرسال" }));
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    const body = posts(calls)[0]!.init?.body as FormData;
    expect(body.get("body")).toBe("@Mona the file");
    expect(body.get("mentions")).toBe("8");
  });

  it("is kept with the words in the draft while another chat is looked at", async () => {
    await openGroup();
    await userEvent.type(box(), "@mo{Enter}wait");
    expect(box()).toHaveValue("@Mona wait");
  });

  it("shows the name in the bubble that is still on its way", async () => {
    let release: (answer: Response) => void = () => undefined;
    const slow = new Promise<Response>((done) => {
      release = done;
    });
    await openGroup({}, [], { "/api/v1/groups/2/send/": () => slow });
    await userEvent.type(box(), "@mo{Enter}look{Enter}");
    await waitFor(() => expect(document.querySelector(".bub--pending .bub__mention")).not.toBeNull());
    expect(document.querySelector(".bub--pending .bub__mention")).toHaveTextContent("@Mona");
    release(sentAnswer([ours(9, "@Mona look", { mentions: [{ id: 8, name: "Mona" }] })]));
    await waitFor(() => expect(document.querySelectorAll(".bub--pending")).toHaveLength(0));
  });
});

describe("where an @ is only a character", () => {
  it("is a group that reaches a client: nobody is offered, there is no button, and nothing is sent as a mention", async () => {
    const { calls } = await openGroup({ team: false, reaches_client: true, client_code: "CL-0001" });
    expect(screen.queryByRole("button", { name: "منشن لحد في الجروب" })).toBeNull();
    await userEvent.type(box(), "@mo");
    expect(listbox()).toBeNull();
    await userEvent.type(box(), "{Enter}");
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(form(posts(calls)[0]!)).toEqual({ body: "@mo" });
  });

  it("is a chat with one colleague", async () => {
    const { calls } = render(
      "/chats/u5",
      { thread: { client: row("u5", { staff: true, room: 9, channel: "", window_open: false }), messages: [] } },
      { "/api/v1/staff/5/send/": () => sentAnswer([ours(9, "@Mona", { uid: "g9-9" })], row("u5", { staff: true, room: 9 })) },
    );
    await screen.findByRole("textbox", { name: "الرسالة" });
    expect(screen.queryByRole("button", { name: "منشن لحد في الجروب" })).toBeNull();
    await userEvent.type(box(), "@Mo");
    expect(listbox()).toBeNull();
    await userEvent.type(box(), "{Enter}");
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(form(posts(calls)[0]!)).toEqual({ body: "@Mo" });
  });

  it("is a client's own conversation", async () => {
    const { calls } = render("/chats/CL-0001", { thread: { client: row("CL-0001"), messages: [entry(1)] } }, {
      "/api/v1/clients/CL-0001/send/": () => sentAnswer([], row("CL-0001")),
    });
    await screen.findByRole("textbox", { name: "الرسالة" });
    expect(screen.queryByRole("button", { name: "منشن لحد في الجروب" })).toBeNull();
    await userEvent.type(box(), "@S{Enter}");
    expect(listbox()).toBeNull();
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(form(posts(calls)[0]!)).toEqual({ body: "@S" });
  });

  it("is a group with nobody else in it", async () => {
    await openGroup({}, [], {}, [MEMBERS[0]!]);
    expect(screen.queryByRole("button", { name: "منشن لحد في الجروب" })).toBeNull();
    await userEvent.type(box(), "@");
    expect(listbox()).toBeNull();
  });
});

describe("a mention in the thread", () => {
  const others = (id: number, body: string, extra: Partial<ThreadEntry> = {}) =>
    entry(id, { uid: `g2-${id}`, kind: "out", mine: false, sender: "Sam", sender_id: 9, body, status: "sent", ...extra });

  it("draws the people a message mentions as names, and every other @ as the plain words it is", async () => {
    await openGroup({}, [others(4, "hi @Nour and @Mona, ask @Omar", { mentions: [{ id: 7, name: "Nour" }, { id: 8, name: "Mona" }], mentions_me: true })]);
    const marked = [...document.querySelectorAll('[data-uid="g2-4"] .bub__mention')];
    expect(marked.map((one) => one.textContent)).toEqual(["@Nour", "@Mona"]);
    expect(marked.map((one) => one.getAttribute("data-mention"))).toEqual(["7", "8"]);
    expect(document.querySelector('[data-uid="g2-4"] .bub__text')).toHaveTextContent("hi @Nour and @Mona, ask @Omar");
  });

  it("marks the bubble that names the person looking, and not one that names somebody else", async () => {
    await openGroup({}, [
      others(4, "@Nour look", { mentions: [{ id: 7, name: "Nour" }], mentions_me: true }),
      others(5, "@Mona look", { mentions: [{ id: 8, name: "Mona" }], mentions_me: false }),
      others(6, "plain"),
    ]);
    expect(document.querySelector('[data-uid="g2-4"]')).toHaveClass("bub--ping");
    expect(document.querySelector('[data-uid="g2-5"]')).not.toHaveClass("bub--ping");
    expect(document.querySelector('[data-uid="g2-6"]')).not.toHaveClass("bub--ping");
  });

  it("does not mark a message that was taken back", async () => {
    await openGroup({}, [others(4, "", { unsent: true, mentions: [], mentions_me: true })]);
    expect(document.querySelector('[data-uid="g2-4"]')).not.toHaveClass("bub--ping");
  });

  it("does not make a mention of an @ in a client's thread, where the server sends none", async () => {
    render("/chats/CL-0001", { thread: { client: row("CL-0001"), messages: [entry(1, { body: "please @Nour" })] } });
    await screen.findByText("please @Nour");
    expect(document.querySelector(".bub__mention")).toBeNull();
  });
});
