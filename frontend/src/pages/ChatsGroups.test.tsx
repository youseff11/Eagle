import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Person } from "../api/types";
import { suggestGroupName } from "../lib/roles";
import { entry, renderChats as render, row, visible } from "../test/chat";
import { jsonResponse } from "../test/helpers";

beforeEach(() => visible("visible"));
afterEach(() => {
  vi.unstubAllGlobals();
  visible("visible");
});

type Call = { url: string; init?: RequestInit };
const posts = (calls: Call[], path: string) => calls.filter((c) => c.init?.method === "POST" && c.url === path);
const body = (call: Call) => JSON.parse(String(call.init?.body));

const person = (id: number, name: string, role: Person["role"]): Person => ({ id, name, initials: name.slice(0, 2).toUpperCase(), role });
const people = [
  person(2, "Hana", "operation"),
  person(3, "Omar", "translator"),
  person(4, "Sara", "translator"),
  person(5, "Ahmed", "team_lead"),
  person(6, "Mona", "team_lead"),
];

describe("what a new group is called", () => {
  const lead = { name: "Lee", role: "team_lead" as const };
  const ops = { name: "Nour", role: "operation" as const };

  it("is named for the translator and the leader when both are known", () => {
    expect(suggestGroupName(lead, [people[1]!, people[0]!])).toBe("مترجم: Omar · ليدر: Lee");
    expect(suggestGroupName(ops, [people[1]!, people[3]!])).toBe("مترجم: Omar · ليدر: Ahmed");
  });

  it("is not named when anything is ambiguous: two translators, two leaders, none, or no leader at all", () => {
    expect(suggestGroupName(lead, [people[1]!, people[2]!])).toBe("");
    expect(suggestGroupName(ops, [people[1]!, people[3]!, people[4]!])).toBe("");
    expect(suggestGroupName(ops, [people[3]!])).toBe("");
    expect(suggestGroupName(ops, [people[1]!])).toBe("");
    expect(suggestGroupName(lead, [])).toBe("");
  });
});

