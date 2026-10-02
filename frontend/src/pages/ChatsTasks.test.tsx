import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ThreadEntry } from "../api/types";
import { dayLabel } from "../components/chat/PickBar";
import { forgetDrafts } from "../components/chat/Composer";
import { newTaskUrl } from "../lib/taskLink";
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

type Call = { url: string; init?: RequestInit };
const posts = (calls: Call[], path: string) => calls.filter((c) => c.init?.method === "POST" && c.url === path);
const body = (call: Call) => JSON.parse(String(call.init?.body));

const CONFIRM = "/api/v1/messages/1/confirm/";
const FORWARD = "/api/v1/chats/forward/";

/** A client's messages: two with documents on different days, one with a voice note, one with only words. */
const doc = (id: number, name: string) => file({ id, name, url: `/files/in/${name}` });
const day1a = entry(1, { uid: "in-1", date: "2026-10-01", body: "the contract", actions: true, has_docs: true, files: [doc(11, "contract.pdf"), doc(12, "stamps.pdf")] });
const day1b = entry(2, { uid: "in-2", date: "2026-10-01", body: "one more page", actions: true, has_docs: true, files: [doc(13, "page.pdf")] });
const day2 = entry(3, { uid: "in-3", date: "2026-10-02", body: "the appendix", actions: true, has_docs: true, files: [doc(14, "appendix.pdf")] });
const voice = entry(4, {
  uid: "in-4", date: "2026-10-02", body: "", actions: true, has_docs: false,
  files: [file({ id: 15, name: "note.ogg", url: "/files/in/note.ogg", audio: true, voice: true, mime: "audio/ogg" })],
});
const words = entry(5, { uid: "in-5", date: "2026-10-02", body: "just words", actions: true, has_docs: false });
const ours = entry(6, { uid: "out-6", kind: "out", date: "2026-10-02", body: "we got it", sender: "Nour", mine: true, status: "sent" });
const messages = [day1a, day1b, day2, voice, words, ours];
const client = row("CL-0001");

async function open(extra: Parameters<typeof render>[2] = {}, setup: Parameters<typeof render>[1] = {}, thread = { client, messages }) {
  const view = render("/chats/CL-0001", { thread, lists: { staff: [row("u5", { staff: true, label: "Sam", initials: "SM" })], groups: [], clients: [] }, ...setup }, extra);
  await screen.findByText("the contract");
  return view;
}

describe("the link to the task form", () => {
  it("names the messages and the files, and leaves out files when there are none", () => {
    expect(newTaskUrl([1, 2], [11, 12, 13])).toBe("/ops/tasks/new/?messages=1,2&files=11,12,13");
    expect(newTaskUrl([5], [])).toBe("/ops/tasks/new/?messages=5");
  });

  it("calls a day by its name when it is today or yesterday, and by its date otherwise", () => {
    const t = (ar: string) => ar;
    const now = new Date(2026, 9, 2, 12);
    expect(dayLabel("2026-10-02", t, now)).toBe("النهارده");
    expect(dayLabel("2026-10-01", t, now)).toBe("امبارح");
    expect(dayLabel("2026-09-28", t, now)).toBe("28/09/2026");
    expect(dayLabel("nonsense", t, now)).toBe("nonsense");
  });
});

