import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CallInfo } from "../api/types";
import { LINGER_MS, SIGNAL_POLL_MS, calls } from "../lib/calls";
import { jsonResponse, mockFetch, renderWithProviders } from "../test/helpers";
import { FakePeer, installWebRtc } from "../test/webrtc";
import { CallOverlay } from "./CallOverlay";
import { CallButtons } from "./chat/CallButtons";

vi.mock("../lib/chime", () => ({ chime: vi.fn(), armSound: vi.fn(() => () => undefined), resetSound: vi.fn() }));

const INCOMING: CallInfo = { id: 9, video: false, from: "Sam", initials: "SA", chat_url: "/ops/chats/u/4/" };
const ANSWERED = "2026-10-03T10:00:00+00:00";

let status: Record<number, string>;
let web: ReturnType<typeof installWebRtc>;
let seen: { url: string; init?: RequestInit }[];

function serve(over: { answer?: () => Response; start?: () => Response } = {}) {
  status = {};
  seen = [];
  const call = (id: number, state = "ringing") => ({ id, status: state, video: false, caller: true, other: "Mona", initials: "MO", answered_at: state === "active" ? ANSWERED : "" });
  const mocked = mockFetch({
    "/api/calls/start/": () => over.start?.() ?? jsonResponse({ ok: true, call: call(7), ice: [] }),
    "/api/calls/9/answer/": () => over.answer?.() ?? jsonResponse({ ok: true, call: { ...call(9, "active"), caller: false }, ice: [] }),
    "/api/calls/": (url) => {
      const id = Number(url.pathname.split("/")[3]);
      return jsonResponse({ ok: true, call: call(id, status[id] ?? "ringing"), signals: [] });
    },
  });
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    seen.push({ url: new URL(String(input), "http://localhost").pathname, init });
    return mocked.fn(input, init);
  });
}