describe("opening a work group", () => {
  const groups = [row("g1", { group: true, team: true, label: "Work", room: 11 })];
  const PEOPLE = "/api/v1/people/";

  /** The create door is `/api/v1/groups/` itself; everything below it (threads, members) is somebody else's. */
  const create = (answer: (init: RequestInit | undefined) => Response | Promise<Response>) => ({
    "/api/v1/groups/": (url: URL, init: RequestInit | undefined) =>
      url.pathname === "/api/v1/groups/" && init?.method === "POST"
        ? answer(init)
        : url.pathname.endsWith("/members/")
          ? jsonResponse({ ok: true, members: [], can_add: false, addable: [] })
          : url.pathname.endsWith("/handin-tasks/")
            ? jsonResponse({ ok: true, tasks: [] })
            : jsonResponse({ ok: true, client: row("g9", { group: true, team: true, label: "New group", room: 19 }), messages: [entry(1, { uid: "g19-1", body: "A new group" })] }),
  });

  async function open(extra: Parameters<typeof render>[2] = {}, setup: Parameters<typeof render>[1] = {}) {
    const view = render("/chats?type=groups", { lists: { groups }, canCreateGroup: true, role: { role: "team_lead", short_name: "Lee" }, ...setup }, {
      [PEOPLE]: () => jsonResponse({ ok: true, people }),
      ...extra,
    });
    await screen.findByText("Work");
    return view;
  }
  const dialog = () => screen.getByRole("dialog");
  const open_ = async () => {
    await userEvent.click(screen.getByRole("button", { name: "جروب شغل" }));
    await screen.findByRole("dialog");
    await within(dialog()).findByText("Omar");
  };
  const tick = (name: string) => userEvent.click(within(dialog()).getByRole("checkbox", { name: new RegExp(name) }));

  it("has the button only in the groups list and only for somebody who may open a group", async () => {
    await open();
    expect(screen.getByRole("button", { name: "جروب شغل" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "العملاء" }));
    expect(screen.queryByRole("button", { name: "جروب شغل" })).not.toBeInTheDocument();
  });

  it("is not drawn for a role that may not, and nobody is asked for the list of people", async () => {
    const { calls } = await open({}, { canCreateGroup: false, role: { role: "translator" } });
    expect(screen.queryByRole("button", { name: "جروب شغل" })).not.toBeInTheDocument();
    expect(calls.some((c) => c.url === PEOPLE)).toBe(false);
  });

  it("asks for the people only when the dialog opens, and lists them with their roles", async () => {
    const { calls } = await open();
    expect(calls.some((c) => c.url === PEOPLE)).toBe(false);
    await open_();
    expect(calls.filter((c) => c.url === PEOPLE)).toHaveLength(1);
    const rows = within(dialog()).getAllByRole("checkbox");
    expect(rows).toHaveLength(5);
    expect(within(dialog()).getAllByText("مترجم")).toHaveLength(2);
    expect(within(dialog()).getByText("أوبريشن")).toBeInTheDocument();
    expect(within(dialog()).getAllByText("تيم ليدر")).toHaveLength(2);
    expect(screen.getByText("جروب داخلي: مفيش حاجة فيه بتوصل العميل.")).toBeInTheDocument();
  });

  it("searches by name", async () => {
    await open();
    await open_();
    await userEvent.type(within(dialog()).getByRole("searchbox"), "mo");
    expect(within(dialog()).getAllByRole("checkbox")).toHaveLength(1);
    expect(within(dialog()).getByText("Mona")).toBeInTheDocument();
    await userEvent.clear(within(dialog()).getByRole("searchbox"));
    await userEvent.type(within(dialog()).getByRole("searchbox"), "zzz");
    expect(within(dialog()).getByText("مفيش نتايج.")).toBeInTheDocument();
  });

  it("will not create before somebody is ticked", async () => {
    const { calls } = await open();
    await open_();
    expect(within(dialog()).getByRole("button", { name: "اعمل الجروب" })).toBeDisabled();
    await tick("Hana");
    expect(within(dialog()).getByRole("button", { name: "اعمل الجروب" })).toBeEnabled();
    await tick("Hana");
    expect(within(dialog()).getByRole("button", { name: "اعمل الجروب" })).toBeDisabled();
    expect(posts(calls, "/api/v1/groups/")).toHaveLength(0);
  });

  it("suggests the name as people are ticked, and stops once a name is typed", async () => {
    await open();
    await open_();
    const name = () => within(dialog()).getByLabelText("اسم الجروب") as HTMLInputElement;
    expect(name().value).toBe("");
    await tick("Omar");
    // A team leader opening it: the leader is them.
    expect(name().value).toBe("مترجم: Omar · ليدر: Lee");
    await tick("Sara");
    expect(name().value).toBe("");
    await tick("Sara");
    expect(name().value).toBe("مترجم: Omar · ليدر: Lee");
    await userEvent.type(name(), "!");
    expect(name().value).toBe("مترجم: Omar · ليدر: Lee!");
    await tick("Omar");
    expect(name().value).toBe("مترجم: Omar · ليدر: Lee!");
    // Emptying the box hands the name back to the suggestion.
    await userEvent.clear(name());
    await tick("Omar");
    expect(name().value).toBe("مترجم: Omar · ليدر: Lee");
  });

  it("creates it, posts the title and the people, and opens the new group", async () => {
    document.cookie = "csrftoken=tokG";
    const { calls } = await open(create(() => jsonResponse({ ok: true, room: 19, code: "g9" })));
    await open_();
    await tick("Ahmed");
    await tick("Hana");
    await userEvent.type(within(dialog()).getByLabelText("اسم الجروب"), "  Plan the week ");
    await userEvent.click(within(dialog()).getByRole("button", { name: "اعمل الجروب" }));

    await waitFor(() => expect(posts(calls, "/api/v1/groups/")).toHaveLength(1));
    const call = posts(calls, "/api/v1/groups/")[0]!;
    expect(body(call)).toEqual({ title: "Plan the week", members: [5, 2] });
    expect(new Headers(call.init?.headers).get("X-CSRFToken")).toBe("tokG");
    // The dialog closes and the group is on screen.
    expect(await screen.findByText("A new group")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("sends the suggested name too, so the server never has to guess it", async () => {
    const { calls } = await open(create(() => jsonResponse({ ok: true, room: 19, code: "g9" })));
    await open_();
    await tick("Omar");
    await userEvent.click(within(dialog()).getByRole("button", { name: "اعمل الجروب" }));
    await waitFor(() => expect(posts(calls, "/api/v1/groups/")).toHaveLength(1));
    expect(body(posts(calls, "/api/v1/groups/")[0]!).title).toBe("مترجم: Omar · ليدر: Lee");
  });

  it("says why in the server's words, and keeps what was ticked", async () => {
    await open(create(() => jsonResponse({ ok: false, error: "refused", message: "اكتب اسم للجروب." }, 400)));
    await open_();
    await tick("Hana");
    await userEvent.click(within(dialog()).getByRole("button", { name: "اعمل الجروب" }));
    expect(await within(dialog()).findByText("اكتب اسم للجروب.")).toBeInTheDocument();
    expect(within(dialog()).getByRole("checkbox", { name: /Hana/ })).toBeChecked();
    expect(within(dialog()).getByRole("button", { name: "اعمل الجروب" })).toBeEnabled();
  });

  it("says when it is not allowed", async () => {
    await open(create(() => jsonResponse({ ok: false, error: "forbidden" }, 403)));
    await open_();
    await tick("Hana");
    await userEvent.click(within(dialog()).getByRole("button", { name: "اعمل الجروب" }));
    expect(await within(dialog()).findByText("مالكش صلاحية تعمل جروب شغل.")).toBeInTheDocument();
  });

  it("creates once however often the button is pressed, and cannot be closed meanwhile", async () => {
    let release: (value: Response) => void = () => undefined;
    const { calls } = await open(create(() => new Promise<Response>((resolve) => (release = resolve))));
    await open_();
    await tick("Hana");
    await userEvent.click(within(dialog()).getByRole("button", { name: "اعمل الجروب" }));
    const busy = within(dialog()).getByRole("button", { name: "بيتعمل..." });
    expect(busy).toBeDisabled();
    await userEvent.click(busy);
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(posts(calls, "/api/v1/groups/")).toHaveLength(1);
    release(jsonResponse({ ok: true, room: 19, code: "g9" }));
    expect(await screen.findByText("A new group")).toBeInTheDocument();
  });

  it("closes with Escape, with Cancel and on the backdrop, and writes nothing", async () => {
    const { calls } = await open();
    await open_();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await open_();
    await userEvent.click(within(dialog()).getByRole("button", { name: "إلغاء" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(posts(calls, "/api/v1/groups/")).toHaveLength(0);
  });

  it("says so when the list of people could not be loaded", async () => {
    await open({ [PEOPLE]: () => jsonResponse({ ok: false, error: "forbidden" }, 403) });
    await userEvent.click(screen.getByRole("button", { name: "جروب شغل" }));
    expect(await within(await screen.findByRole("dialog")).findByText("مش قادرين نجيب الأسامي.")).toBeInTheDocument();
  });
});

describe("who is in a group, and adding to it", () => {
  const room = row("g1", { group: true, team: true, label: "Work", room: 11 });
  const thread = { client: room, messages: [entry(1, { uid: "g11-1", body: "hello group" })] };
  const MEMBERS = "/api/v1/groups/11/members/";
  const ADD = "/api/v1/groups/11/members/add/";
  const members = [person(7, "Nour", "operation"), person(5, "Ahmed", "team_lead"), person(3, "Omar", "translator")];
  const addable = [person(8, "Hala", "hr"), person(9, "Sami", "sales")];
  const roster = (canAdd: boolean) => () => jsonResponse({ ok: true, members, can_add: canAdd, addable: canAdd ? addable : [] });

  async function open(extra: Parameters<typeof render>[2] = {}, setup: Parameters<typeof render>[1] = {}, path = "/chats/g1") {
    // The first route that matches wins and the members' address is a prefix of the add door's: what a test adds goes first.
    const view = render(path, { thread, ...setup }, { ...extra, ...(MEMBERS in extra ? {} : { [MEMBERS]: roster(true) }) });
    await screen.findByText("hello group");
    return view;
  }
  const dialog = () => screen.getByRole("dialog");

  it("lists the members above the messages", async () => {
    await open();
    const chips = await screen.findByText("Ahmed");
    const bar = chips.closest(".cchat__members") as HTMLElement;
    expect(within(bar).getAllByText(/Nour|Ahmed|Omar/)).toHaveLength(3);
  });

  it("offers adding only when the server says this person may", async () => {
    await open({ [MEMBERS]: roster(false) });
    await screen.findByText("Ahmed");
    expect(screen.queryByRole("button", { name: "ضيف عضو" })).not.toBeInTheDocument();
  });

  it("does not ask who is in a colleague's chat, which is two people", async () => {
    const { calls } = render("/chats/u5", { thread: { client: row("u5", { staff: true, label: "Sam", room: 12 }), messages: [entry(1, { uid: "g12-1", body: "hi Sam" })] } });
    await screen.findByText("hi Sam");
    expect(calls.some((c) => c.url.includes("/members/"))).toBe(false);
    expect(screen.queryByRole("button", { name: "ضيف عضو" })).not.toBeInTheDocument();
  });

  it("adds the people who are ticked and says nothing more when all of them were added", async () => {
    document.cookie = "csrftoken=tokM";
    const { calls } = await open({ [ADD]: () => jsonResponse({ ok: true, message: "", added: ["Hala"] }) });
    await userEvent.click(await screen.findByRole("button", { name: "ضيف عضو" }));
    expect(within(dialog()).getAllByRole("checkbox")).toHaveLength(2);
    await userEvent.click(within(dialog()).getByRole("checkbox", { name: /Hala/ }));
    await userEvent.click(within(dialog()).getByRole("button", { name: "ضيف" }));
    await waitFor(() => expect(posts(calls, ADD)).toHaveLength(1));
    const call = posts(calls, ADD)[0]!;
    expect(body(call)).toEqual({ members: [8] });
    expect(new Headers(call.init?.headers).get("X-CSRFToken")).toBe("tokM");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    // Who is in the group, and what the room says about it, are asked for again.
    await waitFor(() => expect(calls.filter((c) => c.url === MEMBERS).length).toBeGreaterThan(1));
    document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("says who was left out when only some were added", async () => {
    await open({ [ADD]: () => jsonResponse({ ok: true, message: "مش ينفع تضيف Sami — التاسك دي مش من حقهم.", added: ["Hala"] }) });
    await userEvent.click(await screen.findByRole("button", { name: "ضيف عضو" }));
    await userEvent.click(within(dialog()).getByRole("checkbox", { name: /Hala/ }));
    await userEvent.click(within(dialog()).getByRole("checkbox", { name: /Sami/ }));
    await userEvent.click(within(dialog()).getByRole("button", { name: "ضيف" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("مش ينفع تضيف Sami");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("says why in the server's words when nobody could be added, and keeps the dialog", async () => {
    await open({ [ADD]: () => jsonResponse({ ok: false, error: "refused", message: "دول في الجروب أصلاً." }, 400) });
    await userEvent.click(await screen.findByRole("button", { name: "ضيف عضو" }));
    await userEvent.click(within(dialog()).getByRole("checkbox", { name: /Hala/ }));
    await userEvent.click(within(dialog()).getByRole("button", { name: "ضيف" }));
    expect(await within(dialog()).findByText("دول في الجروب أصلاً.")).toBeInTheDocument();
    expect(within(dialog()).getByRole("checkbox", { name: /Hala/ })).toBeChecked();
  });

  it("will not add before somebody is ticked, and adds once however often the button is pressed", async () => {
    let release: (value: Response) => void = () => undefined;
    const { calls } = await open({ [ADD]: () => new Promise<Response>((resolve) => (release = resolve)) });
    await userEvent.click(await screen.findByRole("button", { name: "ضيف عضو" }));
    expect(within(dialog()).getByRole("button", { name: "ضيف" })).toBeDisabled();
    await userEvent.click(within(dialog()).getByRole("checkbox", { name: /Hala/ }));
    await userEvent.click(within(dialog()).getByRole("button", { name: "ضيف" }));
    const busy = within(dialog()).getByRole("button", { name: "بيتضاف..." });
    await userEvent.click(busy);
    expect(posts(calls, ADD)).toHaveLength(1);
    release(jsonResponse({ ok: true, message: "", added: ["Hala"] }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("tells whoever adds to a room that reaches a client that the person can then write to them", async () => {
    await open(
      {},
      { thread: { client: row("g1", { group: true, reaches_client: true, label: "With Acme", room: 11 }), messages: [entry(1, { uid: "g11-1", body: "hello group" })] } },
    );
    await userEvent.click(await screen.findByRole("button", { name: "ضيف عضو" }));
    expect(within(dialog()).getByText(/هيقدر يكتب للعميل على واتساب/)).toBeInTheDocument();
  });

  it("has no such warning for a work group", async () => {
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "ضيف عضو" }));
    expect(within(dialog()).queryByText(/هيقدر يكتب للعميل/)).not.toBeInTheDocument();
  });

  it("says when there is nobody left to add", async () => {
    await open({ [MEMBERS]: () => jsonResponse({ ok: true, members, can_add: true, addable: [] }) });
    await userEvent.click(await screen.findByRole("button", { name: "ضيف عضو" }));
    expect(within(dialog()).getByText("مفيش حد يتضاف.")).toBeInTheDocument();
    expect(within(dialog()).getByRole("button", { name: "ضيف" })).toBeDisabled();
  });
});
