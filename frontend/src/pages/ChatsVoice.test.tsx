import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import type { ThreadEntry } from "../api/types";
import { forgetDrafts } from "../components/chat/Composer";
import { RecorderError, startRecording, type Recording } from "../lib/recorder";
import { entry, renderChats as render, row, visible } from "../test/chat";
import { jsonResponse, me } from "../test/helpers";

vi.mock("../lib/recorder", async (original) => ({
  ...(await original<typeof import("../lib/recorder")>()),
  startRecording: vi.fn(),
}));

const starting = vi.mocked(startRecording);

type FakeTake = Recording & { stop: Mock<Recording["stop"]>; cancel: Mock<Recording["cancel"]> };

function take(size = 5, extension = ".webm"): FakeTake {
  return {
    stop: vi.fn<Recording["stop"]>(async () => ({ blob: new Blob(["x".repeat(size)], { type: "audio/webm" }), extension })),
    cancel: vi.fn<Recording["cancel"]>(),
  };
}

const created = vi.fn();
const revoked = vi.fn();

beforeEach(() => {
  visible("visible");
  forgetDrafts();
  starting.mockReset();
  created.mockReset().mockReturnValue("blob:the-take");
  revoked.mockReset();
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: created, revokeObjectURL: revoked }));
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  visible("visible");
});

const SEND = "/api/v1/clients/CL-0001/send/";

type Call = { url: string; init?: RequestInit };
const sends = (calls: Call[]) => calls.filter((c) => c.init?.method === "POST" && c.url.endsWith("/send/"));
const formOf = (call: Call) => call.init?.body as FormData;

/** A voice note of ours as the server writes it: a client's thread says `voice`, a room's only that it is audio. */
const noteOf = (id: number, body = "", extra: Partial<ThreadEntry> = {}, voice = true): ThreadEntry =>
  entry(id, {
    uid: `out-${id}`,
    kind: "out",
    body,
    sender: "Nour",
    sender_id: 7,
    status: "sent",
    files: [
      { id: 1, url: "/files/out/voice.ogg", name: "voice.ogg", size: 1234, mime: "audio/ogg", voice, audio: true, length: "0:01", image: false },
    ],
    ...extra,
  });

const answer = (messages: ThreadEntry[], code = "CL-0001") =>
  jsonResponse({ ok: true, delivered: true, error: "", messages, client: row(code) });

const box = () => screen.getByRole("textbox", { name: "الرسالة" });
const mic = () => screen.getByRole("button", { name: "سجّل رسالة صوتية" });
const bar = () => screen.getByRole("group", { name: "رسالة صوتية" });

async function open(extra: Parameters<typeof render>[2] = {}, setup: Parameters<typeof render>[1] = {}) {
  const view = render("/chats/CL-0001", { thread: { client: row("CL-0001"), messages: [entry(1)] }, ...setup }, extra);
  await screen.findByRole("textbox", { name: "الرسالة" });
  return view;
}

/** Record and stop: a take waits to be sent. */
async function recordTake(recording = take()) {
  starting.mockResolvedValueOnce(recording);
  await userEvent.click(mic());
  await screen.findByText("بسجّل...");
  await userEvent.click(within(bar()).getByRole("button", { name: "وقّف" }));
  await screen.findByText("اسمعها قبل ما تبعتها");
  return recording;
}

