import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import { qk } from "../api/keys";
import { readPath, threadPath } from "../api/queries";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { jsonResponse } from "../test/helpers";
import { entry, renderChats as render, row, visible, file } from "../test/chat";
import { newestShown } from "../components/chat/Conversation";
import { kindOfCode } from "./ChatsPage";

beforeEach(() => visible("visible"));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  visible("visible");
});

describe("codes", () => {
  it("tells which list a conversation belongs to", () => {
    expect(kindOfCode("g12")).toBe("groups");
    expect(kindOfCode("u5")).toBe("staff");
    expect(kindOfCode("CL-0001")).toBe("clients");
  });

  it("builds the address of a thread only from a code it recognises", () => {
    expect(threadPath("g12")).toBe("/api/v1/groups/12/messages/");
    expect(threadPath("u5")).toBe("/api/v1/staff/5/messages/");
    expect(threadPath("CL-0001")).toBe("/api/v1/clients/CL-0001/messages/");
    for (const bad of ["../etc", "CL 0001", "a/b", "", "x".repeat(41), "g12/../x"]) {
      expect(threadPath(bad), bad).toBeNull();
    }
  });

  it("says where to mark a conversation read, and nowhere for a colleague nobody has written to", () => {
    expect(readPath("g12", undefined)).toBe("/api/v1/groups/12/read/");
    expect(readPath("CL-0001", undefined)).toBe("/api/v1/clients/CL-0001/read/");
    expect(readPath("u5", 9)).toBe("/api/v1/groups/9/read/");
    expect(readPath("u5", 0)).toBeNull();
    expect(readPath("../x", 0)).toBeNull();
  });
});

