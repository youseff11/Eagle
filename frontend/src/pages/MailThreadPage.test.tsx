import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { MailFile, MailLetter, MailReply, MailThreadResponse, Role } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { qk } from "../api/keys";
import { MailThreadPage } from "./MailThreadPage";

afterEach(() => vi.unstubAllGlobals());

const THREAD = "/api/v1/mail/threads/12/";

function pdf(id: number, name = "lease.pdf", over: Partial<MailFile> = {}): MailFile {
  return { id, url: `/files/${name}`, name, size: "10 KB", image: false, audio: false, length: "", ...over };
}

function letter(id: number, over: Partial<MailLetter> = {}): MailLetter {
  return {
    kind: "in",
    id,
    from: "CL-0001",
    code: "CL-0001",
    at: { ar: "2026-10-02 5:30 م", en: "2026-10-02 5:30 PM" },
    snippet: `Snippet ${id}`,
    body: `Body ${id}`,
    unseen: false,
    blocked: false,
    task: null,
    claimed_by: null,
    files: [],
    can_confirm: false,
    can_convert: false,
    documents: [],
    raw: "",
    open: false,
    ...over,
  };
}

function reply(id: number, over: Partial<MailReply> = {}): MailReply {
  return {
    kind: "out",
    id,
    by: "Nour",
    at: { ar: "2026-10-02 6:00 م", en: "2026-10-02 6:00 PM" },
    body: `Our words ${id}`,
    files: [],
    failed: false,
    error: "",
    open: false,
    ...over,
  };
}

function thread(over: Partial<MailThreadResponse["thread"]> = {}): MailThreadResponse {
  return {
    ok: true,
    thread: {
      id: 12,
      subject: "Quote for the lease",
      count: 2,
      client: "CL-0001",
      can_reply: true,
      tasks: [],
      blocked: false,
      entries: [letter(1), letter(2, { open: true })],
      ...over,
    },
  };
}

function serve(
  body: (url: URL) => Response | Promise<Response>,
  role: Role = "operation",
  extra: Record<string, (url: URL, init: RequestInit | undefined) => Response | Promise<Response>> = {},
) {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role, is_admin: role === "admin" })),
    "/api/v1/mail/threads/12/seen/": () => jsonResponse({ ok: true, marked: 1, unseen: 0 }),
    ...extra,
    [THREAD]: body,
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function Where() {
  const location = useLocation();
  return <div data-testid="where">{location.pathname + location.search}</div>;
}

function open(route = "/inbox/thread/12", lang: "ar" | "en" = "ar") {
  return renderWithProviders(
    <>
      <Where />
      <Routes>
        <Route path="/inbox" element={<div>the list</div>} />
        <Route path="/inbox/thread/:id" element={<MailThreadPage />} />
        <Route path="/tasks/new" element={<div>new task page</div>} />
        <Route path="/tasks/:code" element={<div>one task page</div>} />
        <Route path="/" element={<div>home page</div>} />
      </Routes>
    </>,
    { route, lang },
  );
}

const article = (container: HTMLElement, selector: string) => container.querySelector(selector) as HTMLElement;
const seenCalls = (calls: { url: string; init?: RequestInit }[]) => calls.filter((call) => call.url === "/api/v1/mail/threads/12/seen/");

