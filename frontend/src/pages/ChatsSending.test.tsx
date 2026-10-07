import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { qk } from "../api/keys";
import type { ThreadEntry, ThreadFile } from "../api/types";
import { forgetDrafts } from "../components/chat/Composer";
import { forgetPhotos } from "../lib/localPhotos";
import { entry, renderChats as render, row, visible } from "../test/chat";
import { jsonResponse } from "../test/helpers";

/**
 * A file that is on its way looks like the file that arrives: a photo is the photo, a recording is the player, a document
 * is its card. Before, it was a paper clip and a file name until the server answered, and then the real thing took its place.
 */

const created = vi.fn();
const revoked = vi.fn();
let made = 0;

beforeEach(() => {
  visible("visible");
  forgetDrafts();
  forgetPhotos();
  made = 0;
  created.mockReset().mockImplementation(() => `blob:preview-${(made += 1)}`);
  revoked.mockReset();
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: created, revokeObjectURL: revoked }));
});
afterEach(() => {
  forgetPhotos();
  vi.unstubAllGlobals();
  visible("visible");
});

const SEND = "/api/v1/clients/CL-0001/send/";

const attach = () => screen.getByLabelText("إرفاق ملفات") as HTMLInputElement;
const sendButton = () => screen.getByRole("button", { name: "إرسال" });
const pendingBubble = () => document.querySelector(".bub--pending") as HTMLElement | null;

const photo = (name = "holiday.png", size = 2048) => new File(["x".repeat(size)], name, { type: "image/png" });
const sound = (name = "song.mp3") => new File(["x".repeat(64)], name, { type: "audio/mpeg" });
const pdf = (name = "brief.pdf") => new File(["x".repeat(3 * 1024)], name, { type: "application/pdf" });

const fileJson = (over: Partial<ThreadFile>): ThreadFile => ({
  id: 1,
  url: "/files/out/holiday.png",
  name: "holiday.png",
  size: 2048,
  mime: "image/png",
  voice: false,
  audio: false,
  length: "",
  image: true,
  ...over,
});

const ours = (id: number, files: ThreadFile[], extra: Partial<ThreadEntry> = {}) =>
  entry(id, { uid: `out-${id}`, kind: "out", body: "", sender: "Nour", sender_id: 7, status: "sent", files, ...extra });

const answer = (messages: ThreadEntry[]) => jsonResponse({ ok: true, delivered: true, error: "", messages, client: row("CL-0001") });

async function open(extra: Parameters<typeof render>[2] = {}) {
  const view = render("/chats/CL-0001", { thread: { client: row("CL-0001"), messages: [entry(1)] } }, extra);
  await screen.findByRole("textbox", { name: "الرسالة" });
  return view;
}

async function sendFiles(...files: File[]) {
  await userEvent.upload(attach(), files);
  await userEvent.click(sendButton());
  await waitFor(() => expect(pendingBubble()).not.toBeNull());
  return pendingBubble()!;
}

describe("a message with files on its way", () => {
  it("draws a photo as the photo and not as the name of a file", async () => {
    await open({ [SEND]: () => new Promise<Response>(() => undefined) });
    const pending = await sendFiles(photo());
    const picture = pending.querySelector("img")!;
    expect(picture).toHaveAttribute("src", "blob:preview-1");
    expect(picture).toHaveAttribute("alt", "holiday.png");
    expect(pending.querySelector(".document-card")).toBeNull();
    expect(within(pending).queryByText("holiday.png")).not.toBeInTheDocument();
  });

  it("draws photos sent together as one grid, as the arrived message does", async () => {
    await open({ [SEND]: () => new Promise<Response>(() => undefined) });
    const pending = await sendFiles(photo("a.png"), photo("b.png", 4096), photo("c.png", 8192));
    const grid = pending.querySelector(".imggrid")!;
    expect(grid).toHaveAttribute("data-images", "3");
    expect([...grid.querySelectorAll("img")].map((one) => one.getAttribute("src"))).toEqual(["blob:preview-1", "blob:preview-2", "blob:preview-3"]);
  });

  it("draws a sound file as the player it will be, one that can be played while it is on its way", async () => {
    await open({ [SEND]: () => new Promise<Response>(() => undefined) });
    const pending = await sendFiles(sound());
    expect(within(pending).getByText("رسالة صوتية")).toBeInTheDocument();
    expect(within(pending).getByRole("button", { name: "تشغيل" })).toBeInTheDocument();
    expect(pending.querySelector("audio")).toHaveAttribute("src", "blob:preview-1");
  });

  it("draws a document as its card", async () => {
    await open({ [SEND]: () => new Promise<Response>(() => undefined) });
    const pending = await sendFiles(pdf());
    const card = pending.querySelector(".document-card")!;
    expect(card.querySelector(".document-card__badge--pdf")).toHaveTextContent("PDF");
    expect(card).toHaveTextContent("brief.pdf");
    expect(card).toHaveTextContent("PDF · 3 KB");
    // A card on its way is not a link: there is nothing to open yet.
    expect(card.tagName).toBe("DIV");
    expect(within(pending).queryByRole("link")).not.toBeInTheDocument();
  });

  it("keeps the order the files were chosen in, a photo between two documents", async () => {
    await open({ [SEND]: () => new Promise<Response>(() => undefined) });
    const pending = await sendFiles(pdf("first.pdf"), photo("middle.png"), pdf("last.pdf"));
    const order = [...pending.querySelectorAll(".bub__file")].map((one) => (one.querySelector("img") ? "photo" : one.textContent!.match(/first|last/)?.[0]));
    expect(order).toEqual(["first", "photo", "last"]);
  });

  it("falls back to the card for a photo it cannot draw yet (a browser with no object URLs)", async () => {
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: undefined }));
    await open({ [SEND]: () => new Promise<Response>(() => undefined) });
    const pending = await sendFiles(photo());
    expect(pending.querySelector("img")).toBeNull();
    expect(pending.querySelector(".document-card")).toHaveTextContent("holiday.png");
  });
});

