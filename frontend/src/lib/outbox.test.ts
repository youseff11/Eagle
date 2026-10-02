import { afterEach, describe, expect, it, vi } from "vitest";
import { postMessage, SEND_TIMEOUT_FILES_MS, SEND_TIMEOUT_MS } from "../api/queries";
import type { ThreadEntry } from "../api/types";
import { entry } from "../test/chat";
import { unmatched, type Outgoing } from "./outbox";

const item = (key: number, body: string, overrides: Partial<Outgoing> = {}): Outgoing => ({
  key,
  body,
  reply: null,
  files: [],
  task: "",
  voice: null,
  before: [],
  state: "sending",
  error: "",
  ...overrides,
});

const ours = (id: number, body: string, overrides: Partial<ThreadEntry> = {}) =>
  entry(id, { uid: `out-${id}`, kind: "out", body, sender: "Nour", sender_id: 7, ...overrides });

describe("what has already arrived", () => {
  it("takes off the queue a message of ours with the same words that was not there before", () => {
    expect(unmatched([item(1, "hello")], [ours(5, "hello")], 7)).toEqual([]);
  });

  it("keeps what is not in the thread, and what is in it only as somebody else's", () => {
    expect(unmatched([item(1, "hello")], [], 7)).toHaveLength(1);
    expect(unmatched([item(1, "hello")], [entry(5, { body: "hello" })], 7)).toHaveLength(1);
    expect(unmatched([item(1, "hello")], [ours(5, "hello", { sender: "Mona", sender_id: 8 })], 7)).toHaveLength(1);
    expect(unmatched([item(1, "hello")], [ours(5, "other words")], 7)).toHaveLength(1);
  });

  it("never mistakes a message that was in the thread before for the one that was sent", () => {
    expect(unmatched([item(1, "hello", { before: ["out-5"] })], [ours(5, "hello")], 7)).toHaveLength(1);
  });

  it("knows a group's own message by `mine`, and a client's thread's by who wrote it - by id, not by name", () => {
    expect(unmatched([item(1, "hi")], [ours(5, "hi", { sender: "", sender_id: 0, mine: true })], 7)).toEqual([]);
    expect(unmatched([item(1, "hi")], [ours(5, "hi", { sender_id: 7, mine: false })], 7)).toEqual([]);
    // A colleague of the same name is somebody else: the same words from them are not ours.
    expect(unmatched([item(1, "hi")], [ours(5, "hi", { sender: "Nour", sender_id: 99, mine: false })], 7)).toHaveLength(1);
    // Without an id to go by, only `mine` counts.
    expect(unmatched([item(1, "hi")], [ours(5, "hi", { sender_id: 0, mine: false })], 0)).toHaveLength(1);
  });

  it("ignores the spaces around the words, as the server does", () => {
    expect(unmatched([item(1, "  hello ")], [ours(5, "hello")], 7)).toEqual([]);
  });

  it("matches each message in the thread with one in the queue: two identical lines are two", () => {
    const queue = [item(1, "ok"), item(2, "ok")];
    expect(unmatched(queue, [ours(5, "ok")], 7).map((i) => i.key)).toEqual([2]);
    expect(unmatched(queue, [ours(5, "ok"), ours(6, "ok")], 7)).toEqual([]);
  });

  it("never counts a refused message as arrived: nothing of it was written", () => {
    expect(unmatched([item(1, "hello", { state: "refused", error: "forbidden" })], [ours(5, "hello")], 7)).toHaveLength(1);
  });

  it("counts one that is not sure about itself", () => {
    expect(unmatched([item(1, "hello", { state: "unsure" })], [ours(5, "hello")], 7)).toEqual([]);
  });
});