describe("under a client's message", () => {
  it("has «استلمت» and «تحويل لتاسك» only under messages that carry a document", async () => {
    await open();
    expect(screen.getAllByRole("button", { name: "استلمت" })).toHaveLength(3);
    expect(screen.getAllByRole("button", { name: "تحويل لتاسك" })).toHaveLength(3);
    // The voice note and the words have neither, and neither has our own message.
    for (const uid of ["in-4", "in-5", "out-6"]) {
      expect(within(document.querySelector(`[data-uid="${uid}"]`) as HTMLElement).queryByRole("button", { name: "استلمت" })).toBeNull();
    }
  });

  it("has neither when the server does not give this person the actions", async () => {
    const plain = messages.map((m) => ({ ...m, actions: false }));
    await open({}, {}, { client, messages: plain });
    expect(screen.queryByRole("button", { name: "استلمت" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "تحويل لتاسك" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "تحديد ملفات" })).not.toBeInTheDocument();
  });

  it("has neither for a Sales person, who may not answer from this thread", async () => {
    await open({}, { role: { role: "sales" } });
    expect(screen.queryByRole("button", { name: "استلمت" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "تحويل لتاسك" })).not.toBeInTheDocument();
  });

  it("says which task a message already is, offers a new request on it, and who has said «received»", async () => {
    const claimed = entry(1, { uid: "in-1", date: "2026-10-01", body: "the contract", actions: true, has_docs: true, task_code: "TSK-00007", has_task: true, claimed_by: "Hana", files: [doc(11, "contract.pdf")] });
    await open({}, {}, { client, messages: [claimed] });
    const actions = document.querySelector(".bub__actions") as HTMLElement;
    expect(within(actions).getByText("TSK-00007")).toBeInTheDocument();
    expect(within(actions).getByRole("button", { name: "طلب جديد" })).toBeInTheDocument();
    expect(within(actions).queryByRole("button", { name: "تحويل لتاسك" })).not.toBeInTheDocument();
    expect(within(actions).getByText("Hana")).toBeInTheDocument();
  });
});