describe("when it arrives", () => {
  it("shows the same picture at once, from the copy that was waiting, and not a blank while the server's loads", async () => {
    let release: (value: Response) => void = () => undefined;
    await open({ [SEND]: () => new Promise<Response>((resolve) => (release = resolve)) });
    await sendFiles(photo());
    release(answer([entry(1), ours(9, [fileJson({})])]));
    await waitFor(() => expect(pendingBubble()).toBeNull());
    const real = document.querySelector('[data-uid="out-9"]') as HTMLElement;
    expect(real.querySelector("img")).toHaveAttribute("src", "blob:preview-1");
    // Opening it, and saving it, still go to the server's address.
    expect(real.querySelector("a.bub__img")).toHaveAttribute("href", "/files/out/holiday.png");
    expect(revoked).not.toHaveBeenCalledWith("blob:preview-1");
  });

  it("does the same for the photos of a grid, found by their sizes whatever the server called them", async () => {
    let release: (value: Response) => void = () => undefined;
    await open({ [SEND]: () => new Promise<Response>((resolve) => (release = resolve)) });
    await sendFiles(photo("a.png", 2048), photo("b.png", 4096));
    release(
      answer([
        entry(1),
        // The server wrote them in another order and under other names.
        ours(9, [fileJson({ id: 2, url: "/files/out/x2.png", name: "x2.png", size: 4096 }), fileJson({ id: 1, url: "/files/out/x1.png", name: "x1.png", size: 2048 })]),
      ]),
    );
    await waitFor(() => expect(pendingBubble()).toBeNull());
    const sources = [...document.querySelectorAll('[data-uid="out-9"] .imggrid img')].map((one) => one.getAttribute("src"));
    expect(sources).toEqual(["blob:preview-2", "blob:preview-1"]);
  });

  it("does it too when the message reaches the thread by another road before the server has answered", async () => {
    let arrived = false;
    const view = await open({
      [SEND]: () => new Promise<Response>(() => undefined),
      "/api/v1/clients/CL-0001/messages/": () =>
        jsonResponse({ ok: true, client: row("CL-0001"), messages: arrived ? [entry(1), ours(9, [fileJson({})])] : [entry(1)] }),
    });
    await sendFiles(photo());
    arrived = true;
    await act(async () => {
      await view.client.invalidateQueries({ queryKey: qk.thread("CL-0001") });
    });
    await waitFor(() => expect(document.querySelector('[data-uid="out-9"]')).not.toBeNull());
    expect(pendingBubble()).toBeNull();
    expect(document.querySelector('[data-uid="out-9"] img')).toHaveAttribute("src", "blob:preview-1");
  });

  it("borrows nothing for a message that is not this one: what arrives with another size is drawn from the server", async () => {
    let release: (value: Response) => void = () => undefined;
    await open({ [SEND]: () => new Promise<Response>((resolve) => (release = resolve)) });
    await sendFiles(photo("same.png", 2048));
    // What arrives has another size: it is not this photo, so nothing is borrowed for it.
    release(answer([entry(1), ours(9, [fileJson({ size: 9999 })])]));
    await waitFor(() => expect(document.querySelector('[data-uid="out-9"]')).not.toBeNull());
    expect(document.querySelector('[data-uid="out-9"] img')).toHaveAttribute("src", "/files/out/holiday.png");
  });

  it("lets go of the copy of a document or a sound: nothing is drawn from it any more", async () => {
    let release: (value: Response) => void = () => undefined;
    await open({ [SEND]: () => new Promise<Response>((resolve) => (release = resolve)) });
    await sendFiles(sound());
    release(answer([entry(1), ours(9, [fileJson({ name: "song.mp3", url: "/files/out/song.mp3", mime: "audio/mpeg", size: 64, audio: true, image: false })])]));
    await waitFor(() => expect(pendingBubble()).toBeNull());
    expect(revoked).toHaveBeenCalledWith("blob:preview-1");
  });
});

describe("when it did not go", () => {
  it("keeps the photo on screen while the person decides, and lets it go when they give it up", async () => {
    await open({ [SEND]: () => jsonResponse({ ok: false, error: "file_too_big" }, 400) });
    await sendFiles(photo());
    expect(await screen.findByText("فيه ملف أكبر من المسموح.")).toBeInTheDocument();
    expect(pendingBubble()!.querySelector("img")).toHaveAttribute("src", "blob:preview-1");
    expect(revoked).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "امسح" }));
    expect(pendingBubble()).toBeNull();
    expect(revoked).toHaveBeenCalledWith("blob:preview-1");
  });
});
