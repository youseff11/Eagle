import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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
const sends = (calls: Call[]) => calls.filter((c) => c.init?.method === "POST" && c.url.endsWith("/send/"));
const sentForm = (call: Call) => call.init?.body as FormData;
const askedTasks = (calls: Call[]) => calls.filter((c) => c.url.includes("/file-tasks/"));

/** A file of `size` bytes. */
const fileOf = (name: string, size = 10, type = "application/pdf") => new File(["x".repeat(size)], name, { type });

const ours = (id: number, body: string, files: string[] = [], extra: Partial<ThreadEntry> = {}) =>
  entry(id, {
    uid: `out-${id}`,
    kind: "out",
    body,
    sender: "Nour",
    sender_id: 7,
    status: "sent",
    files: files.map((name, index) => ({
      id: index + 1,
      url: `/files/out/${name}`,
      name,
      size: 10,
      mime: "application/pdf",
      voice: false,
      audio: false,
      length: "",
      image: false,
    })),
    ...extra,
  });

/** The same message with every file of the size given (the files built by `ours` are all 10 bytes). */
const ofSize = (message: ThreadEntry, size: number): ThreadEntry => ({
  ...message,
  files: message.files.map((file) => ({ ...file, size })),
});

const answer = (messages: ThreadEntry[], code = "CL-0001") =>
  jsonResponse({ ok: true, delivered: true, error: "", messages, client: row(code) });

const box = () => screen.getByRole("textbox", { name: "الرسالة" });
const sendButton = () => screen.getByRole("button", { name: "إرسال" });
const attach = () => screen.getByLabelText("إرفاق ملفات") as HTMLInputElement;
const chips = () => Array.from(document.querySelectorAll(".cchat__files .chip"));

async function openClient(extra: Parameters<typeof render>[2] = {}, options: Parameters<typeof render>[3] = {}) {
  const view = render("/chats/CL-0001", { thread: { client: row("CL-0001"), messages: [entry(1)] } }, extra, options);
  await screen.findByRole("textbox", { name: "الرسالة" });
  return view;
}

async function openStaff(extra: Parameters<typeof render>[2] = {}) {
  const view = render(
    "/chats/u5",
    { thread: { client: row("u5", { staff: true, room: 9, channel: "", window_open: false }), messages: [entry(1, { uid: "g9-1" })] } },
    extra,
  );
  await screen.findByRole("textbox", { name: "الرسالة" });
  return view;
}

const tasksAnswer = (...codes: string[]) =>
  jsonResponse({ ok: true, tasks: codes.map((code) => ({ code, title: `Title of ${code}` })) });

describe("attaching", () => {
  it("shows each file as a chip with its size, and a chip can be taken off", async () => {
    await openClient();
    await userEvent.upload(attach(), [fileOf("brief.pdf", 2048), fileOf("photo.png", 5 * 1024 * 1024, "image/png")]);
    expect(chips()).toHaveLength(2);
    expect(chips()[0]).toHaveTextContent("brief.pdf");
    expect(chips()[0]).toHaveTextContent("2 KB");
    expect(chips()[1]).toHaveTextContent("5 MB");
    await userEvent.click(screen.getByRole("button", { name: "شيل brief.pdf" }));
    expect(chips()).toHaveLength(1);
    expect(chips()[0]).toHaveTextContent("photo.png");
  });

  it("lets the same file be chosen again after it was taken off", async () => {
    await openClient();
    const file = fileOf("again.pdf");
    await userEvent.upload(attach(), file);
    await userEvent.click(screen.getByRole("button", { name: "شيل again.pdf" }));
    expect(chips()).toHaveLength(0);
    await userEvent.upload(attach(), file);
    expect(chips()).toHaveLength(1);
  });

  it("adds to what is attached instead of replacing it", async () => {
    await openClient();
    await userEvent.upload(attach(), fileOf("one.pdf"));
    await userEvent.upload(attach(), fileOf("two.pdf"));
    expect(chips().map((chip) => chip.textContent)).toEqual([expect.stringContaining("one.pdf"), expect.stringContaining("two.pdf")]);
  });

  it("can send files alone, with no words", async () => {
    await openClient();
    expect(sendButton()).toBeDisabled();
    await userEvent.upload(attach(), fileOf("only.pdf"));
    expect(sendButton()).toBeEnabled();
  });

  it("turns the clip off while the 24-hour window is closed", async () => {
    render("/chats/CL-0001", { thread: { client: row("CL-0001", { window_open: false }), messages: [entry(1)] } });
    await screen.findByRole("textbox", { name: "الرسالة" });
    expect(attach()).toBeDisabled();
  });

  it("keeps what was attached and not sent while the person looks at another conversation", async () => {
    const first = await openClient();
    await userEvent.upload(attach(), fileOf("kept.pdf"));
    first.unmount();
    await openClient();
    expect(chips()).toHaveLength(1);
    expect(chips()[0]).toHaveTextContent("kept.pdf");
  });
});

