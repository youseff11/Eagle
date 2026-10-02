import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ThreadEntry } from "../api/types";
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

type Call = { url: string; init?: RequestInit };
const posts = (calls: Call[], path: string) => calls.filter((c) => c.init?.method === "POST" && c.url === path);
const body = (call: Call) => JSON.parse(String(call.init?.body));

// The header's button; the files have buttons of the same name beside them.
const HEADER = "حدد ملفات الترجمة وخلّص التاسك";
const TASKS = "/api/v1/groups/11/handin-tasks/";
const HAND = "/api/v1/tasks/TSK-00001/hand-in/";
const room = row("g1", { group: true, team: true, label: "Work", room: 11 });

/** A message of this translator's with a file, one of the leader's, and a voice note of theirs. */
const mine1 = entry(5, { uid: "g11-5", mine: true, sender: "Omar", body: "first translation", files: [file({ id: 31, name: "a.docx", url: "/files/g/a.docx" })] });
const mine2 = entry(6, { uid: "g11-6", mine: true, sender: "Omar", body: "second translation", files: [file({ id: 32, name: "b.docx", url: "/files/g/b.docx" })] });
const theirs = entry(7, { uid: "g11-7", mine: false, sender: "Ahmed", body: "leader's file", files: [file({ id: 33, name: "lead.docx", url: "/files/g/lead.docx" })] });
const voice = entry(8, {
  uid: "g11-8", mine: true, sender: "Omar", body: "",
  files: [file({ id: 34, name: "note.ogg", url: "/files/g/note.ogg", audio: true, voice: true, mime: "audio/ogg" })],
});
const noId = entry(9, { uid: "g11-9", mine: true, sender: "Omar", body: "a delivery", files: [file({ id: 0, name: "gone.docx", url: "" })] });
const messages = [mine1, mine2, theirs, voice, noId];

const tasks = (...codes: string[]) => () => jsonResponse({ ok: true, tasks: codes.map((code) => ({ code, title: `Job ${code}` })) });
const handed = () => jsonResponse({ ok: true, code: "TSK-00001" });

async function open(extra: Parameters<typeof render>[2] = {}, setup: Parameters<typeof render>[1] = {}, thread = { client: room, messages }) {
  // The first route that matches wins and the thread's address is a prefix of the tasks': what a test adds goes first.
  const view = render("/chats/g1", { thread, role: { role: "translator" }, types: ["groups", "staff"], ...setup }, { [TASKS]: tasks("TSK-00001"), ...extra });
  await screen.findByText("first translation");
  return view;
}
const bar = () => screen.getByRole("toolbar", { name: "خلصت التاسك" });
const count = () => within(bar()).getByText(/^\d+$/);
const send = () => within(bar()).getByRole("button", { name: "خلصت التاسك" });
const boxes = () => screen.queryAllByRole("checkbox");
const dialog = () => screen.getByRole("dialog");

describe("the button", () => {
  it("is there for a translator in a work group who has a task to hand in", async () => {
    await open();
    expect(await screen.findByTitle(HEADER)).toBeInTheDocument();
  });

  it("is not there when there is no task to hand in to", async () => {
    await open({ [TASKS]: tasks() });
    await waitFor(() => expect(screen.getByText("first translation")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "خلصت التاسك" })).not.toBeInTheDocument();
    expect(screen.queryByRole("toolbar")).not.toBeInTheDocument();
  });

  it("is not asked for - and not drawn - for anybody who is not a translator", async () => {
    const { calls } = await open({}, { role: { role: "team_lead" } });
    expect(calls.some((c) => c.url === TASKS)).toBe(false);
    expect(screen.queryByRole("button", { name: "خلصت التاسك" })).not.toBeInTheDocument();
  });

  it("is not asked for in a colleague's chat, a client group or a client's thread", async () => {
    const staff = render("/chats/u5", { role: { role: "translator" }, types: ["groups", "staff"], thread: { client: row("u5", { staff: true, label: "Sam", room: 12 }), messages: [entry(1, { uid: "g12-1", body: "hi Sam" })] } });
    await screen.findByText("hi Sam");
    expect(staff.calls.some((c) => c.url.includes("handin-tasks"))).toBe(false);
    staff.unmount();

    const group = render("/chats/g2", {
      role: { role: "translator" }, types: ["groups", "staff"],
      thread: { client: row("g2", { group: true, reaches_client: true, label: "With Acme", room: 12 }), messages: [entry(1, { uid: "g12-1", body: "hi group" })] },
    });
    await screen.findByText("hi group");
    expect(group.calls.some((c) => c.url.includes("handin-tasks"))).toBe(false);
  });
});