async function tick(ms = 0) {
  await vi.advanceTimersByTimeAsync(ms);
  await new Promise<void>((resolve) => setImmediate(resolve));
  await vi.advanceTimersByTimeAsync(0);
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout", "Date"] });
  vi.setSystemTime(new Date(ANSWERED));
  web = installWebRtc();
  serve();
  calls.reset();
});
afterEach(() => {
  calls.reset();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const open = (lang: "ar" | "en" = "ar") => renderWithProviders(<CallOverlay />, { lang });
const ring = (info: CallInfo = INCOMING) => act(() => calls.incoming(info));
const press = async (name: string) => {
  fireEvent.click(screen.getByRole("button", { name }));
  await act(async () => void (await tick(0)));
};

describe("CallOverlay", () => {
  it("is not there when there is no call", () => {
    open();
    expect(document.querySelector("#callOverlay")).toBeNull();
  });

  it("shows who is calling and what it is, with the two buttons a ringing phone has", () => {
    open();
    ring();
    expect(screen.getByRole("dialog", { name: "Sam" })).toHaveAttribute("data-phase", "incoming");
    expect(screen.getByText("SA")).toHaveClass("call__face");
    expect(screen.getByText("مكالمة صوتية جاية…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "رد" })).toHaveClass("call__btn--ok");
    expect(screen.getByRole("button", { name: "إنهاء" })).toHaveClass("call__btn--end");
    // Nothing to mute or to switch off before it is answered.
    expect(screen.queryByRole("button", { name: "كتم المايك" })).toBeNull();
    expect(screen.queryByRole("button", { name: "قفل الكاميرا" })).toBeNull();
  });

  it("says a video call is a video call", () => {
    open();
    ring({ ...INCOMING, video: true });
    expect(screen.getByText("مكالمة فيديو جاية…")).toBeInTheDocument();
  });

  it("is answered with the green button, and then shows a clock from when it was answered", async () => {
    open();
    ring();
    await press("رد");
    expect(screen.getByRole("dialog")).toHaveAttribute("data-phase", "live");
    expect(screen.queryByRole("button", { name: "رد" })).toBeNull();
    expect(document.querySelector("#callState")).toHaveTextContent("0:00");
    await act(async () => void (await tick(5000)));
    expect(document.querySelector("#callState")).toHaveTextContent("0:05");
    await act(async () => void (await tick(60_000)));
    expect(document.querySelector("#callState")).toHaveTextContent("1:05");
  });

  it("offers the microphone's mute while it is on, and says whether it is muted", async () => {
    open();
    ring();
    await press("رد");
    const mute = screen.getByRole("button", { name: "كتم المايك" });
    expect(mute).toHaveAttribute("aria-pressed", "false");
    await press("كتم المايك");
    expect(screen.getByRole("button", { name: "كتم المايك" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "كتم المايك" })).toHaveClass("is-off");
    expect(web.streams[0]!.getAudioTracks()[0]!.enabled).toBe(false);
  });

  it("offers the camera's switch only for a video call, and draws the other end's picture when it arrives", async () => {
    open();
    ring({ ...INCOMING, video: true });
    await press("رد");
    expect(screen.getByRole("button", { name: "قفل الكاميرا" })).toBeInTheDocument();
    expect(document.querySelector(".call")).not.toHaveClass("is-video");
    expect(document.querySelector(".call__remote")).toHaveClass("hidden");
    const stream = { id: "remote" };
    act(() => FakePeer.all[0]!.emitTrack(stream));
    expect(document.querySelector(".call")).toHaveClass("is-video");
    expect(document.querySelector(".call__remote")).not.toHaveClass("hidden");
    expect((document.querySelector(".call__remote") as HTMLVideoElement & { srcObject: unknown }).srcObject).toBe(stream);
    expect((document.querySelector("audio") as HTMLAudioElement & { srcObject: unknown }).srcObject).toBe(stream);
    await press("قفل الكاميرا");
    expect(screen.getByRole("button", { name: "قفل الكاميرا" })).toHaveAttribute("aria-pressed", "true");
  });

  it("draws no picture for a voice call, but still plays the voice", async () => {
    open();
    ring();
    await press("رد");
    const stream = { id: "voice" };
    act(() => FakePeer.all[0]!.emitTrack(stream));
    expect(document.querySelector(".call")).not.toHaveClass("is-video");
    expect((document.querySelector(".call__remote") as HTMLVideoElement & { srcObject: unknown }).srcObject).toBeNull();
    expect((document.querySelector("audio") as HTMLAudioElement & { srcObject: unknown }).srcObject).toBe(stream);
    expect(screen.queryByRole("button", { name: "قفل الكاميرا" })).toBeNull();
  });

  it("is turned down with the red button, says so, and goes after a moment", async () => {
    open();
    ring();
    await press("إنهاء");
    expect(screen.getByText("رفضت المكالمة")).toBeInTheDocument();
    expect(seen.find((call) => call.url === "/api/calls/9/end/")).toBeDefined();
    await act(async () => void (await tick(LINGER_MS + 10)));
    expect(document.querySelector("#callOverlay")).toBeNull();
  });

  it("is hung up with the same button while it is going on", async () => {
    open();
    ring();
    await press("رد");
    await press("إنهاء");
    expect(screen.getByText("المكالمة خلصت")).toBeInTheDocument();
    expect(new URLSearchParams(String(seen.find((call) => call.url === "/api/calls/9/end/")!.init?.body)).get("reason")).toBe("ended");
  });

  it("says the other end hung up or gave up when the server says so", async () => {
    open();
    ring();
    await press("رد");
    status[9] = "ended";
    await act(async () => void (await tick(SIGNAL_POLL_MS)));
    expect(screen.getByText("المكالمة خلصت")).toBeInTheDocument();
  });

  it("says why in the server's own words when a call cannot be placed", async () => {
    serve({ start: () => jsonResponse({ ok: false, error: "Mona في مكالمة تانية دلوقتي." }, 400) });
    open();
    await act(async () => void (await calls.place({ userId: 5, name: "Mona", initials: "MO" }, false)));
    await act(async () => void (await tick(0)));
    expect(screen.getByText("Mona في مكالمة تانية دلوقتي.")).toBeInTheDocument();
  });

  it("says to allow the microphone when the browser refuses it", async () => {
    web = installWebRtc({ denied: true });
    open();
    await act(async () => void (await calls.place({ userId: 5, name: "Mona", initials: "MO" }, false)));
    await act(async () => void (await tick(0)));
    expect(screen.getByText("لازم تسمح للمتصفح يستخدم المايك.")).toBeInTheDocument();
  });

  it("says ringing while it rings at somebody and nothing is muted or switched", async () => {
    open();
    await act(async () => void (await calls.place({ userId: 5, name: "Mona", initials: "MO" }, false)));
    await act(async () => void (await tick(0)));
    expect(screen.getByRole("dialog", { name: "Mona" })).toHaveAttribute("data-phase", "ringing");
    expect(screen.getByText("بيرن…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "رد" })).toBeNull();
  });

  it("warns before the page is left while a call is on, and only then", async () => {
    open();
    const left = () => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    };
    ring();
    expect(left()).toBe(false);
    await press("رد");
    expect(left()).toBe(true);
  });

  it("tells the server as the page goes away, so the other end is not left talking to nobody", async () => {
    open();
    ring();
    await press("رد");
    window.dispatchEvent(new Event("pagehide"));
    expect(web.beacons).toHaveLength(1);
    expect(web.beacons[0]!.url).toBe("/api/calls/9/end/");
    expect(web.beacons[0]!.data.get("reason")).toBe("ended");
  });

  it("does not warn or send anything when there is no call", () => {
    open();
    window.dispatchEvent(new Event("pagehide"));
    expect(web.beacons).toEqual([]);
  });

  it("is in English too", () => {
    open("en");
    ring({ ...INCOMING, video: true });
    expect(screen.getByText("Incoming video call…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Answer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hang up" })).toBeInTheDocument();
  });
});

describe("CallButtons", () => {
  const render = (code: string, lang: "ar" | "en" = "ar") => renderWithProviders(<CallButtons code={code} name="Mona" initials="MO" />, { lang });

  it("has a voice call and a video call for a colleague, and rings them as such", async () => {
    const place = vi.spyOn(calls, "place").mockResolvedValue(undefined);
    render("u5");
    fireEvent.click(screen.getByRole("button", { name: "مكالمة صوتية" }));
    fireEvent.click(screen.getByRole("button", { name: "مكالمة فيديو" }));
    expect(place).toHaveBeenNthCalledWith(1, { userId: 5, name: "Mona", initials: "MO" }, false);
    expect(place).toHaveBeenNthCalledWith(2, { userId: 5, name: "Mona", initials: "MO" }, true);
    place.mockRestore();
  });

  it("is nothing for a client, a group or an address that is not a colleague's", () => {
    for (const code of ["CL-0001", "g12", "u", "u5x", "x5"]) {
      const view = render(code);
      expect(screen.queryByRole("button"), code).toBeNull();
      view.unmount();
    }
  });

  it("is off while a call is on the screen, and on again when it is over", async () => {
    render("u5");
    expect(screen.getByRole("button", { name: "مكالمة صوتية" })).toBeEnabled();
    act(() => calls.incoming(INCOMING));
    expect(screen.getByRole("button", { name: "مكالمة صوتية" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "مكالمة فيديو" })).toBeDisabled();
    await act(async () => void (await calls.pressHangUp()));
    // Its last words are still on the screen, but another call may be placed.
    expect(screen.getByRole("button", { name: "مكالمة صوتية" })).toBeEnabled();
  });

  it("is in English too", () => {
    render("u5", "en");
    expect(screen.getByRole("button", { name: "Voice call" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Video call" })).toBeInTheDocument();
  });
});