describe("«استلمت»", () => {
  const dialog = () => screen.getByRole("dialog");
  const first = () => within(document.querySelector('[data-uid="in-1"]') as HTMLElement).getByRole("button", { name: "استلمت" });

  it("asks first, and sends nothing until it is answered", async () => {
    const { calls } = await open({ [CONFIRM]: () => jsonResponse({ ok: true, message: "", claimed_by: "Nour" }) });
    await userEvent.click(first());
    expect(within(dialog()).getByText("هيتبعت للعميل رد فيه كلمة confirmed. تمام؟")).toBeInTheDocument();
    await userEvent.click(within(dialog()).getByRole("button", { name: "إلغاء" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(posts(calls, CONFIRM)).toHaveLength(0);
  });

  it("sends the receipt for that message, closes, and asks for the thread again", async () => {
    document.cookie = "csrftoken=tokR";
    const { calls } = await open({ [CONFIRM]: () => jsonResponse({ ok: true, message: "", claimed_by: "Nour" }) });
    await userEvent.click(first());
    await userEvent.click(within(dialog()).getByRole("button", { name: "تمام" }));
    await waitFor(() => expect(posts(calls, CONFIRM)).toHaveLength(1));
    expect(new Headers(posts(calls, CONFIRM)[0]!.init?.headers).get("X-CSRFToken")).toBe("tokR");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/v1/clients/CL-0001/messages/").length).toBeGreaterThan(1));
    document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("says why, in the server's words, and keeps the question", async () => {
    await open({ [CONFIRM]: () => jsonResponse({ ok: false, error: "refused", message: "الرسالة دي محجوبة." }, 400) });
    await userEvent.click(first());
    await userEvent.click(within(dialog()).getByRole("button", { name: "تمام" }));
    expect(await within(dialog()).findByText("الرسالة دي محجوبة.")).toBeInTheDocument();
    expect(within(dialog()).getByRole("button", { name: "تمام" })).toBeEnabled();
  });

  it("does not claim it failed when nothing came back or the server broke: the receipt may be out", async () => {
    for (const answer of [() => Promise.reject(new TypeError("down")), () => jsonResponse({ ok: false, error: "server" }, 500)]) {
      const view = await open({ [CONFIRM]: answer });
      await userEvent.click(first());
      await userEvent.click(within(dialog()).getByRole("button", { name: "تمام" }));
      expect(await within(dialog()).findByText(/مش متأكدين إن الرد وصل/)).toBeInTheDocument();
      view.unmount();
    }
  });

  it("sends once however often the button is pressed, and cannot be closed meanwhile", async () => {
    let release: (value: Response) => void = () => undefined;
    const { calls } = await open({ [CONFIRM]: () => new Promise<Response>((resolve) => (release = resolve)) });
    await userEvent.click(first());
    await userEvent.click(within(dialog()).getByRole("button", { name: "تمام" }));
    const busy = within(dialog()).getByRole("button", { name: "بيتبعت..." });
    expect(busy).toBeDisabled();
    await userEvent.click(busy);
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(posts(calls, CONFIRM)).toHaveLength(1);
    act(() => release(jsonResponse({ ok: true, message: "", claimed_by: "Nour" })));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

describe("«تحويل لتاسك» on one message", () => {
  const dialog = () => screen.getByRole("dialog");
  const open_ = async (uid = "in-1") => {
    await userEvent.click(within(document.querySelector(`[data-uid="${uid}"]`) as HTMLElement).getByRole("button", { name: "تحويل لتاسك" }));
    await screen.findByRole("dialog");
  };

  it("lists the message's documents, all ticked, and leads to the task form with the ones left ticked", async () => {
    await open();
    await open_();
    expect(within(dialog()).getAllByRole("checkbox")).toHaveLength(2);
    expect(within(dialog()).getByRole("link", { name: "كمّل" })).toHaveAttribute("href", "/ops/tasks/new/?messages=1&files=11,12");
    await userEvent.click(within(dialog()).getByRole("checkbox", { name: /stamps/ }));
    expect(within(dialog()).getByRole("link", { name: "كمّل" })).toHaveAttribute("href", "/ops/tasks/new/?messages=1&files=11");
    await userEvent.click(within(dialog()).getByRole("checkbox", { name: /contract/ }));
    expect(within(dialog()).getByRole("link", { name: "كمّل" })).toHaveAttribute("href", "/ops/tasks/new/?messages=1");
  });

  it("does not list a voice note as a document of the job", async () => {
    const mixed = entry(1, {
      uid: "in-1", date: "2026-10-01", body: "the contract", actions: true, has_docs: true,
      files: [doc(11, "contract.pdf"), file({ id: 16, name: "note.ogg", audio: true, voice: true, mime: "audio/ogg" })],
    });
    await open({}, {}, { client, messages: [mixed] });
    await open_();
    expect(within(dialog()).getAllByRole("checkbox")).toHaveLength(1);
    expect(within(dialog()).getByRole("link", { name: "كمّل" })).toHaveAttribute("href", "/ops/tasks/new/?messages=1&files=11");
  });

  it("closes with Cancel and Escape and changes nothing", async () => {
    const { calls } = await open();
    await open_();
    await userEvent.click(within(dialog()).getByRole("button", { name: "إلغاء" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await open_();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    // Nothing was written: the only POST there is is the page saying it has read the conversation.
    expect(calls.filter((c) => c.init?.method === "POST" && !c.url.endsWith("/read/"))).toHaveLength(0);
  });
});

describe("select files", () => {
  const toggle = () => screen.getByRole("button", { name: "تحديد ملفات" });
  const bar = () => screen.getByRole("toolbar", { name: "تحديد ملفات" });
  const count = () => within(bar()).getByText(/^\d+$/);
  const dayBox = () => within(bar()).getByRole("combobox", { name: "ملفات يوم معيّن" });
  const boxes = () => screen.queryAllByRole("checkbox");
  const dialog = () => screen.getByRole("dialog");

  it("is offered when the conversation has documents to pick, and not when it has none", async () => {
    await open();
    expect(toggle()).toHaveAttribute("aria-pressed", "false");
  });

  it("is not offered when nothing in the conversation is a document", async () => {
    render("/chats/CL-0001", { thread: { client, messages: [words, voice, ours] } });
    await screen.findByText("just words");
    expect(screen.queryByRole("button", { name: "تحديد ملفات" })).not.toBeInTheDocument();
  });

  it("draws a box on every document - not on a voice note - and takes the box to write in away", async () => {
    await open();
    await userEvent.click(toggle());
    expect(boxes().map((box) => box.getAttribute("aria-label"))).toEqual([
      "حدد الملف: contract.pdf", "حدد الملف: stamps.pdf", "حدد الملف: page.pdf", "حدد الملف: appendix.pdf",
    ]);
    expect(document.querySelector(".cchat__stream")).toHaveClass("is-picking");
    expect(screen.queryByRole("textbox", { name: "الرسالة" })).not.toBeInTheDocument();
    expect(count()).toHaveTextContent("0");
    expect(within(bar()).getByRole("button", { name: "تحويل لشات" })).toBeDisabled();
    expect(within(bar()).getByRole("button", { name: "تحويل لتاسك" })).toBeDisabled();
  });

  it("counts what is ticked across messages and leads to one task with the messages they are in", async () => {
    await open();
    await userEvent.click(toggle());
    await userEvent.click(screen.getByRole("checkbox", { name: /stamps/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /appendix/ }));
    expect(count()).toHaveTextContent("2");
    expect(within(bar()).getByRole("link", { name: "تحويل لتاسك" })).toHaveAttribute("href", "/ops/tasks/new/?messages=1,3&files=12,14");
    await userEvent.click(screen.getByRole("checkbox", { name: /stamps/ }));
    expect(count()).toHaveTextContent("1");
    expect(within(bar()).getByRole("link", { name: "تحويل لتاسك" })).toHaveAttribute("href", "/ops/tasks/new/?messages=3&files=14");
  });

  it("ticks a file when a tap lands on it instead of opening it", async () => {
    await open();
    await userEvent.click(toggle());
    await userEvent.click(screen.getByRole("link", { name: "page.pdf" }));
    expect(count()).toHaveTextContent("1");
    expect(screen.getByRole("checkbox", { name: /page/ })).toBeChecked();
    await userEvent.click(screen.getByRole("link", { name: "page.pdf" }));
    expect(count()).toHaveTextContent("0");
  });

  it("offers the days that have a file, with how many, newest first", async () => {
    await open();
    await userEvent.click(toggle());
    const options = within(dayBox()).getAllByRole("option").map((option) => option.textContent);
    expect(options[0]).toBe("كل الأيام");
    expect(options[1]).toMatch(/02\/10\/2026|النهارده|امبارح/);
    expect(options[1]).toMatch(/\(1\)/);
    expect(options[2]).toMatch(/\(3\)/);
  });

  it("makes a day a selection of its own, and «select all» works inside it", async () => {
    await open();
    await userEvent.click(toggle());
    await userEvent.click(screen.getByRole("checkbox", { name: /appendix/ }));
    await userEvent.selectOptions(dayBox(), within(dayBox()).getAllByRole("option")[2]!);
    // Choosing a day replaces what was ticked with that day's files.
    expect(count()).toHaveTextContent("3");
    expect(screen.getByRole("checkbox", { name: /appendix/ })).not.toBeChecked();
    expect(within(bar()).getByRole("button", { name: "شيل الكل" })).toBeInTheDocument();
    await userEvent.click(within(bar()).getByRole("button", { name: "شيل الكل" }));
    expect(count()).toHaveTextContent("0");
    await userEvent.click(within(bar()).getByRole("button", { name: "تحديد الكل" }));
    expect(count()).toHaveTextContent("3");
    // Back to every day: select all ticks the rest.
    await userEvent.selectOptions(dayBox(), "");
    expect(within(bar()).getByRole("button", { name: "تحديد الكل" })).toBeInTheDocument();
    await userEvent.click(within(bar()).getByRole("button", { name: "تحديد الكل" }));
    expect(count()).toHaveTextContent("4");
  });

  it("is left with Cancel and nothing stays ticked for the next time; the box to write in is back", async () => {
    await open();
    await userEvent.type(screen.getByRole("textbox", { name: "الرسالة" }), "half a thought");
    await userEvent.click(toggle());
    await userEvent.click(screen.getByRole("checkbox", { name: /page/ }));
    await userEvent.click(within(bar()).getByRole("button", { name: "إلغاء" }));
    expect(screen.queryByRole("toolbar")).not.toBeInTheDocument();
    expect(boxes()).toHaveLength(0);
    expect(screen.getByRole("textbox", { name: "الرسالة" })).toHaveValue("half a thought");
    await userEvent.click(toggle());
    expect(count()).toHaveTextContent("0");
  });

  it("forwards the ticked files - and only files, by id - to another conversation", async () => {
    const { calls } = await open({
      [FORWARD]: () => jsonResponse({ ok: true, delivered: true, message: "", code: "u5" }),
      "/api/v1/staff/": () => jsonResponse({ ok: true, client: row("u5", { staff: true, label: "Sam" }), messages: [entry(1, { uid: "g9-1", body: "arrived there", forwarded: true })] }),
    });
    await userEvent.click(toggle());
    await userEvent.click(screen.getByRole("checkbox", { name: /contract/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /page/ }));
    await userEvent.click(within(bar()).getByRole("button", { name: "تحويل لشات" }));
    await screen.findByRole("dialog");
    await userEvent.click(await within(dialog()).findByRole("radio", { name: /Sam/ }));
    await userEvent.click(within(dialog()).getByRole("button", { name: "ابعت" }));
    await waitFor(() => expect(posts(calls, FORWARD)).toHaveLength(1));
    expect(body(posts(calls, FORWARD)[0]!)).toEqual({ source: "CL-0001", target: "u5", uids: [], files: [11, 13], note: "" });
    expect(await screen.findByText("arrived there")).toBeInTheDocument();
    expect(screen.queryByRole("toolbar")).not.toBeInTheDocument();
  });

  it("does not run together with picking messages to forward: starting one ends the other", async () => {
    await open();
    await userEvent.click(toggle());
    await userEvent.click(screen.getByRole("checkbox", { name: /contract/ }));
    await userEvent.click(screen.getByRole("button", { name: "تحويل رسايل" }));
    expect(screen.queryByRole("toolbar", { name: "تحديد ملفات" })).not.toBeInTheDocument();
    expect(screen.getByRole("toolbar", { name: "تحويل رسايل" })).toBeInTheDocument();
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    await userEvent.click(toggle());
    expect(screen.queryByRole("toolbar", { name: "تحويل رسايل" })).not.toBeInTheDocument();
    expect(count()).toHaveTextContent("0");
  });

  it("drops a ticked file that has gone from the thread", async () => {
    let now: ThreadEntry[] = messages;
    const { client: queries } = await open({ "/api/v1/clients/": () => jsonResponse({ ok: true, client, messages: now }) });
    await userEvent.click(toggle());
    await userEvent.click(screen.getByRole("checkbox", { name: /contract/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /page/ }));
    expect(count()).toHaveTextContent("2");
    now = [day1b, day2];
    await act(async () => {
      await queries.invalidateQueries();
    });
    await waitFor(() => expect(count()).toHaveTextContent("1"));
    expect(screen.queryByRole("checkbox", { name: /contract/ })).not.toBeInTheDocument();
  });

  it("is not there in a colleague's chat or a group", async () => {
    render("/chats/g1", { thread: { client: row("g1", { group: true, team: true, room: 11 }), messages: [entry(1, { uid: "g11-1", body: "hello group", files: [doc(21, "x.pdf")] })] } });
    await screen.findByText("hello group");
    expect(screen.queryByRole("button", { name: "تحديد ملفات" })).not.toBeInTheDocument();
  });
});

describe("the way to the client's page", () => {
  it("is a link beside the conversation's name, for the roles that answer clients", async () => {
    await open();
    expect(screen.getByRole("link", { name: "ملف العميل" })).toHaveAttribute("href", "/clients/CL-0001/");
  });

  it("is not there in a group", async () => {
    render("/chats/g1", { thread: { client: row("g1", { group: true, team: true, room: 11 }), messages: [entry(1, { uid: "g11-1", body: "hello group" })] } });
    await screen.findByText("hello group");
    expect(screen.queryByRole("link", { name: "ملف العميل" })).not.toBeInTheDocument();
  });
});