describe("the lists", () => {
  it("has the tabs this role has: a translator has no client tab", async () => {
    render("/chats", { types: ["groups", "staff"], lists: { groups: [row("g1", { group: true, label: "Work", team: true })] } });
    expect(await screen.findByRole("tab", { name: "الجروبات" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "الزمايل" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "العملاء" })).not.toBeInTheDocument();
    expect(await screen.findByText("Work")).toBeInTheDocument();
  });

  it("lists a client by its code, with the last words, the time in Arabic and the unread count", async () => {
    render("/chats", { lists: { clients: [row("CL-0001", { unread: 3, text: "hello there" })] } });
    expect(await screen.findByText("CL-0001")).toBeInTheDocument();
    expect(screen.getByText("hello there")).toBeInTheDocument();
    expect(screen.getByText("8:05 PM")).toBeInTheDocument();
    expect(screen.getByTitle("رسايل مااتقرتش")).toHaveTextContent("3");
  });

  it("speaks English with the server's own English time", async () => {
    render("/chats", { lists: { clients: [row("CL-0001")] } }, {}, { lang: "en" });
    await screen.findByText("CL-0001");
    expect(screen.getByText("8:05 PM")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Clients" })).toBeInTheDocument();
  });

  it("says 99+ for a long queue and nothing for none", async () => {
    render("/chats", { lists: { clients: [row("CL-0001", { unread: 250 }), row("CL-0002", { unread: 0 })] } });
    await screen.findByText("CL-0002");
    expect(screen.getByTitle("رسايل مااتقرتش")).toHaveTextContent("99+");
    expect(screen.getAllByTitle("رسايل مااتقرتش")).toHaveLength(1);
  });

  it("tags a group that reaches the client, and shows the ticks on our own last message", async () => {
    render("/chats?type=groups", {
      lists: {
        groups: [row("g7", { group: true, reaches_client: true, label: "With client", outgoing: true, receipt: "read" })],
      },
    });
    expect(await screen.findByText("مع العميل")).toBeInTheDocument();
    expect(document.querySelector(".cthread .tick--read")).not.toBeNull();
  });

  it("switches list when a tab is chosen", async () => {
    const { calls } = render("/chats", { lists: { groups: [row("g1", { group: true, label: "Work", team: true })] } });
    await screen.findByRole("tab", { name: "الجروبات" });
    await userEvent.click(screen.getByRole("tab", { name: "الجروبات" }));
    expect(await screen.findByText("Work")).toBeInTheDocument();
    expect(calls.some((c) => c.url.includes("type=groups"))).toBe(true);
  });

  it("asks for a search only once the typing has settled", async () => {
    const { calls } = render("/chats", { lists: { clients: [row("CL-0001")] } });
    await screen.findByText("CL-0001");
    const box = screen.getByRole("searchbox");
    await userEvent.type(box, "CL-00");
    await waitFor(() => expect(calls.some((c) => c.url.includes("q=CL-00"))).toBe(true));
    // Not a request per key: nothing with a half-typed word.
    expect(calls.some((c) => c.url.includes("q=C&") || c.url.endsWith("q=C"))).toBe(false);
  });

  it("says so when there is nothing", async () => {
    render("/chats", { lists: { clients: [] } });
    expect(await screen.findByText("مفيش محادثات لسه.")).toBeInTheDocument();
  });

  it("says so when the list cannot be loaded", async () => {
    const { calls } = render("/chats", {}, { "/api/v1/chats/": () => jsonResponse({ ok: false, error: "server" }, 500) });
    expect(await screen.findByText("حصلت مشكلة في التحميل.")).toBeInTheDocument();
    expect(calls.length).toBeGreaterThan(0);
  });
});

describe("a conversation", () => {
  it("opens a client's from its code and shows who and on which channel", async () => {
    const { calls } = render("/chats/CL-0001", {
      lists: { clients: [row("CL-0001")] },
      thread: { client: row("CL-0001"), messages: [entry(1)] },
    });
    expect(await screen.findByText("message 1")).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/v1/clients/CL-0001/messages/")).toBe(true);
    expect(screen.getAllByText("WhatsApp").length).toBeGreaterThan(0);
  });

  it("opens a group by its room and a colleague by their id", async () => {
    const group = render("/chats/g12", { thread: { client: row("g12", { group: true, label: "A group" }), messages: [entry(1)] } });
    await screen.findByText("message 1");
    expect(group.calls.some((c) => c.url === "/api/v1/groups/12/messages/")).toBe(true);
    group.unmount();
    const staff = render("/chats/u5", { thread: { client: row("u5", { staff: true, initials: "MS", label: "Mona" }), messages: [entry(1)] } });
    await screen.findByText("message 1");
    expect(staff.calls.some((c) => c.url === "/api/v1/staff/5/messages/")).toBe(true);
  });

  it("puts the two call buttons on a chat with a colleague and on no other", async () => {
    const group = render("/chats/g12", { thread: { client: row("g12", { group: true, label: "A group" }), messages: [entry(1)] } });
    await screen.findByText("message 1");
    expect(screen.queryByRole("button", { name: "مكالمة صوتية" })).toBeNull();
    group.unmount();
    const client = render("/chats/CL-0001", { thread: { client: row("CL-0001"), messages: [entry(1)] } });
    await screen.findByText("message 1");
    expect(screen.queryByRole("button", { name: "مكالمة فيديو" })).toBeNull();
    client.unmount();
    render("/chats/u5", { thread: { client: row("u5", { staff: true, initials: "MS", label: "Mona" }), messages: [entry(1)] } });
    await screen.findByText("message 1");
    expect(screen.getByRole("button", { name: "مكالمة صوتية" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "مكالمة فيديو" })).toBeInTheDocument();
  });

  it("draws the text, the quote, the subject and the forwarded tag, and ours on the other side", async () => {
    render("/chats/CL-0001", {
      thread: {
        client: row("CL-0001"),
        messages: [
          entry(1, { subject: "Quote please", quote: "the older words", quote_who: "العميل", forwarded: true }),
          entry(2, { kind: "out", uid: "out-2", body: "our answer", mine: true, status: "sent", receipt: "delivered", sender: "Nour" }),
        ],
      },
    });
    expect(await screen.findByText("message 1")).toBeInTheDocument();
    expect(screen.getByText("Quote please")).toBeInTheDocument();
    expect(screen.getByText("the older words")).toBeInTheDocument();
    expect(screen.getByText("محوّلة")).toBeInTheDocument();
    const ours = document.querySelector('[data-uid="out-2"]') as HTMLElement;
    expect(ours).toHaveClass("bub--out");
    expect(within(ours).getByText("Nour")).toBeInTheDocument();
    expect(ours.querySelector(".tick")).not.toBeNull();
    expect(document.querySelector('[data-uid="in-1"]')).toHaveClass("bub--in");
  });

  // A work group or a colleague's chat is drawn as WhatsApp draws one: what this person wrote on their side, what the others wrote
  // on the other. The server calls every colleague's message `out` (only a client's words are `in`), so `mine` decides there.
  it.each([
    ["a colleague's chat", "u5", row("u5", { staff: true, initials: "MS", label: "Mona" })],
    ["a work group", "g12", row("g12", { group: true, team: true, label: "Work" })],
  ])("puts only my own words on my side in %s, and the others on the other", async (_name, code, header) => {
    render(`/chats/${code}`, {
      thread: {
        client: header,
        messages: [
          entry(1, { kind: "out", uid: "mine-1", body: "from me", mine: true, status: "sent", sender: "Nour" }),
          entry(2, { kind: "out", uid: "theirs-2", body: "from Mona", mine: false, sender: "Mona" }),
          entry(3, { kind: "in", uid: "client-3", body: "from the client", mine: false, sender: "" }),
        ],
      },
    });
    await screen.findByText("from me");
    expect(document.querySelector('[data-uid="mine-1"]')).toHaveClass("bub--out");
    expect(document.querySelector('[data-uid="theirs-2"]')).toHaveClass("bub--in");
    expect(document.querySelector('[data-uid="client-3"]')).toHaveClass("bub--in");
    // Nobody else's message carries the marks of mine.
    expect(document.querySelector('[data-uid="theirs-2"] .tick')).toBeNull();
  });

  it("keeps every message of ours on our side in a client's conversation, whichever colleague wrote it", async () => {
    render("/chats/CL-0001", {
      thread: {
        client: row("CL-0001"),
        messages: [
          entry(1, { kind: "out", uid: "mine-1", body: "from me", mine: true, status: "sent", sender: "Nour" }),
          entry(2, { kind: "out", uid: "colleague-2", body: "from a colleague", mine: false, status: "sent", sender: "Mona" }),
          entry(3),
        ],
      },
    });
    await screen.findByText("from me");
    expect(document.querySelector('[data-uid="mine-1"]')).toHaveClass("bub--out");
    expect(document.querySelector('[data-uid="colleague-2"]')).toHaveClass("bub--out");
    expect(document.querySelector('[data-uid="in-3"]')).toHaveClass("bub--in");
  });

  it("lays a conversation out left to right in both languages, with the words inside keeping the language's direction", () => {
    // WhatsApp's sides (ours on the right) in Arabic too: a row laid out by the page's direction put ours on the left of an Arabic page.
    const css = readFileSync(resolve(import.meta.dirname, "../styles.css"), "utf-8");
    expect(css).toMatch(/\.bub\s*\{\s*direction:\s*ltr;\s*\}/);
    expect(css).toMatch(/\[dir="rtl"\]\s+\.bub__box\s*\{\s*direction:\s*rtl;\s*\}/);
  });

  it("tags technical support in the list and in the header of their chat, and a colleague stays a colleague", async () => {
    render("/chats?type=staff", {
      lists: { staff: [row("u9", { staff: true, role: "support", label: "Sami Support" }), row("u5", { staff: true, role: "operation", label: "Mona" })] },
      types: ["groups", "staff"],
    });
    const support = (await screen.findByText("Sami Support")).closest(".cthread") as HTMLElement;
    expect(within(support).getByText("دعم فني")).toBeInTheDocument();
    const colleague = screen.getByText("Mona").closest(".cthread") as HTMLElement;
    expect(within(colleague).queryByText("دعم فني")).toBeNull();
  });

  it("says in the header of the chat that it is technical support", async () => {
    render("/chats/u9", { thread: { client: row("u9", { staff: true, role: "support", label: "Sami Support", initials: "SS" }), messages: [entry(1)] } });
    await screen.findByText("message 1");
    expect(screen.getAllByText("دعم فني").length).toBeGreaterThan(0);
    expect(screen.queryByText("زميل")).toBeNull();
  });

  it("shows the date once for each day and the time in Arabic", async () => {
    render("/chats/CL-0001", {
      thread: {
        client: row("CL-0001"),
        messages: [entry(1, { date: "2026-10-01" }), entry(2, { date: "2026-10-01", time: "9:30 PM" }), entry(3, { date: "2026-10-02" })],
      },
    });
    await screen.findByText("message 3");
    expect(screen.getAllByText("2026-10-01")).toHaveLength(1);
    expect(screen.getAllByText("2026-10-02")).toHaveLength(1);
    expect(screen.getByText("9:30 PM")).toBeInTheDocument();
  });

  it("shows a photo as a photo, a voice note with a player and a document as a link", async () => {
    render("/chats/CL-0001", {
      thread: {
        client: row("CL-0001"),
        messages: [
          entry(1, {
            files: [
              file({ id: 1, name: "photo.jpg", url: "/files/in/photo.jpg", image: true }),
              file({ id: 2, name: "note.ogg", url: "/files/in/note.ogg", audio: true, voice: true, length: "0:12" }),
              file({ id: 3, name: "doc.pdf", url: "/files/in/doc.pdf" }),
            ],
          }),
        ],
      },
    });
    await screen.findByText("message 1");
    expect(screen.getByAltText("photo.jpg")).toHaveAttribute("src", "/files/in/photo.jpg");
    expect(screen.getByText("رسالة صوتية")).toBeInTheDocument();
    expect(screen.getByText("0:12")).toBeInTheDocument();
    expect(document.querySelector("audio")).toHaveAttribute("src", "/files/in/note.ogg");
    expect(screen.getByRole("link", { name: "doc.pdf" })).toHaveAttribute("href", "/files/in/doc.pdf");
  });

  it("draws a file link only for an address on this site", async () => {
    render("/chats/CL-0001", {
      thread: {
        client: row("CL-0001"),
        messages: [
          entry(1, {
            files: [
              file({ id: 1, name: "evil.pdf", url: "https://evil.example/x.pdf" }),
              file({ id: 2, name: "js.pdf", url: "javascript:alert(1)" }),
              file({ id: 3, name: "pic.jpg", url: "//evil.example/p.jpg", image: true }),
              file({ id: 4, name: "snd.ogg", url: "https://evil.example/s.ogg", audio: true }),
            ],
          }),
        ],
      },
    });
    await screen.findByText("message 1");
    expect(screen.getByText("evil.pdf")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "evil.pdf" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "js.pdf" })).not.toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("audio")).toBeNull();
    for (const link of document.querySelectorAll(".cchat__stream a")) {
      expect(link.getAttribute("href")).not.toMatch(/evil|javascript/);
    }
  });

  it("draws the words of a message as text, never as markup", async () => {
    render("/chats/CL-0001", {
      thread: { client: row("CL-0001"), messages: [entry(1, { body: "<img src=x onerror=alert(1)><b>bold</b>" })] },
    });
    expect(await screen.findByText("<img src=x onerror=alert(1)><b>bold</b>")).toBeInTheDocument();
    expect(document.querySelector(".cchat__stream img")).toBeNull();
    expect(document.querySelector(".cchat__stream b")).toBeNull();
  });

  it("shows a failed send with its reason, and the reactions", async () => {
    render("/chats/CL-0001", {
      thread: {
        client: row("CL-0001"),
        messages: [
          entry(1, {
            kind: "out",
            uid: "out-1",
            mine: true,
            status: "failed",
            error: "Meta refused it",
            reactions: [{ kind: "like", count: 2, mine: true, who: ["Nour", "Mona"] }],
          }),
        ],
      },
    });
    expect(await screen.findByText("Meta refused it")).toBeInTheDocument();
    expect(document.querySelector('[data-uid="out-1"]')).toHaveClass("bub--failed");
    expect(document.querySelector(".bub__reacts")).toHaveTextContent("2");
    expect(document.querySelector(".bub__reacts use")).toHaveAttribute("href", "#r-like");
  });

  it("does not draw a reaction it does not know", async () => {
    render("/chats/CL-0001", {
      thread: {
        client: row("CL-0001"),
        messages: [entry(1, { reactions: [{ kind: 'x"><script>', count: 1, mine: false, who: [] }] })],
      },
    });
    await screen.findByText("message 1");
    expect(document.querySelector(".bub__reacts use")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
  });

  it("warns that a group reaches the client, says a work group is internal, and the 24-hour rule", async () => {
    const reaching = render("/chats/g1", {
      thread: { client: row("g1", { group: true, reaches_client: true, label: "With client", window_open: false }), messages: [] },
    });
    expect(await screen.findByText("الجروب ده بيوصل العميل")).toBeInTheDocument();
    expect(screen.getByText("نافذة الـ24 ساعة قفلت")).toBeInTheDocument();
    reaching.unmount();

    const internal = render("/chats/g2", { thread: { client: row("g2", { group: true, team: true, channel: "", label: "Work" }), messages: [] } });
    expect(await screen.findByText("جروب شغل داخلي")).toBeInTheDocument();
    expect(screen.queryByText("نافذة الـ24 ساعة قفلت")).not.toBeInTheDocument();
    internal.unmount();

    render("/chats/CL-0003", { thread: { client: row("CL-0003", { window_open: true }), messages: [] } });
    await screen.findByText("مفيش رسايل لسه.");
    expect(screen.queryByText("نافذة الـ24 ساعة قفلت")).not.toBeInTheDocument();
  });

  it("does not talk of the 24-hour window for an e-mail conversation", async () => {
    render("/chats/CL-0004", { thread: { client: row("CL-0004", { channel: "email", window_open: false }), messages: [] } });
    await screen.findByText("مفيش رسايل لسه.");
    expect(screen.queryByText("نافذة الـ24 ساعة قفلت")).not.toBeInTheDocument();
  });

  it("does not talk of the 24-hour window for a group whose client is last heard from by e-mail", async () => {
    render("/chats/g3", {
      thread: { client: row("g3", { group: true, reaches_client: true, channel: "email", window_open: false }), messages: [] },
    });
    expect(await screen.findByText("الجروب ده بيوصل العميل")).toBeInTheDocument();
    expect(screen.queryByText("نافذة الـ24 ساعة قفلت")).not.toBeInTheDocument();
  });

  it("says it is not available when the server refuses, and when it fails", async () => {
    const refused = render("/chats/CL-0001", { thread: jsonResponse({ ok: false, error: "forbidden" }, 403) });
    expect(await screen.findByText("المحادثة دي مش متاحة ليك.")).toBeInTheDocument();
    refused.unmount();
    render("/chats/CL-0002", { thread: jsonResponse({ ok: false, error: "server" }, 500) });
    expect(await screen.findByText("حصلت مشكلة في التحميل.")).toBeInTheDocument();
  });

});