describe("MailThreadPage", () => {
  it("shows the subject, how many letters, the client, and the tasks it is linked to", async () => {
    serve(() => jsonResponse(thread({ tasks: ["TSK-00009"] })));
    const user = userEvent.setup();
    const { container } = open();
    expect(await screen.findByRole("heading", { name: "Quote for the lease" })).toBeInTheDocument();
    expect(container.querySelector(".thread-head .badge")).toHaveTextContent("2");
    expect(within(container.querySelector(".thread-meta") as HTMLElement).getByText("CL-0001")).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "TSK-00009" }));
    expect(await screen.findByText("one task page")).toBeInTheDocument();
  });

  it("says a conversation with no subject has none", async () => {
    serve(() => jsonResponse(thread({ subject: "" })));
    open();
    expect(await screen.findByRole("heading", { name: "(من غير عنوان)" })).toBeInTheDocument();
  });

  it("starts with the newest letter open and the others folded, and a click opens or folds one", async () => {
    serve(() => jsonResponse(thread()));
    const user = userEvent.setup();
    const { container } = open();
    await screen.findByText("Body 2");
    expect(screen.queryByText("Body 1")).toBeNull();
    expect(article(container, '[data-message="2"]')).toHaveClass("is-open");
    await user.click(within(article(container, '[data-message="1"]')).getByRole("button"));
    expect(screen.getByText("Body 1")).toBeInTheDocument();
    await user.click(within(article(container, '[data-message="2"]')).getByRole("button"));
    expect(screen.queryByText("Body 2")).toBeNull();
    // A letter's first line is the preview of a folded one.
    expect(within(article(container, '[data-message="2"]')).getByText("Snippet 2")).toBeInTheDocument();
  });

  it("opens every letter at once", async () => {
    serve(() => jsonResponse(thread({ entries: [letter(1), letter(2), letter(3, { open: true })], count: 3 })));
    const user = userEvent.setup();
    open();
    await screen.findByText("Body 3");
    await user.click(screen.getByRole("button", { name: "افتح الكل" }));
    expect(screen.getByText("Body 1")).toBeInTheDocument();
    expect(screen.getByText("Body 2")).toBeInTheDocument();
  });

  it("has no expand-all for a single letter", async () => {
    serve(() => jsonResponse(thread({ count: 1, entries: [letter(1, { open: true })] })));
    open();
    await screen.findByText("Body 1");
    expect(screen.queryByRole("button", { name: "افتح الكل" })).toBeNull();
  });

  it("shows our replies between the letters, with who wrote them", async () => {
    serve(() => jsonResponse(thread({ count: 2, entries: [letter(1), reply(5, { open: true }), letter(2, { open: true })] })));
    const { container } = open();
    await screen.findByText("Our words 5");
    const ours = article(container, '[data-reply="5"]');
    expect(ours).toHaveClass("mail--ours");
    expect(within(ours).getByText("ردّنا · Nour")).toBeInTheDocument();
    expect(Array.from(container.querySelectorAll("#threadList > article")).map((one) => one.getAttribute("data-message") ?? one.getAttribute("data-reply"))).toEqual(["1", "5", "2"]);
  });

  it("keeps a reply that did not go on the page, marked, with the reason", async () => {
    serve(() =>
      jsonResponse(thread({ entries: [letter(1), reply(5, { failed: true, error: "العنوان مش بيقبل ميلات", open: true })] })),
    );
    const { container } = open();
    expect(await screen.findByText("العنوان مش بيقبل ميلات")).toBeInTheDocument();
    const ours = article(container, '[data-reply="5"]');
    expect(ours).toHaveClass("is-failed");
    expect(within(ours).getByText("متبعتش")).toBeInTheDocument();
  });

  it("says a reply with only files has only files", async () => {
    serve(() => jsonResponse(thread({ entries: [letter(1), reply(5, { body: "", files: [pdf(30, "answer.pdf")], open: false })] })));
    const { container } = open();
    await screen.findByText("(ملفات بس)");
    expect(within(article(container, '[data-reply="5"]')).getByText("1")).toBeInTheDocument();
  });

  it("marks the conversation read once, when it has shown letters that were new, and the marks stay", async () => {
    let fresh = true;
    const mocked = serve(() => jsonResponse(thread({ entries: [letter(1, { unseen: fresh }), letter(2, { open: true, unseen: fresh })] })));
    const { container, client } = open();
    await screen.findByText("Body 2");
    await waitFor(() => expect(seenCalls(mocked.calls)).toHaveLength(1));
    expect(seenCalls(mocked.calls)[0]!.init?.method).toBe("POST");
    expect(article(container, '[data-message="1"]')).toHaveClass("is-unread");
    // The next answer says they are read: they still look new to the person who has not looked away yet.
    fresh = false;
    await act(async () => {
      await client.invalidateQueries({ queryKey: qk.mailThread(12) });
    });
    expect(article(container, '[data-message="1"]')).toHaveClass("is-unread");
    expect(seenCalls(mocked.calls)).toHaveLength(1);
  });

  it("does not say anything was read when nothing was new, and a GET alone never does", async () => {
    const mocked = serve(() => jsonResponse(thread()));
    open();
    await screen.findByText("Body 2");
    expect(seenCalls(mocked.calls)).toHaveLength(0);
    expect(mocked.calls.filter((call) => call.init?.method === "POST")).toHaveLength(0);
  });

  it("opens a letter that arrives while the page is open, and leaves the others as the person left them", async () => {
    let arrived = false;
    const mocked = serve(() =>
      jsonResponse(
        arrived
          ? thread({ count: 3, entries: [letter(1), letter(2, { open: true }), letter(3, { open: true, unseen: true })] })
          : thread({ entries: [letter(1), letter(2, { open: true })] }),
      ),
    );
    const user = userEvent.setup();
    const { container, client } = open();
    await screen.findByText("Body 2");
    await user.click(within(article(container, '[data-message="2"]')).getByRole("button"));
    expect(screen.queryByText("Body 2")).toBeNull();
    arrived = true;
    await act(async () => {
      await client.invalidateQueries({ queryKey: qk.mailThread(12) });
    });
    expect(await screen.findByText("Body 3")).toBeInTheDocument();
    // The one the person folded stays folded.
    expect(screen.queryByText("Body 2")).toBeNull();
    // The new letter is said to be read once it is shown.
    await waitFor(() => expect(seenCalls(mocked.calls).length).toBeGreaterThan(0));
  });

  it("links a file to this site and does not follow an address that is not on it", async () => {
    serve(() =>
      jsonResponse(
        thread({
          count: 1,
          entries: [
            letter(1, {
              open: true,
              files: [pdf(30, "lease.pdf"), pdf(31, "bad.pdf", { url: "https://cdn.example.com/bad.pdf" }), pdf(32, "js.pdf", { url: "javascript:alert(1)" })],
            }),
          ],
        }),
      ),
    );
    open();
    const good = await screen.findByRole("link", { name: /lease\.pdf/ });
    expect(good).toHaveAttribute("href", "/files/lease.pdf");
    expect(good).toHaveAttribute("target", "_blank");
    expect(good.getAttribute("rel")).toContain("noopener");
    expect(screen.queryByRole("link", { name: /bad\.pdf/ })).toBeNull();
    expect(screen.getByText("bad.pdf")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /js\.pdf/ })).toBeNull();
  });

  it("plays a voice note with the site's own control", async () => {
    serve(() =>
      jsonResponse(thread({ count: 1, entries: [letter(1, { open: true, files: [pdf(40, "note.ogg", { audio: true, length: "0:12" })] })] })),
    );
    const { container } = open();
    await screen.findByText("Body 1");
    expect(container.querySelector(".voice")).not.toBeNull();
    expect(screen.getByText("0:12")).toBeInTheDocument();
  });

  it("shows the raw address only when the server sent it", async () => {
    serve(() => jsonResponse(thread({ count: 1, entries: [letter(1, { open: true, raw: "sender@example.com Sender" })] })), "admin");
    open();
    expect(await screen.findByText("sender@example.com Sender")).toHaveClass("mail__raw");
  });

  it("does not show an address the server did not send", async () => {
    serve(() => jsonResponse(thread({ count: 1, entries: [letter(1, { open: true })] })));
    const { container } = open();
    await screen.findByText("Body 1");
    expect(container.querySelector(".mail__raw")).toBeNull();
  });

  it("offers «استلمت» for a letter with a file the client sent, and asks before telling the client", async () => {
    const mocked = serve(
      () => jsonResponse(thread({ count: 1, entries: [letter(2, { open: true, files: [pdf(30)], documents: [30], can_confirm: true })] })),
      "operation",
      { "/api/v1/messages/2/confirm/": () => jsonResponse({ ok: true, claimed_by: "Nour" }) },
    );
    const user = userEvent.setup();
    open();
    await user.click(await screen.findByRole("button", { name: "استلمت" }));
    expect(screen.getByText("هيتبعت للعميل رد فيه كلمة confirmed. تمام؟")).toBeInTheDocument();
    // Nothing was said to the client by opening the question.
    expect(mocked.calls.filter((call) => call.url.startsWith("/api/v1/messages/"))).toHaveLength(0);
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "ابعت" }));
    await waitFor(() => expect(mocked.calls.some((call) => call.url === "/api/v1/messages/2/confirm/")).toBe(true));
    expect(mocked.calls.find((call) => call.url === "/api/v1/messages/2/confirm/")?.init?.method).toBe("POST");
    await waitFor(() => expect(screen.queryByText("هيتبعت للعميل رد فيه كلمة confirmed. تمام؟")).toBeNull());
  });

  it("can be said no to, and then nothing is sent", async () => {
    const mocked = serve(
      () => jsonResponse(thread({ count: 1, entries: [letter(2, { open: true, files: [pdf(30)], documents: [30], can_confirm: true })] })),
      "operation",
      { "/api/v1/messages/2/confirm/": () => jsonResponse({ ok: true }) },
    );
    const user = userEvent.setup();
    open();
    await user.click(await screen.findByRole("button", { name: "استلمت" }));
    await user.click(screen.getByRole("button", { name: "إلغاء" }));
    expect(mocked.calls.filter((call) => call.url.startsWith("/api/v1/messages/"))).toHaveLength(0);
  });

  it("says why «استلمت» was refused, in the server's words, and keeps the question open", async () => {
    serve(
      () => jsonResponse(thread({ count: 1, entries: [letter(2, { open: true, files: [pdf(30)], documents: [30], can_confirm: true })] })),
      "operation",
      { "/api/v1/messages/2/confirm/": () => jsonResponse({ ok: false, error: "refused", message: "الرسالة دي اتأكد استلامها قبل كده (Mona)." }, 400) },
    );
    const user = userEvent.setup();
    open();
    await user.click(await screen.findByRole("button", { name: "استلمت" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "ابعت" }));
    expect(await screen.findByText("الرسالة دي اتأكد استلامها قبل كده (Mona).")).toBeInTheDocument();
    expect(screen.getByText("هيتبعت للعميل رد فيه كلمة confirmed. تمام؟")).toBeInTheDocument();
  });

  it("does not offer «استلمت» for a letter already claimed or with nothing to confirm, and says who has it", async () => {
    serve(() =>
      jsonResponse(
        thread({
          entries: [
            letter(1, { open: true, files: [pdf(30)], documents: [30], can_confirm: true, claimed_by: "Mona" }),
            letter(2, { open: true, can_confirm: false }),
          ],
        }),
      ),
    );
    const { container } = open();
    await screen.findByText("Body 2");
    expect(screen.queryByRole("button", { name: "استلمت" })).toBeNull();
    expect(within(article(container, '[data-message="1"]')).getAllByText("Mona").length).toBeGreaterThan(0);
    expect(within(article(container, '[data-message="1"]')).getByText("استلمها")).toBeInTheDocument();
  });

  it("converts a letter to a task with the files that were ticked, and with none named when all are", async () => {
    serve(() =>
      jsonResponse(
        thread({
          count: 1,
          entries: [
            letter(7, {
              open: true,
              files: [pdf(30, "a.pdf"), pdf(31, "b.pdf"), pdf(32, "c.ogg", { audio: true, length: "0:05" })],
              documents: [30, 31],
              can_convert: true,
            }),
          ],
        }),
      ),
    );
    const user = userEvent.setup();
    open();
    const link = await screen.findByRole("link", { name: "تحويل لتاسك" });
    // Every document ticked: the file list is left out, and a voice note is never one of the files to pick.
    expect(link.getAttribute("href")).toBe("/tasks/new?message=7");
    expect(screen.queryByRole("checkbox", { name: /c\.ogg/ })).toBeNull();
    await user.click(screen.getByRole("checkbox", { name: /b\.pdf/ }));
    expect(screen.getByRole("link", { name: "تحويل لتاسك" }).getAttribute("href")).toBe("/tasks/new?message=7&files=30");
    await user.click(screen.getByRole("link", { name: "تحويل لتاسك" }));
    expect(await screen.findByText("new task page")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("/tasks/new?message=7&files=30");
  });

  it("does not offer to convert what the server did not allow (a task already, the Sales)", async () => {
    serve(() => jsonResponse(thread({ count: 1, entries: [letter(7, { open: true, files: [pdf(30)], documents: [30], can_convert: false, task: "TSK-00003" })] })));
    open();
    await screen.findByText("Body 7");
    expect(screen.queryByRole("link", { name: "تحويل لتاسك" })).toBeNull();
    expect(screen.getByText("TSK-00003")).toBeInTheDocument();
  });

  describe("replying", () => {
    function setup(extra: Record<string, (url: URL, init: RequestInit | undefined) => Response | Promise<Response>> = {}) {
      return serve(() => jsonResponse(thread()), "operation", { "/api/inbox/thread/12/reply/": () => jsonResponse({ ok: true, error: "", id: 9 }), ...extra });
    }
    const replyCalls = (calls: { url: string }[]) => calls.filter((call) => call.url === "/api/inbox/thread/12/reply/");

    it("sends the words and the files as one form, and clears the box when it went", async () => {
      const mocked = setup();
      const user = userEvent.setup();
      open();
      const box = await screen.findByRole("textbox", { name: "الرد" });
      await user.type(box, "Here is the quote");
      const file = new File(["x"], "quote.pdf", { type: "application/pdf" });
      await user.upload(screen.getByTestId("mail-reply-pick"), file);
      expect(screen.getByText("quote.pdf")).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "ابعت" }));
      await waitFor(() => expect(replyCalls(mocked.calls)).toHaveLength(1));
      const form = replyCalls(mocked.calls)[0] as unknown as { init: RequestInit };
      expect(form.init.method).toBe("POST");
      const data = form.init.body as FormData;
      expect(data.get("body")).toBe("Here is the quote");
      expect((data.getAll("files")[0] as File).name).toBe("quote.pdf");
      await waitFor(() => expect(box).toHaveValue(""));
      expect(screen.queryByText("quote.pdf")).toBeNull();
    });

    it("says who the reply goes to", async () => {
      setup();
      const { container } = open();
      await screen.findByRole("textbox", { name: "الرد" });
      const head = container.querySelector(".mail-reply__head") as HTMLElement;
      expect(head).toHaveTextContent("رد على");
      expect(within(head).getByText("CL-0001").tagName).toBe("B");
    });

    it("sends with Ctrl+Enter", async () => {
      const mocked = setup();
      const user = userEvent.setup();
      open();
      await user.type(await screen.findByRole("textbox", { name: "الرد" }), "Quick");
      await user.keyboard("{Control>}{Enter}{/Control}");
      await waitFor(() => expect(replyCalls(mocked.calls)).toHaveLength(1));
    });

    it("takes a file off before sending", async () => {
      const mocked = setup();
      const user = userEvent.setup();
      open();
      await screen.findByRole("textbox", { name: "الرد" });
      await user.upload(screen.getByTestId("mail-reply-pick"), [new File(["x"], "one.pdf"), new File(["y"], "two.pdf")]);
      await user.click(screen.getByRole("button", { name: "شيل الملف: one.pdf" }));
      await user.type(screen.getByRole("textbox", { name: "الرد" }), "Words");
      await user.click(screen.getByRole("button", { name: "ابعت" }));
      await waitFor(() => expect(replyCalls(mocked.calls)).toHaveLength(1));
      const data = (replyCalls(mocked.calls)[0] as unknown as { init: RequestInit }).init.body as FormData;
      expect((data.getAll("files") as File[]).map((one) => one.name)).toEqual(["two.pdf"]);
    });

    it("sends nothing for an empty reply and says so", async () => {
      const mocked = setup();
      const user = userEvent.setup();
      open();
      await screen.findByRole("textbox", { name: "الرد" });
      await user.click(screen.getByRole("button", { name: "ابعت" }));
      expect(screen.getByText("اكتب رد أو ارفق ملف.")).toBeInTheDocument();
      expect(replyCalls(mocked.calls)).toHaveLength(0);
    });

    it("sends nothing for files that are over what an e-mail takes, and says so", async () => {
      const mocked = setup();
      const user = userEvent.setup();
      open();
      await screen.findByRole("textbox", { name: "الرد" });
      const big = new File(["x"], "huge.pdf");
      Object.defineProperty(big, "size", { value: 26 * 1024 * 1024 });
      await user.upload(screen.getByTestId("mail-reply-pick"), big);
      await user.click(screen.getByRole("button", { name: "ابعت" }));
      expect(screen.getByText("الملفات مع بعض أكبر من 25 ميجا — الإيميل مش هيقبلها.")).toBeInTheDocument();
      expect(replyCalls(mocked.calls)).toHaveLength(0);
    });

    it("keeps what was written and says why when the send was refused", async () => {
      setup({ "/api/inbox/thread/12/reply/": () => jsonResponse({ ok: false, error: "السيرفر رفض الإيميل", id: 9 }, 400) });
      const user = userEvent.setup();
      open();
      const box = await screen.findByRole("textbox", { name: "الرد" });
      await user.type(box, "Do not lose me");
      await user.click(screen.getByRole("button", { name: "ابعت" }));
      expect(await screen.findByText("السيرفر رفض الإيميل")).toBeInTheDocument();
      expect(box).toHaveValue("Do not lose me");
    });

    it("asks the conversation again after a send: the reply is on it, failed or not", async () => {
      const mocked = setup();
      const user = userEvent.setup();
      open();
      await user.type(await screen.findByRole("textbox", { name: "الرد" }), "Hello");
      const before = mocked.calls.filter((call) => call.url === THREAD).length;
      await user.click(screen.getByRole("button", { name: "ابعت" }));
      await waitFor(() => expect(mocked.calls.filter((call) => call.url === THREAD).length).toBeGreaterThan(before));
    });

    it("has no reply box for a conversation with no client, and says why", async () => {
      serve(() => jsonResponse(thread({ client: null, can_reply: false })));
      open();
      expect(await screen.findByText("المحادثة دي مش مربوطة بعميل، فمينفعش ترد عليها من هنا.")).toBeInTheDocument();
      expect(screen.queryByRole("textbox", { name: "الرد" })).toBeNull();
      expect(screen.queryByRole("button", { name: "رد" })).toBeNull();
    });
  });

  it("goes back to the list as the person left it", async () => {
    serve(() => jsonResponse(thread()));
    const user = userEvent.setup();
    open("/inbox/thread/12?state=mine&q=lease");
    const back = await screen.findByRole("link", { name: /الميلات/ });
    expect(back.getAttribute("href")).toBe("/inbox?state=mine&q=lease");
    await user.click(back);
    expect(await screen.findByText("the list")).toBeInTheDocument();
  });

  it("goes back to the plain list when no filter came along, and drops anything else in the address", async () => {
    serve(() => jsonResponse(thread()));
    open("/inbox/thread/12?evil=1");
    expect((await screen.findByRole("link", { name: /الميلات/ })).getAttribute("href")).toBe("/inbox");
  });

  it("says a conversation that is not there, or not theirs, is not there", async () => {
    serve(() => jsonResponse({ ok: false, error: "not_found" }, 404));
    open();
    expect(await screen.findByText("المحادثة دي مش موجودة.")).toBeInTheDocument();
  });

  it("says it could not load when the server failed", async () => {
    serve(() => jsonResponse({ ok: false, error: "boom" }, 500));
    open();
    expect(await screen.findByText("حصلت مشكلة في التحميل.")).toBeInTheDocument();
  });

  it("goes to the list for an address that is not a number, without asking", async () => {
    const mocked = serve(() => jsonResponse(thread()));
    open("/inbox/thread/abc");
    expect(await screen.findByText("the list")).toBeInTheDocument();
    expect(mocked.calls.filter((call) => call.url.startsWith("/api/v1/mail/threads/"))).toHaveLength(0);
  });

  it("sends everybody the mailbox is not for home, without asking for the conversation", async () => {
    for (const role of ["translator", "team_lead", "hr", "accounting", "reviewer"] as Role[]) {
      const mocked = serve(() => jsonResponse(thread()), role);
      const { unmount } = open();
      expect(await screen.findByText("home page")).toBeInTheDocument();
      expect(mocked.calls.filter((call) => call.url.startsWith("/api/v1/mail/threads/")), role).toHaveLength(0);
      unmount();
    }
  });

  it("is in English too", async () => {
    serve(() => jsonResponse(thread()));
    open("/inbox/thread/12", "en");
    expect(await screen.findByRole("button", { name: "Expand all" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reply" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Reply" })).toBeInTheDocument();
    expect(screen.getByText("Up to 25 MB · Ctrl+Enter sends")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reply" }));
  });
});
