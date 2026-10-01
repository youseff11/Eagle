import { afterEach, describe, expect, it, vi } from "vitest";
import { postMessage, SEND_TIMEOUT_MS } from "../api/queries";
import type { ThreadEntry } from "../api/types";
import { entry } from "../test/chat";
import { unmatched, type Outgoing } from "./outbox";

const item = (key: number, body: string, overrides: Partial<Outgoing> = {}): Outgoing => ({
  key,
  body,
  reply: null,
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
    const outcome = postMessage("CL-0001", "hello").then(
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