describe("recording", () => {
  it("shows the red dot and the clock while it records, and the microphone button is off meanwhile", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    await open();
    starting.mockResolvedValueOnce(take());
    await userEvent.click(mic());
    expect(await screen.findByText("بسجّل...")).toBeInTheDocument();
    expect(document.querySelector(".rec-dot")).not.toBeNull();
    expect(mic()).toBeDisabled();
    expect(mic()).toHaveClass("is-live");
    await act(async () => vi.advanceTimersByTime(5000));
    expect(within(bar()).getByLabelText("المدة")).toHaveTextContent("0:05");
  });

  it("stops into a take to listen to, with the player and the two things that can be done with it", async () => {
    await open();
    await recordTake();
    expect(document.querySelector(".rec-dot")).toBeNull();
    expect(document.querySelector("audio.rec-preview")).toHaveAttribute("src", "blob:the-take");
    expect(within(bar()).getByRole("button", { name: "ابعت" })).toBeEnabled();
    expect(within(bar()).getByRole("button", { name: "إلغاء التسجيل" })).toBeInTheDocument();
  });

  it("can be thrown away while it runs and after it, and nothing is sent", async () => {
    const { calls } = await open();
    const first = take();
    starting.mockResolvedValueOnce(first);
    await userEvent.click(mic());
    await screen.findByText("بسجّل...");
    await userEvent.click(within(bar()).getByRole("button", { name: "إلغاء التسجيل" }));
    expect(first.cancel).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("group", { name: "رسالة صوتية" })).not.toBeInTheDocument();

    await recordTake();
    await userEvent.click(within(bar()).getByRole("button", { name: "إلغاء التسجيل" }));
    expect(screen.queryByRole("group", { name: "رسالة صوتية" })).not.toBeInTheDocument();
    expect(revoked).toHaveBeenCalledWith("blob:the-take");
    expect(mic()).toBeEnabled();
    expect(sends(calls)).toHaveLength(0);
  });

  it("says why when the microphone is refused, and when the browser cannot record", async () => {
    await open();
    starting.mockRejectedValueOnce(new RecorderError("denied"));
    await userEvent.click(mic());
    expect(await screen.findByText(/مفيش إذن للمايك/)).toBeInTheDocument();
    expect(mic()).toBeEnabled();

    starting.mockRejectedValueOnce(new RecorderError("unsupported"));
    await userEvent.click(mic());
    expect(await screen.findByText("المتصفح ده مش بيسجّل صوت.")).toBeInTheDocument();
    expect(screen.queryByText(/مفيش إذن للمايك/)).not.toBeInTheDocument();

    starting.mockRejectedValueOnce(new RecorderError("failed"));
    await userEvent.click(mic());
    expect(await screen.findByText(/التسجيل ماشتغلش/)).toBeInTheDocument();
  });

  it("is off while the 24-hour window is closed", async () => {
    render("/chats/CL-0001", { thread: { client: row("CL-0001", { window_open: false }), messages: [entry(1)] } });
    await screen.findByRole("textbox", { name: "الرسالة" });
    expect(mic()).toBeDisabled();
  });

  it("lets the microphone go when the conversation is left", async () => {
    const view = await open();
    const recording = take();
    starting.mockResolvedValueOnce(recording);
    await userEvent.click(mic());
    await screen.findByText("بسجّل...");
    view.unmount();
    expect(recording.cancel).toHaveBeenCalledTimes(1);
  });
});

describe("sending the note", () => {
  it("sends the recording as `voice`, named by its format, with its length, in one multipart request", async () => {
    const { calls } = await open({ [SEND]: () => answer([entry(1), noteOf(9)]) });
    await recordTake(take(5, ".ogg"));
    await userEvent.click(within(bar()).getByRole("button", { name: "ابعت" }));
    await waitFor(() => expect(sends(calls)).toHaveLength(1));
    const form = formOf(sends(calls)[0]!);
    const voice = form.get("voice") as File;
    expect(voice.name).toBe("voice.ogg");
    expect(voice.size).toBe(5);
    expect(form.get("seconds")).toBe("1");
    expect(form.get("body")).toBe("");
    expect(form.has("task")).toBe(false);
    expect(form.getAll("files")).toEqual([]);
    expect(new Headers(sends(calls)[0]!.init?.headers).has("Content-Type")).toBe(false);
  });

  it("clears the bar, shows the note on its way, and replaces it with the one the server wrote", async () => {
    let release: (value: Response) => void = () => undefined;
    await open({ [SEND]: () => new Promise<Response>((resolve) => (release = resolve)) });
    await recordTake();
    await userEvent.click(within(bar()).getByRole("button", { name: "ابعت" }));
    const pending = await waitFor(() => {
      const found = document.querySelector(".bub--pending") as HTMLElement | null;
      expect(found).not.toBeNull();
      return found!;
    });
    expect(within(pending).getByText("رسالة صوتية")).toBeInTheDocument();
    expect(within(pending).getByText("0:01")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "رسالة صوتية" })).not.toBeInTheDocument();
    release(answer([entry(1), noteOf(9)]));
    await waitFor(() => expect(document.querySelectorAll(".bub--pending")).toHaveLength(0));
    expect(document.querySelector('[data-uid="out-9"]')).not.toBeNull();
  });

  it("sends the words typed beside it, and the words are gone from the box", async () => {
    const { calls } = await open({ [SEND]: () => answer([entry(1), noteOf(9, "listen")]) });
    await userEvent.type(box(), "listen");
    await recordTake();
    await userEvent.click(within(bar()).getByRole("button", { name: "ابعت" }));
    await waitFor(() => expect(sends(calls)).toHaveLength(1));
    expect(formOf(sends(calls)[0]!).get("body")).toBe("listen");
    await waitFor(() => expect(box()).toHaveValue(""));
  });

  it("quotes the message that was chosen, and leaves files that were attached for their own send", async () => {
    const { calls } = await open({ [SEND]: () => answer([entry(1), noteOf(9)]) });
    await userEvent.click(screen.getByRole("button", { name: "رد" }));
    await userEvent.upload(screen.getByLabelText("إرفاق ملفات"), new File(["x"], "kept.pdf"));
    await recordTake();
    await userEvent.click(within(bar()).getByRole("button", { name: "ابعت" }));
    await waitFor(() => expect(sends(calls)).toHaveLength(1));
    const form = formOf(sends(calls)[0]!);
    expect(form.get("reply_uid")).toBe("in-1");
    expect(form.getAll("files")).toEqual([]);
    // The file is still attached, waiting.
    expect(document.querySelectorAll(".cchat__files .chip")).toHaveLength(1);
  });

  it("waits while a message is on its way, so what was said keeps its order", async () => {
    await open({ [SEND]: () => new Promise<Response>(() => undefined) });
    await userEvent.type(box(), "first{Enter}");
    await screen.findByText("بيتبعت...");
    await recordTake();
    expect(within(bar()).getByRole("button", { name: "ابعت" })).toBeDisabled();
  });

  it("will not send a take bigger than the server takes, and says so", async () => {
    await open({
      "/api/v1/me/": () => jsonResponse({ ...me({ role: "operation" }), limits: { ...me().limits, voice: { seconds: 300, bytes: 4 } } }),
    });
    await recordTake(take(10));
    expect(await screen.findByText(/التسجيل أكبر من المسموح/)).toBeInTheDocument();
    expect(within(bar()).getByRole("button", { name: "ابعت" })).toBeDisabled();
  });

  it("keeps a refused note to try again, and says why", async () => {
    let answerWith: () => Response = () => jsonResponse({ ok: false, error: "file_too_big" }, 400);
    const { calls } = await open({ [SEND]: () => answerWith() });
    await recordTake();
    await userEvent.click(within(bar()).getByRole("button", { name: "ابعت" }));
    expect(await screen.findByText("فيه ملف أكبر من المسموح.")).toBeInTheDocument();
    answerWith = () => answer([entry(1), noteOf(9)]);
    await userEvent.click(screen.getByRole("button", { name: "حاول تاني" }));
    await waitFor(() => expect(sends(calls)).toHaveLength(2));
    expect((formOf(sends(calls)[1]!).get("voice") as File).size).toBe(5);
  });
});