describe("sending files", () => {
  it("sends the words and the files in one multipart request, with the token and no content type of its own", async () => {
    document.cookie = "csrftoken=tok456";
    const { calls } = await openClient({ [SEND]: () => answer([entry(1), ours(9, "the brief", ["brief.pdf", "photo.png"])]) });
    await userEvent.upload(attach(), [fileOf("brief.pdf"), fileOf("photo.png", 10, "image/png")]);
    await userEvent.type(box(), "the brief{Enter}");
    await screen.findByText("photo.png");
    const [call] = sends(calls);
    const form = sentForm(call!);
    expect(form).toBeInstanceOf(FormData);
    expect(form.get("body")).toBe("the brief");
    expect((form.getAll("files") as File[]).map((file) => file.name)).toEqual(["brief.pdf", "photo.png"]);
    expect(form.has("reply_uid")).toBe(false);
    // A client conversation has no task to name.
    expect(form.has("task")).toBe(false);
    const headers = new Headers(call!.init?.headers);
    expect(headers.get("X-CSRFToken")).toBe("tok456");
    // The browser writes it, with the boundary: one set by hand would have no boundary and the server could not read it.
    expect(headers.has("Content-Type")).toBe(false);
    document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("sends files alone as a message with empty words, and answers to a reply with the one it quotes", async () => {
    const { calls } = await openClient({ [SEND]: () => answer([entry(1), ours(9, "", ["only.pdf"])]) });
    await userEvent.click(screen.getByRole("button", { name: "رد" }));
    await userEvent.upload(attach(), fileOf("only.pdf"));
    await userEvent.click(sendButton());
    await waitFor(() => expect(sends(calls)).toHaveLength(1));
    const form = sentForm(sends(calls)[0]!);
    expect(form.get("body")).toBe("");
    expect(form.get("reply_uid")).toBe("in-1");
    expect((form.getAll("files") as File[]).map((file) => file.name)).toEqual(["only.pdf"]);
  });

  it("shows the files in the message that is on its way, and the box is empty and the chips gone at once", async () => {
    let release: (value: Response) => void = () => undefined;
    await openClient({ [SEND]: () => new Promise<Response>((resolve) => (release = resolve)) });
    await userEvent.upload(attach(), fileOf("slow.pdf", 3 * 1024));
    await userEvent.type(box(), "with a file{Enter}");
    const pending = (await screen.findByText("with a file")).closest(".bub") as HTMLElement;
    expect(pending).toHaveClass("bub--pending");
    // The card the arrived file will have: its badge, its name, its type and its size.
    expect(within(pending).getByText("slow.pdf")).toBeInTheDocument();
    expect(within(pending).getByText("PDF · 3 KB")).toBeInTheDocument();
    expect(pending.querySelector(".document-card")).not.toBeNull();
    expect(chips()).toHaveLength(0);
    release(answer([entry(1), ours(9, "with a file", ["slow.pdf"])]));
    await waitFor(() => expect(document.querySelectorAll(".bub--pending")).toHaveLength(0));
    expect(document.querySelector('[data-uid="out-9"]')).not.toBeNull();
    expect(screen.getAllByText("slow.pdf")).toHaveLength(1);
  });

  it("is not sent twice by pressing Send again while the files are on their way", async () => {
    const { calls } = await openClient({ [SEND]: () => new Promise<Response>(() => undefined) });
    await userEvent.upload(attach(), fileOf("big.pdf"));
    await userEvent.click(sendButton());
    await screen.findByText("بيتبعت...");
    await userEvent.upload(attach(), fileOf("next.pdf"));
    expect(sendButton()).toBeDisabled();
    expect(sends(calls)).toHaveLength(1);
  });
});

describe("how many and how big", () => {
  const limits = (files: { count: number; bytes: number; total_bytes: number }) => ({
    "/api/v1/me/": () => jsonResponse({ ...me({ role: "operation" }), limits: { ...me().limits, files } }),
  });

  it("will not send more files than allowed, and says so until some are taken off", async () => {
    const { calls } = await openClient();
    await userEvent.upload(attach(), Array.from({ length: 11 }, (_, i) => fileOf(`f${i}.pdf`)));
    expect(screen.getByRole("alert")).toHaveTextContent("الحد الأقصى 10 ملفات");
    expect(sendButton()).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "شيل f10.pdf" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(sendButton()).toBeEnabled();
    expect(sends(calls)).toHaveLength(0);
  });

  it("will not send a file bigger than the server takes", async () => {
    await openClient(limits({ count: 10, bytes: 10 * 1024 * 1024, total_bytes: 40 * 1024 * 1024 }));
    await userEvent.upload(attach(), fileOf("huge.pdf", 11 * 1024 * 1024));
    expect(await screen.findByText(/فيه ملف أكبر من 10 ميجا/)).toBeInTheDocument();
    expect(sendButton()).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "شيل huge.pdf" }));
    expect(sendButton()).toBeDisabled();
    await userEvent.upload(attach(), fileOf("fine.pdf"));
    expect(sendButton()).toBeEnabled();
  });

  it("will not send files that are too big together", async () => {
    await openClient(limits({ count: 10, bytes: 10 * 1024, total_bytes: 15 * 1024 }));
    await userEvent.upload(attach(), [fileOf("a.pdf", 9 * 1024), fileOf("b.pdf", 9 * 1024)]);
    expect(await screen.findByText(/الملفات مع بعض أكبر من/)).toBeInTheDocument();
    expect(sendButton()).toBeDisabled();
  });

  it("says why when the server refuses the files, and keeps them to try again", async () => {
    let answerWith: () => Response = () => jsonResponse({ ok: false, error: "file_too_big" }, 400);
    const { calls } = await openClient({ [SEND]: () => answerWith() });
    await userEvent.upload(attach(), fileOf("refused.pdf"));
    await userEvent.click(sendButton());
    expect(await screen.findByText("فيه ملف أكبر من المسموح.")).toBeInTheDocument();
    answerWith = () => answer([entry(1), ours(9, "", ["refused.pdf"])]);
    await userEvent.click(screen.getByRole("button", { name: "حاول تاني" }));
    await waitFor(() => expect(sends(calls)).toHaveLength(2));
    // The same file went again: it was held, not lost.
    expect((sentForm(sends(calls)[1]!).getAll("files") as File[]).map((file) => file.name)).toEqual(["refused.pdf"]);
    await waitFor(() => expect(document.querySelectorAll(".bub--pending")).toHaveLength(0));
  });
});