describe("what 'read' is about", () => {
  const uids = (...list: [string, "in" | "out"][]) => list.map(([uid, kind], index) => entry(index + 1, { uid, kind }));

  it("is the newest message the screen shows: a client's own, from the uid", () => {
    const thread = uids(["in-4", "in"], ["out-9", "out"], ["in-7", "in"], ["out-30", "out"]);
    // Our own messages live in another table with ids of their own: they never count.
    expect(newestShown("CL-0001", thread)).toBe(7);
  });

  it("is, in a group or a chat with a colleague, the newest of all the messages", () => {
    const thread = uids(["g3-4", "out"], ["g3-12", "in"], ["g3-9", "out"]);
    expect(newestShown("g3", thread)).toBe(12);
    expect(newestShown("u5", uids(["g8-2", "out"]))).toBe(2);
  });

  it("is nothing for an empty thread or an uid it cannot read", () => {
    expect(newestShown("CL-0001", [])).toBe(0);
    expect(newestShown("g3", uids(["g3-x", "in"]))).toBe(0);
  });
});

describe("reading", () => {
  const posts = (calls: { url: string; init?: RequestInit }[]) =>
    calls.filter((c) => c.init?.method === "POST").map((c) => c.url);
  const bodies = (calls: { url: string; init?: RequestInit }[]) =>
    calls.filter((c) => c.init?.method === "POST").map((c) => JSON.parse(String(c.init?.body)));

  it("names the newest message it showed, so a later one is not marked read", async () => {
    const { calls } = render(
      "/chats/CL-0001",
      {
        thread: {
          client: row("CL-0001"),
          messages: [entry(5, { uid: "in-5" }), entry(6, { uid: "out-3", kind: "out", mine: true }), entry(7, { uid: "in-9" })],
        },
      },
      { "/api/v1/clients/CL-0001/read/": () => jsonResponse({ ok: true, moved: true }) },
    );
    await screen.findByText("message 7");
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(bodies(calls)).toEqual([{ upto: 9 }]);
  });

  it("names the newest message of a group by its own id", async () => {
    const { calls } = render(
      "/chats/g12",
      { thread: { client: row("g12", { group: true }), messages: [entry(1, { uid: "g12-40" }), entry(2, { uid: "g12-41" })] } },
      { "/api/v1/groups/12/read/": () => jsonResponse({ ok: true, moved: true }) },
    );
    await screen.findByText("message 2");
    await waitFor(() => expect(bodies(calls)).toEqual([{ upto: 41 }]));
  });

  it("says nothing for an empty conversation: there is nothing to have read", async () => {
    const { calls } = render("/chats/CL-0001", { thread: { client: row("CL-0001"), messages: [] } });
    await screen.findByText("مفيش رسايل لسه.");
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(posts(calls)).toEqual([]);
  });

  it("waits for a fresh look: what the cache held when the page opened is not what is on screen", async () => {
    // Opened a minute ago, left, and now opened again: the cache has the old thread, the client has
    // written since, and the server is slow to answer.
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 } } });
    client.setQueryData(qk.thread("CL-0001"), { ok: true, client: row("CL-0001"), messages: [entry(1, { uid: "in-1" })] });
    let release: (answer: Response) => void = () => undefined;
    const { calls } = render(
      "/chats/CL-0001",
      {},
      {
        "/api/v1/clients/CL-0001/messages/": () => new Promise<Response>((resolve) => (release = resolve)),
        "/api/v1/clients/CL-0001/read/": () => jsonResponse({ ok: true, moved: true }),
      },
      { client },
    );
    // The old messages are on screen at once, but nothing is marked read from them.
    expect(await screen.findByText("message 1")).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 80));
    expect(posts(calls)).toEqual([]);

    // The fresh answer arrives with a newer message: only now, and up to the newest shown.
    release(jsonResponse({ ok: true, client: row("CL-0001"), messages: [entry(1, { uid: "in-1" }), entry(2, { uid: "in-2", body: "URGENT" })] }));
    expect(await screen.findByText("URGENT")).toBeInTheDocument();
    await waitFor(() => expect(bodies(calls)).toEqual([{ upto: 2 }]));
  });

  it("asks the server again every time a conversation is opened, whatever the cache holds", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 60_000 } } });
    client.setQueryData(qk.thread("CL-0001"), { ok: true, client: row("CL-0001"), messages: [entry(1)] });
    const { calls } = render("/chats/CL-0001", { thread: { client: row("CL-0001"), messages: [entry(1)] } }, {}, { client });
    await screen.findByText("message 1");
    await waitFor(() => expect(calls.some((c) => c.url === "/api/v1/clients/CL-0001/messages/")).toBe(true));
  });

  it("asks nothing, and says so, for a code it does not know", async () => {
    const { calls } = render("/chats/bad%20code", {});
    expect(await screen.findByText("المحادثة دي مش متاحة ليك.")).toBeInTheDocument();
    // Not left on "loading" for ever: the room says it is not available (the list beside it may still load).
    expect(document.querySelector(".cchat__room")).not.toHaveTextContent("بيحمّل...");
    expect(calls.some((c) => c.url.includes("bad"))).toBe(false);
  });

  it("asks nothing for a conversation of a list this role does not have: a translator and a client", async () => {
    const { calls } = render("/chats/CL-0001", { types: ["groups", "staff"] });
    expect(await screen.findByText("المحادثة دي مش متاحة ليك.")).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 50));
    // Not a refused request at every refresh, each one written to the audit log.
    expect(calls.filter((c) => c.url.startsWith("/api/v1/clients/"))).toEqual([]);
  });

  it("says the conversation was read, once, when it is open with the tab in front", async () => {
    const { calls } = render(
      "/chats/CL-0001",
      { thread: { client: row("CL-0001"), messages: [entry(1)] } },
      { "/api/v1/clients/CL-0001/read/": () => jsonResponse({ ok: true, moved: true }) },
    );
    await screen.findByText("message 1");
    await waitFor(() => expect(posts(calls)).toEqual(["/api/v1/clients/CL-0001/read/"]));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(posts(calls)).toHaveLength(1);
    expect(bodies(calls)).toEqual([{ upto: 1 }]);
  });

  it("says nothing while the tab is not in front, and does it when the tab comes back", async () => {
    visible("hidden");
    const { calls } = render(
      "/chats/g12",
      { thread: { client: row("g12", { group: true }), messages: [entry(1)] } },
      { "/api/v1/groups/12/read/": () => jsonResponse({ ok: true, moved: false }) },
    );
    await screen.findByText("message 1");
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(posts(calls)).toEqual([]);
    visible("visible");
    document.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() => expect(posts(calls)).toEqual(["/api/v1/groups/12/read/"]));
  });

  it("marks a colleague's chat through its room, and has nothing to mark when there is no room yet", async () => {
    const withRoom = render(
      "/chats/u5",
      { thread: { client: row("u5", { staff: true, room: 9 }), messages: [entry(1)] } },
      { "/api/v1/groups/9/read/": () => jsonResponse({ ok: true, moved: true }) },
    );
    await screen.findByText("message 1");
    await waitFor(() => expect(posts(withRoom.calls)).toEqual(["/api/v1/groups/9/read/"]));
    withRoom.unmount();

    const without = render("/chats/u6", { thread: { client: row("u6", { staff: true, room: 0 }), messages: [] } });
    await screen.findByText("مفيش رسايل لسه.");
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(posts(without.calls)).toEqual([]);
  });

  it("marks nothing for a conversation that could not be opened", async () => {
    const { calls } = render("/chats/CL-0001", { thread: jsonResponse({ ok: false, error: "forbidden" }, 403) });
    await screen.findByText("المحادثة دي مش متاحة ليك.");
    expect(posts(calls)).toEqual([]);
  });

  it("asks again, and marks again, when a newer message arrives", async () => {
    let messages = [entry(1)];
    const { calls, client } = render(
      "/chats/CL-0001",
      {},
      {
        "/api/v1/clients/CL-0001/messages/": () => jsonResponse({ ok: true, client: row("CL-0001"), messages }),
        "/api/v1/clients/CL-0001/read/": () => jsonResponse({ ok: true, moved: true }),
      },
    );
    await screen.findByText("message 1");
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    messages = [entry(1), entry(2)];
    await client.invalidateQueries({ queryKey: ["chats"] });
    await screen.findByText("message 2");
    await waitFor(() => expect(posts(calls)).toHaveLength(2));
  });
});