describe("what has already arrived, for a message with files", () => {
  // A file of `size` bytes, named by the person; and an entry carrying files of those sizes, named by the server.
  const file = (name: string, size: number) => new File(["x".repeat(size)], name);
  const withFiles = (id: number, body: string, sizes: number[]) =>
    ours(id, body, {
      files: sizes.map((size, index) => ({
        id: index + 1, url: `/files/f${index}`, name: `stored-${index}`, size, mime: "", voice: false, audio: false, length: "", image: false,
      })),
    });

  it("is the message that carries as many files of the same sizes, in any order", () => {
    const queued = item(1, "see", { files: [file("a.pdf", 5), file("b.png", 9)] });
    expect(unmatched([queued], [withFiles(5, "see", [9, 5])], 7)).toEqual([]);
  });

  it("does not need the name to be the one that was sent: the server rewrites a name", () => {
    const queued = item(1, "see", { files: [file("R&reg;.pdf", 5)] });
    expect(unmatched([queued], [withFiles(5, "see", [5])], 7)).toEqual([]);
  });

  it("is not a message with other sizes, fewer files, more files, or none", () => {
    const queued = item(1, "see", { files: [file("a.pdf", 5), file("b.png", 9)] });
    for (const sizes of [[5, 8], [5], [5, 9, 3], []]) {
      expect(unmatched([queued], [withFiles(5, "see", sizes)], 7), sizes.join()).toHaveLength(1);
    }
  });

  it("is not a message with the same files and other words", () => {
    expect(unmatched([item(1, "see", { files: [file("a.pdf", 5)] })], [withFiles(5, "look", [5])], 7)).toHaveLength(1);
  });

  it("is, for words alone, only a message with no files", () => {
    expect(unmatched([item(1, "hi")], [withFiles(5, "hi", [5])], 7)).toHaveLength(1);
  });

  it("is files alone: empty words and the same sizes", () => {
    expect(unmatched([item(1, "", { files: [file("a.pdf", 5)] })], [withFiles(5, "", [5])], 7)).toEqual([]);
  });
});

describe("what has already arrived, for a voice note", () => {
  const recorded = { blob: new Blob(["sound"]), seconds: 4, extension: ".webm" };
  const queued = () => item(1, "", { voice: recorded });
  const audioFile = (voice: boolean, name = "voice.ogg") => ({
    id: 1, url: `/files/${name}`, name, size: 999, mime: "audio/ogg", voice, audio: true, length: "0:04", image: false,
  });
  const document = { id: 2, url: "/files/x.pdf", name: "x.pdf", size: 5, mime: "application/pdf", voice: false, audio: false, length: "", image: false };

  it("is a message of ours with one voice note in it, whatever size the server made of it", () => {
    expect(unmatched([queued()], [ours(5, "", { files: [audioFile(true)] })], 7)).toEqual([]);
    // A room's file has no `voice` column: it is a voice note by being audio.
    expect(unmatched([queued()], [ours(5, "", { files: [audioFile(false)] })], 7)).toEqual([]);
  });

  it("is not a message with a voice note and something else, with nothing, or with a file that is not sound", () => {
    expect(unmatched([queued()], [ours(5, "", { files: [audioFile(true), document] })], 7)).toHaveLength(1);
    expect(unmatched([queued()], [ours(5, "", { files: [audioFile(true), audioFile(true, "two.ogg")] })], 7)).toHaveLength(1);
    expect(unmatched([queued()], [ours(5, "", { files: [] })], 7)).toHaveLength(1);
    expect(unmatched([queued()], [ours(5, "", { files: [document] })], 7)).toHaveLength(1);
  });

  it("is not a voice note somebody else sent, or one with other words", () => {
    expect(unmatched([queued()], [ours(5, "", { files: [audioFile(true)], sender_id: 99 })], 7)).toHaveLength(1);
    expect(unmatched([queued()], [ours(5, "other words", { files: [audioFile(true)] })], 7)).toHaveLength(1);
    expect(unmatched([item(1, "listen", { voice: recorded })], [ours(5, "listen", { files: [audioFile(true)] })], 7)).toEqual([]);
  });

  it("is the note of the length that was recorded, where the thread says how long it is", () => {
    // Recorded for 4 seconds: a client's thread says "0:04", and another audio message of ours is not this one.
    expect(unmatched([queued()], [ours(5, "", { files: [{ ...audioFile(true), length: "0:04" }] })], 7)).toEqual([]);
    expect(unmatched([queued()], [ours(5, "", { files: [{ ...audioFile(true), length: "0:09" }] })], 7)).toHaveLength(1);
    expect(unmatched([queued()], [ours(5, "", { files: [{ ...audioFile(true), length: "" }] })], 7)).toEqual([]);
  });

  it("is not a plain message of ours with an audio file attached, which is files and not a note", () => {
    const attached = item(1, "", { files: [new File(["x".repeat(999)], "song.mp3")] });
    expect(unmatched([attached], [ours(5, "", { files: [audioFile(false, "song.mp3")] })], 7)).toEqual([]);
  });
});