describe("handing in", () => {
  it("draws a box only beside this person's own files - not the leader's, not a voice note, not one with no file behind it", async () => {
    await open();
    await userEvent.click(await screen.findByTitle(HEADER));
    expect(boxes().map((box) => box.getAttribute("aria-label"))).toEqual([
      "حدد الملف: a.docx",
      "حدد الملف: b.docx",
    ]);
    expect(document.querySelector(".cchat__stream")).toHaveClass("is-handing");
  });

  it("replaces the box to write in with a bar that says how many are ticked", async () => {
    await open();
    await userEvent.click(await screen.findByTitle(HEADER));
    expect(screen.queryByRole("textbox", { name: "الرسالة" })).not.toBeInTheDocument();
    expect(count()).toHaveTextContent("0");
    expect(send()).toBeDisabled();
    expect(within(bar()).getByText("TSK-00001")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("checkbox", { name: /a\.docx/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /b\.docx/ }));
    expect(count()).toHaveTextContent("2");
    expect(send()).toBeEnabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /a\.docx/ }));
    expect(count()).toHaveTextContent("1");
  });

  it("has a button beside each of the files that starts the same mode with that file ticked", async () => {
    await open();
    await screen.findByTitle(HEADER);
    // One beside each of the two files that are this person's own: not the leader's, not the voice note.
    const starters = Array.from(document.querySelectorAll<HTMLElement>(".bub__handbtn"));
    expect(starters).toHaveLength(2);
    await userEvent.click(starters[1]!);
    expect(count()).toHaveTextContent("1");
    expect(screen.getByRole("checkbox", { name: /b\.docx/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /a\.docx/ })).not.toBeChecked();
  });

  it("is left with Cancel, and the box to write in comes back with what was typed", async () => {
    await open();
    await userEvent.type(screen.getByRole("textbox", { name: "الرسالة" }), "half a thought");
    await userEvent.click(await screen.findByTitle(HEADER));
    await userEvent.click(screen.getByRole("checkbox", { name: /a\.docx/ }));
    await userEvent.click(within(bar()).getByRole("button", { name: "إلغاء" }));
    expect(screen.queryByRole("toolbar")).not.toBeInTheDocument();
    expect(boxes()).toHaveLength(0);
    expect(screen.getByRole("textbox", { name: "الرسالة" })).toHaveValue("half a thought");
    // And nothing stays ticked for the next time.
    await userEvent.click(screen.getByTitle(HEADER));
    expect(count()).toHaveTextContent("0");
  });

  it("asks once more, and nothing is sent until it is answered", async () => {
    const { calls } = await open({ [HAND]: handed });
    await userEvent.click(await screen.findByTitle(HEADER));
    await userEvent.click(screen.getByRole("checkbox", { name: /a\.docx/ }));
    await userEvent.click(send());
    expect(within(dialog()).getByText("الملفات دي هتتسجّل على TSK-00001 والتاسك هتروح للمراجعة. تمام؟")).toBeInTheDocument();
    await userEvent.click(within(dialog()).getByRole("button", { name: "إلغاء" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(posts(calls, HAND)).toHaveLength(0);
    // Still handing in, with the file still ticked.
    expect(count()).toHaveTextContent("1");
  });

  it("sends the ticked files for the task, ends the mode and says it went to review, with a way to the task", async () => {
    document.cookie = "csrftoken=tokH";
    const { calls } = await open({ [HAND]: handed });
    await userEvent.click(await screen.findByTitle(HEADER));
    await userEvent.click(screen.getByRole("checkbox", { name: /b\.docx/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /a\.docx/ }));
    await userEvent.click(send());
    await userEvent.click(within(dialog()).getByRole("button", { name: "تمام، ابعت" }));

    await waitFor(() => expect(posts(calls, HAND)).toHaveLength(1));
    const call = posts(calls, HAND)[0]!;
    expect(body(call)).toEqual({ files: [32, 31] });
    expect(new Headers(call.init?.headers).get("X-CSRFToken")).toBe("tokH");
    expect(await screen.findByRole("status")).toHaveTextContent("تمام: TSK-00001 راحت للمراجعة.");
    expect(screen.getByRole("link", { name: "افتح التاسك" })).toHaveAttribute("href", "/tasks/TSK-00001/");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("toolbar")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "الرسالة" })).toBeInTheDocument();
    // What the hand-in changed is asked for again: the group's messages, the tasks on offer, the desk.
    await waitFor(() => expect(calls.filter((c) => c.url === TASKS).length).toBeGreaterThan(1));
    document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("asks which task when there are several, and hands in to the one chosen", async () => {
    const second = "/api/v1/tasks/TSK-00002/hand-in/";
    const { calls } = await open({ [TASKS]: tasks("TSK-00001", "TSK-00002"), [second]: () => jsonResponse({ ok: true, code: "TSK-00002" }) });
    await userEvent.click(await screen.findByTitle(HEADER));
    await userEvent.click(screen.getByRole("checkbox", { name: /a\.docx/ }));
    await userEvent.selectOptions(within(bar()).getByRole("combobox", { name: "التاسك" }), "TSK-00002");
    await userEvent.click(send());
    expect(within(dialog()).getByText(/هتتسجّل على TSK-00002/)).toBeInTheDocument();
    await userEvent.click(within(dialog()).getByRole("button", { name: "تمام، ابعت" }));
    await waitFor(() => expect(posts(calls, second)).toHaveLength(1));
    expect(posts(calls, HAND)).toHaveLength(0);
    expect(await screen.findByRole("status")).toHaveTextContent("TSK-00002");
  });

  it("says why, in the server's words, when it will not, and keeps the picking", async () => {
    await open({ [HAND]: () => jsonResponse({ ok: false, error: "refused", message: "فيه ملف من دول متسجّل على تاسك تانية." }, 400) });
    await userEvent.click(await screen.findByTitle(HEADER));
    await userEvent.click(screen.getByRole("checkbox", { name: /a\.docx/ }));
    await userEvent.click(send());
    await userEvent.click(within(dialog()).getByRole("button", { name: "تمام، ابعت" }));
    expect(await within(dialog()).findByText("فيه ملف من دول متسجّل على تاسك تانية.")).toBeInTheDocument();
    await userEvent.click(within(dialog()).getByRole("button", { name: "إلغاء" }));
    expect(count()).toHaveTextContent("1");
    expect(screen.getByRole("checkbox", { name: /a\.docx/ })).toBeChecked();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("does not claim it failed when nothing came back or the server broke: the task may have gone", async () => {
    for (const answer of [() => Promise.reject(new TypeError("down")), () => jsonResponse({ ok: false, error: "server" }, 500)]) {
      const view = await open({ [HAND]: answer });
      await userEvent.click(await screen.findByTitle(HEADER));
      await userEvent.click(screen.getByRole("checkbox", { name: /a\.docx/ }));
      await userEvent.click(send());
      await userEvent.click(within(dialog()).getByRole("button", { name: "تمام، ابعت" }));
      expect(await within(dialog()).findByText(/مش متأكدين إن التاسك راحت/)).toBeInTheDocument();
      view.unmount();
    }
  });

  it("sends once however often the button is pressed, and the question cannot be closed meanwhile", async () => {
    let release: (value: Response) => void = () => undefined;
    const { calls } = await open({ [HAND]: () => new Promise<Response>((resolve) => (release = resolve)) });
    await userEvent.click(await screen.findByTitle(HEADER));
    await userEvent.click(screen.getByRole("checkbox", { name: /a\.docx/ }));
    await userEvent.click(send());
    await userEvent.click(within(dialog()).getByRole("button", { name: "تمام، ابعت" }));
    const busy = within(dialog()).getByRole("button", { name: "بيتبعت..." });
    expect(busy).toBeDisabled();
    await userEvent.click(busy);
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(posts(calls, HAND)).toHaveLength(1);
    act(() => release(handed()));
    expect(await screen.findByRole("status")).toBeInTheDocument();
  });

  it("drops a ticked file that has gone from the thread", async () => {
    let now: ThreadEntry[] = messages;
    const { client } = await open({
      "/api/v1/groups/": (url) => {
        if (url.pathname.endsWith("/handin-tasks/")) return tasks("TSK-00001")();
        if (url.pathname.endsWith("/members/")) return jsonResponse({ ok: true, members: [], can_add: false, addable: [] });
        return jsonResponse({ ok: true, client: room, messages: now });
      },
    });
    await userEvent.click(await screen.findByTitle(HEADER));
    await userEvent.click(screen.getByRole("checkbox", { name: /a\.docx/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /b\.docx/ }));
    expect(count()).toHaveTextContent("2");
    now = [mine2, theirs];
    await act(async () => {
      await client.invalidateQueries();
    });
    await waitFor(() => expect(count()).toHaveTextContent("1"));
    expect(screen.queryByRole("checkbox", { name: /a\.docx/ })).not.toBeInTheDocument();
  });

  it("and picking messages to forward do not run together: starting one ends the other", async () => {
    await open();
    await userEvent.click(await screen.findByTitle(HEADER));
    await userEvent.click(screen.getByRole("checkbox", { name: /a\.docx/ }));
    await userEvent.click(screen.getByRole("button", { name: "تحويل رسايل" }));
    expect(screen.queryByRole("toolbar", { name: "خلصت التاسك" })).not.toBeInTheDocument();
    expect(screen.getByRole("toolbar", { name: "تحويل رسايل" })).toBeInTheDocument();
    expect(boxes()).toHaveLength(0);
    // The other way round: starting to hand in ends the picking of messages, and nothing stays ticked.
    await userEvent.click(screen.getByTitle(HEADER));
    expect(screen.queryByRole("toolbar", { name: "تحويل رسايل" })).not.toBeInTheDocument();
    expect(count()).toHaveTextContent("0");
  });

  it("does not draw a button beside the files while messages are being picked", async () => {
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "تحويل رسايل" }));
    expect(document.querySelectorAll(".bub__handbtn")).toHaveLength(0);
  });
});