describe("which task the files are for", () => {
  it("asks nothing until there are files, and nothing at all for a client or a client group", async () => {
    const staff = await openStaff({ "/api/v1/staff/5/file-tasks/": () => tasksAnswer("TSK-1", "TSK-2") });
    expect(askedTasks(staff.calls)).toHaveLength(0);
    await userEvent.upload(attach(), fileOf("a.pdf"));
    await waitFor(() => expect(askedTasks(staff.calls)).toHaveLength(1));
    expect(askedTasks(staff.calls)[0]!.url).toBe("/api/v1/staff/5/file-tasks/");
    staff.unmount();

    const client = await openClient();
    await userEvent.upload(attach(), fileOf("b.pdf"));
    expect(screen.queryByLabelText("التاسك")).not.toBeInTheDocument();
    expect(askedTasks(client.calls)).toHaveLength(0);
    client.unmount();

    const group = render("/chats/g1", { thread: { client: row("g1", { group: true, reaches_client: true }), messages: [entry(1)] } });
    await screen.findByRole("textbox", { name: "الرسالة" });
    await userEvent.upload(attach(), fileOf("c.pdf"));
    expect(screen.queryByLabelText("التاسك")).not.toBeInTheDocument();
    expect(askedTasks(group.calls)).toHaveLength(0);
  });

  it("makes the person choose when there are several, and sends the one chosen", async () => {
    const { calls } = await openStaff({
      "/api/v1/staff/5/file-tasks/": () => tasksAnswer("TSK-00001", "TSK-00002"),
      "/api/v1/staff/5/send/": () => answer([entry(1, { uid: "g9-1" })], "u5"),
    });
    await userEvent.upload(attach(), fileOf("work.docx"));
    const select = await screen.findByLabelText("التاسك");
    expect(sendButton()).toBeDisabled();
    expect(select.closest(".cchat__filetask")).toHaveClass("is-missing");
    await userEvent.selectOptions(select, "TSK-00002");
    expect(sendButton()).toBeEnabled();
    expect(select.closest(".cchat__filetask")).not.toHaveClass("is-missing");
    await userEvent.click(sendButton());
    await waitFor(() => expect(sends(calls)).toHaveLength(1));
    expect(sentForm(sends(calls)[0]!).get("task")).toBe("TSK-00002");
  });

  it("lets the files be said not to be for a task", async () => {
    const { calls } = await openStaff({
      "/api/v1/staff/5/file-tasks/": () => tasksAnswer("TSK-00001", "TSK-00002"),
      "/api/v1/staff/5/send/": () => answer([entry(1, { uid: "g9-1" })], "u5"),
    });
    await userEvent.upload(attach(), fileOf("notes.txt"));
    await userEvent.selectOptions(await screen.findByLabelText("التاسك"), "none");
    await userEvent.click(sendButton());
    await waitFor(() => expect(sends(calls)).toHaveLength(1));
    expect(sentForm(sends(calls)[0]!).get("task")).toBe("none");
  });

  it("takes the only task without asking, and still lets the person say it is not for it", async () => {
    const { calls } = await openStaff({
      "/api/v1/staff/5/file-tasks/": () => tasksAnswer("TSK-00007"),
      "/api/v1/staff/5/send/": () => answer([entry(1, { uid: "g9-1" })], "u5"),
    });
    await userEvent.upload(attach(), fileOf("one.docx"));
    const select = (await screen.findByLabelText("التاسك")) as HTMLSelectElement;
    expect(select.value).toBe("TSK-00007");
    expect(sendButton()).toBeEnabled();
    await userEvent.click(sendButton());
    await waitFor(() => expect(sends(calls)).toHaveLength(1));
    expect(sentForm(sends(calls)[0]!).get("task")).toBe("TSK-00007");
  });

  it("shows no picker and names no task when there is none to choose", async () => {
    const { calls } = await openStaff({
      "/api/v1/staff/5/file-tasks/": () => tasksAnswer(),
      "/api/v1/staff/5/send/": () => answer([entry(1, { uid: "g9-1" })], "u5"),
    });
    await userEvent.upload(attach(), fileOf("free.txt"));
    await waitFor(() => expect(askedTasks(calls)).toHaveLength(1));
    expect(screen.queryByLabelText("التاسك")).not.toBeInTheDocument();
    await userEvent.click(sendButton());
    await waitFor(() => expect(sends(calls)).toHaveLength(1));
    expect(sentForm(sends(calls)[0]!).has("task")).toBe(false);
  });

  it("waits for the list of tasks before it lets the files go", async () => {
    let release: (value: Response) => void = () => undefined;
    await openStaff({ "/api/v1/staff/5/file-tasks/": () => new Promise<Response>((resolve) => (release = resolve)) });
    await userEvent.upload(attach(), fileOf("wait.docx"));
    expect(sendButton()).toBeDisabled();
    release(tasksAnswer("TSK-00001", "TSK-00002"));
    await screen.findByLabelText("التاسك");
    expect(sendButton()).toBeDisabled();
  });

  it("asks a work group at its own address", async () => {
    const { calls } = render(
      "/chats/g2",
      { thread: { client: row("g2", { group: true, team: true, channel: "" }), messages: [entry(1, { uid: "g2-1" })] } },
      { "/api/v1/groups/2/file-tasks/": () => tasksAnswer("TSK-00001", "TSK-00002") },
    );
    await screen.findByRole("textbox", { name: "الرسالة" });
    await userEvent.upload(attach(), fileOf("team.docx"));
    await screen.findByLabelText("التاسك");
    expect(askedTasks(calls)[0]!.url).toBe("/api/v1/groups/2/file-tasks/");
  });

  it("says so when the tasks could not be loaded, and leaves the decision to the server", async () => {
    const { calls } = await openStaff({
      "/api/v1/staff/5/file-tasks/": () => jsonResponse({ ok: false, error: "server" }, 500),
      "/api/v1/staff/5/send/": () => answer([entry(1, { uid: "g9-1" })], "u5"),
    });
    await userEvent.upload(attach(), fileOf("blind.docx"));
    expect(await screen.findByText(/مش قادرين نجيب التاسكات/)).toBeInTheDocument();
    await userEvent.click(sendButton());
    await waitFor(() => expect(sends(calls)).toHaveLength(1));
  });

  it("says what to do when the server asks for a task the picker did not know about", async () => {
    await openStaff({
      "/api/v1/staff/5/file-tasks/": () => tasksAnswer(),
      "/api/v1/staff/5/send/": () => jsonResponse({ ok: false, error: "pick_task", choices: [{ code: "TSK-1", title: "x" }] }, 400),
    });
    await userEvent.upload(attach(), fileOf("late.docx"));
    await userEvent.click(sendButton());
    expect(await screen.findByText(/حدد الملفات تبع أنهي تاسك/)).toBeInTheDocument();
  });
});