describe("the request a message with files makes", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  function capture() {
    const calls: { path: string; init?: RequestInit }[] = [];
    vi.stubGlobal("fetch", async (path: string, init?: RequestInit) => {
      calls.push({ path, init });
      return new Response(JSON.stringify({ ok: true, delivered: true, error: "", messages: [], client: {} }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    return calls;
  }

  it("is a form of urlencoded words when there is nothing to upload", async () => {
    const calls = capture();
    await postMessage("g3", { body: "hello", replyUid: "g3-4" });
    expect(calls[0]!.path).toBe("/api/v1/groups/3/send/");
    expect(String(calls[0]!.init?.body)).toBe("body=hello&reply_uid=g3-4");
  });

  it("is multipart with the words, the quote, the task and each file by its name", async () => {
    const calls = capture();
    await postMessage("u5", {
      body: "see",
      replyUid: "g9-2",
      task: "TSK-00001",
      files: [new File(["1"], "a.pdf"), new File(["2"], "b.png")],
    });
    const form = calls[0]!.init?.body as FormData;
    expect(calls[0]!.path).toBe("/api/v1/staff/5/send/");
    expect([form.get("body"), form.get("reply_uid"), form.get("task")]).toEqual(["see", "g9-2", "TSK-00001"]);
    expect((form.getAll("files") as File[]).map((f) => f.name)).toEqual(["a.pdf", "b.png"]);
  });

  it("leaves out the quote and the task when there are none", async () => {
    const calls = capture();
    await postMessage("CL-0001", { body: "", files: [new File(["1"], "a.pdf")] });
    const form = calls[0]!.init?.body as FormData;
    expect(form.has("reply_uid")).toBe(false);
    expect(form.has("task")).toBe(false);
    expect(form.get("body")).toBe("");
  });

  it("waits longer for an upload than for words before it gives up", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      (_path: string, init?: RequestInit) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        }),
    );
    const words = postMessage("CL-0001", { body: "hi" }).then(() => "answered", (e: unknown) => (e as Error).name);
    const upload = postMessage("CL-0001", { body: "", files: [new File(["1"], "a.pdf")] }).then(
      () => "answered",
      (e: unknown) => (e as Error).name,
    );
    await vi.advanceTimersByTimeAsync(SEND_TIMEOUT_MS + 1);
    await expect(words).resolves.toBe("AbortError");
    let uploadSettled = false;
    void upload.then(() => (uploadSettled = true));
    await Promise.resolve();
    expect(uploadSettled).toBe(false);
    await vi.advanceTimersByTimeAsync(SEND_TIMEOUT_FILES_MS - SEND_TIMEOUT_MS);
    await expect(upload).resolves.toBe("AbortError");
  });
});

describe("a send that is neither answered nor refused", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("is cut off after the time limit, so it can be 'not sure' instead of waiting for ever", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      (_url: string, init?: RequestInit) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        }),
    );
    const outcome = postMessage("CL-0001", { body: "hello" }).then(
      () => "answered",
      (error: unknown) => (error instanceof DOMException ? error.name : "other"),
    );
    await vi.advanceTimersByTimeAsync(SEND_TIMEOUT_MS - 1);
    let settled = false;
    void outcome.then(() => (settled = true));
    await Promise.resolve();
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(2);
    await expect(outcome).resolves.toBe("AbortError");
  });
});