describe("when nothing comes back for a voice note", () => {
  it("finds the note in the thread by being a voice note of ours, whatever size the server made of it", async () => {
    let arrived = false;
    await open({
      [SEND]: () => Promise.reject(new TypeError("Failed to fetch")),
      "/api/v1/clients/CL-0001/messages/": () =>
        jsonResponse({ ok: true, client: row("CL-0001"), messages: arrived ? [entry(1), noteOf(9)] : [entry(1)] }),
    });
    arrived = true;
    await recordTake();
    await userEvent.click(within(bar()).getByRole("button", { name: "ابعت" }));
    await waitFor(() => expect(document.querySelector('[data-uid="out-9"]')).not.toBeNull());
    await waitFor(() => expect(document.querySelectorAll(".bub--pending")).toHaveLength(0));
    expect(screen.queryByText(/مش متأكدين/)).not.toBeInTheDocument();
  });

  it("knows it in a work group too, where a voice note is only a file that is audio", async () => {
    let arrived = false;
    render(
      "/chats/g2",
      { thread: { client: row("g2", { group: true, team: true, channel: "" }), messages: [entry(1, { uid: "g2-1" })] } },
      {
        "/api/v1/groups/2/send/": () => Promise.reject(new TypeError("Failed to fetch")),
        "/api/v1/groups/2/messages/": () =>
          jsonResponse({
            ok: true,
            client: row("g2", { group: true, team: true }),
            messages: arrived ? [entry(1, { uid: "g2-1" }), noteOf(9, "", { uid: "g2-9" }, false)] : [entry(1, { uid: "g2-1" })],
          }),
      },
    );
    await screen.findByRole("textbox", { name: "الرسالة" });
    arrived = true;
    await recordTake();
    await userEvent.click(within(bar()).getByRole("button", { name: "ابعت" }));
    await waitFor(() => expect(document.querySelector('[data-uid="g2-9"]')).not.toBeNull());
    await waitFor(() => expect(document.querySelectorAll(".bub--pending")).toHaveLength(0));
  });

  it("is not fooled by a message of ours with the same words and no voice note in it", async () => {
    await open({
      [SEND]: () => Promise.reject(new TypeError("Failed to fetch")),
      "/api/v1/clients/CL-0001/messages/": () =>
        jsonResponse({ ok: true, client: row("CL-0001"), messages: [entry(1), noteOf(9, "", { files: [] })] }),
    });
    await recordTake();
    await userEvent.click(within(bar()).getByRole("button", { name: "ابعت" }));
    expect(await screen.findByText(/مش متأكدين/)).toBeInTheDocument();
    expect(document.querySelectorAll(".bub--pending")).toHaveLength(1);
  });

  it("is not fooled by a voice note somebody else sent", async () => {
    await open({
      [SEND]: () => Promise.reject(new TypeError("Failed to fetch")),
      "/api/v1/clients/CL-0001/messages/": () =>
        jsonResponse({ ok: true, client: row("CL-0001"), messages: [entry(1), noteOf(9, "", { sender: "Mona", sender_id: 99 })] }),
    });
    await recordTake();
    await userEvent.click(within(bar()).getByRole("button", { name: "ابعت" }));
    expect(await screen.findByText(/مش متأكدين/)).toBeInTheDocument();
  });
});