describe("when nothing comes back for a message with files", () => {
  it("looks at the thread and finds the message there by its files", async () => {
    let arrived = false;
    await openClient({
      [SEND]: () => Promise.reject(new TypeError("Failed to fetch")),
      "/api/v1/clients/CL-0001/messages/": () =>
        jsonResponse({ ok: true, client: row("CL-0001"), messages: arrived ? [entry(1), ours(9, "see", ["brief.pdf"])] : [entry(1)] }),
    });
    arrived = true;
    await userEvent.upload(attach(), fileOf("brief.pdf"));
    await userEvent.type(box(), "see{Enter}");
    await waitFor(() => expect(document.querySelector('[data-uid="out-9"]')).not.toBeNull());
    await waitFor(() => expect(document.querySelectorAll(".bub--pending")).toHaveLength(0));
    expect(screen.queryByText(/مش متأكدين/)).not.toBeInTheDocument();
  });

  it("is not fooled by a message with the same words and files of other sizes", async () => {
    await openClient({
      [SEND]: () => Promise.reject(new TypeError("Failed to fetch")),
      "/api/v1/clients/CL-0001/messages/": () =>
        jsonResponse({ ok: true, client: row("CL-0001"), messages: [entry(1), ofSize(ours(9, "see", ["other.pdf"]), 99)] }),
    });
    await userEvent.upload(attach(), fileOf("brief.pdf"));
    await userEvent.type(box(), "see{Enter}");
    expect(await screen.findByText(/مش متأكدين/)).toBeInTheDocument();
    expect(document.querySelectorAll(".bub--pending")).toHaveLength(1);
  });

  it("knows its message although the server wrote the file under another name", async () => {
    let arrived = false;
    await openClient({
      [SEND]: () => Promise.reject(new TypeError("Failed to fetch")),
      "/api/v1/clients/CL-0001/messages/": () =>
        jsonResponse({
          ok: true,
          client: row("CL-0001"),
          messages: arrived ? [entry(1), ours(9, "see", ["R\u00ae.pdf"])] : [entry(1)],
        }),
    });
    arrived = true;
    await userEvent.upload(attach(), fileOf("R&reg;.pdf"));
    await userEvent.type(box(), "see{Enter}");
    await waitFor(() => expect(document.querySelector('[data-uid="out-9"]')).not.toBeNull());
    await waitFor(() => expect(document.querySelectorAll(".bub--pending")).toHaveLength(0));
    expect(screen.queryByText(/مش متأكدين/)).not.toBeInTheDocument();
  });

  it("is not fooled by files alone when the thread has only a words-only message", async () => {
    await openClient({
      [SEND]: () => Promise.reject(new TypeError("Failed to fetch")),
      "/api/v1/clients/CL-0001/messages/": () =>
        jsonResponse({ ok: true, client: row("CL-0001"), messages: [entry(1), ours(9, "")] }),
    });
    await userEvent.upload(attach(), fileOf("brief.pdf"));
    await userEvent.click(sendButton());
    expect(await screen.findByText(/مش متأكدين/)).toBeInTheDocument();
  });
});

describe("the box", () => {
  it("takes no height of its own while it is empty, and grows only when there are words", async () => {
    await openClient();
    expect(box().style.height).toBe("");
    await userEvent.type(box(), "a");
    expect(box().style.height).not.toBe("");
    await userEvent.clear(box());
    expect(box().style.height).toBe("");
  });
});
