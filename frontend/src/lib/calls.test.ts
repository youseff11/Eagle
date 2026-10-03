import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CallInfo } from "../api/types";
import { FakePeer, installWebRtc } from "../test/webrtc";
import { jsonResponse, mockFetch } from "../test/helpers";
import { LINGER_MS, RING_POLL_MS, RING_REPEAT_MS, RING_SECONDS, SIGNAL_POLL_MS, calls } from "./calls";
import { chime } from "./chime";

vi.mock("./chime", () => ({ chime: vi.fn(), armSound: vi.fn(() => () => undefined), resetSound: vi.fn() }));

const PERSON = { userId: 5, name: "Mona", initials: "MO" };
const ICE = [{ urls: ["stun:stun.example:19302"] }];
const callJson = (over: object = {}) => ({ id: 7, status: "ringing", video: false, caller: true, other: "Mona", initials: "MO", answered_at: "", ...over });
const INCOMING: CallInfo = { id: 9, video: false, from: "Sam", initials: "SA", chat_url: "/ops/chats/u/4/" };

type Call = { url: string; init?: RequestInit };
let server: {
  /** What the server says the call's state is, per call id. */
  status: Record<number, string>;
  /** The signals the other end has sent, per call id. */
  signals: Record<number, { id: number; kind: string; payload: string }[]>;
  start: () => Response;
  answer: () => Response;
  calls: Call[];
};
let web: ReturnType<typeof installWebRtc>;

function serve(over: Partial<typeof server> = {}) {
  server = {
    status: {},
    signals: {},
    start: () => jsonResponse({ ok: true, call: callJson(), ice: ICE }),
    answer: () => jsonResponse({ ok: true, call: callJson({ id: 9, status: "active", caller: false, answered_at: "2026-10-03T10:00:00+00:00" }), ice: ICE }),
    calls: [],
    ...over,
  };
  const mocked = mockFetch({
    "/api/calls/start/": () => server.start(),
    "/api/calls/9/answer/": () => server.answer(),
    "/api/calls/": (url, init) => {
      // "", "api", "calls", "<id>", "signals" | "end", "".
      const [, , , id, kind] = url.pathname.split("/");
      const call = Number(id);
      if (kind === "signals" && init?.method !== "POST") {
        const after = Number(url.searchParams.get("after") ?? 0);
        return jsonResponse({ ok: true, call: callJson({ id: call, status: server.status[call] ?? "ringing" }), signals: (server.signals[call] ?? []).filter((one) => one.id > after) });
      }
      return jsonResponse({ ok: true, call: callJson({ id: call }) });
    },
  });
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    server.calls.push({ url: new URL(String(input), "http://localhost").pathname + new URL(String(input), "http://localhost").search, init });
    return mocked.fn(input, init);
  });
}

const posts = (path: string) => server.calls.filter((call) => call.url === path && call.init?.method === "POST");
const form = (call: Call) => Object.fromEntries(new URLSearchParams(String(call.init?.body)));
/**
 * Let time pass, and let the answers that were asked for arrive: a `Response` reads its body on the real event loop, which
 * fake timers do not move.
 */
async function tick(ms = 0) {
  await vi.advanceTimersByTimeAsync(ms);
  await new Promise<void>((resolve) => setImmediate(resolve));
  await vi.advanceTimersByTimeAsync(0);
}
const flush = () => tick(0);
const peer = () => FakePeer.all[FakePeer.all.length - 1]!;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout", "Date"] });
  vi.mocked(chime).mockClear();
  web = installWebRtc();
  serve();
  calls.reset();
});
afterEach(() => {
  calls.reset();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("placing a call", () => {
  it("opens the microphone only for a voice call, asks the server to ring, and sends the offer", async () => {
    await calls.place(PERSON, false);
    await flush();
    expect(web.asked).toEqual([{ audio: true, video: false }]);
    expect(form(posts("/api/calls/start/")[0]!)).toEqual({ user: "5", video: "" });
    expect(calls.getState()).toMatchObject({ phase: "ringing", id: 7, name: "Mona", initials: "MO", video: false, caller: true, notice: "ringing" });
    expect(peer().config).toEqual({ iceServers: ICE });
    expect(peer().added).toHaveLength(1);
    const offer = posts("/api/calls/7/signals/")[0]!;
    expect(form(offer).kind).toBe("offer");
    expect(JSON.parse(form(offer).payload)).toEqual({ type: "offer", sdp: "offer-sdp" });
  });

  it("opens the camera too for a video call, and says so to the server", async () => {
    server.start = () => jsonResponse({ ok: true, call: callJson({ video: true }), ice: ICE });
    await calls.place(PERSON, true);
    await flush();
    expect(web.asked).toEqual([{ audio: true, video: true }]);
    expect(form(posts("/api/calls/start/")[0]!).video).toBe("1");
    expect(peer().added).toHaveLength(2);
  });

  it("says it is opening the microphone while the browser asks, and rings the phone while it rings", async () => {
    web = installWebRtc({ hold: true });
    const placing = calls.place(PERSON, false);
    await flush();
    expect(calls.getState()).toMatchObject({ phase: "starting", notice: "opening_mic" });
    web.release();
    await placing;
    await flush();
    expect(calls.getState().phase).toBe("ringing");
    expect(chime).toHaveBeenCalledWith(2, 880);
    const rang = vi.mocked(chime).mock.calls.length;
    await tick(RING_REPEAT_MS * 2);
    expect(vi.mocked(chime).mock.calls.length).toBe(rang + 2);
  });

  it("is a refusal of the microphone, said so, with nothing sent to the server", async () => {
    web = installWebRtc({ denied: true });
    await calls.place(PERSON, false);
    await flush();
    expect(calls.getState()).toMatchObject({ phase: "ended", notice: "mic_denied" });
    expect(posts("/api/calls/start/")).toHaveLength(0);
    await tick(LINGER_MS + 10);
    expect(calls.getState().phase).toBe("idle");
  });

  it("is the same for a browser that has no microphone to open", async () => {
    web = installWebRtc({ unsupported: true });
    await calls.place(PERSON, false);
    await flush();
    expect(calls.getState()).toMatchObject({ phase: "ended", notice: "mic_denied" });
  });

  it("says why in the server's own words when it will not ring, and lets the microphone go", async () => {
    server.start = () => jsonResponse({ ok: false, error: "Mona في مكالمة تانية دلوقتي." }, 400);
    await calls.place(PERSON, false);
    await flush();
    expect(calls.getState()).toMatchObject({ phase: "ended", notice: "could_not_call", detail: "Mona في مكالمة تانية دلوقتي." });
    expect(web.streams[0]!.tracks.every((track) => track.stopped)).toBe(true);
    expect(FakePeer.all).toHaveLength(0);
  });

  it("says it could not call when the server did not even answer", async () => {
    server.start = () => {
      throw new TypeError("network");
    };
    await calls.place(PERSON, false);
    await flush();
    expect(calls.getState()).toMatchObject({ phase: "ended", notice: "could_not_call", detail: "" });
  });

  it("does nothing while another call is on the screen", async () => {
    await calls.place(PERSON, false);
    await flush();
    await calls.place({ userId: 8, name: "Sam", initials: "SA" }, false);
    await flush();
    expect(posts("/api/calls/start/")).toHaveLength(1);
    expect(calls.getState().name).toBe("Mona");
    expect(calls.busy).toBe(true);
  });

  it("sends this end's network candidates to the other end as they are found", async () => {
    await calls.place(PERSON, false);
    await flush();
    peer().emitCandidate({ candidate: "candidate:1", sdpMid: "0" });
    await flush();
    const ice = posts("/api/calls/7/signals/").filter((call) => form(call).kind === "ice");
    expect(ice).toHaveLength(1);
    expect(JSON.parse(form(ice[0]!).payload)).toEqual({ candidate: "candidate:1", sdpMid: "0" });
  });

  it("is on the line once the other end answers, with the clock from when they did", async () => {
    await calls.place(PERSON, false);
    await flush();
    server.signals[7] = [{ id: 1, kind: "answer", payload: JSON.stringify({ type: "answer", sdp: "their-sdp" }) }];
    server.status[7] = "active";
    server.calls.length = 0;
    await tick(SIGNAL_POLL_MS);
    expect(peer().remoteDescription).toEqual({ type: "answer", sdp: "their-sdp" });
    expect(calls.getState().phase).toBe("live");
    // The ringing stops, and so does the wait for an answer: nobody gives up on a call that is going on.
    const rang = vi.mocked(chime).mock.calls.length;
    await tick(RING_REPEAT_MS * 3);
    expect(vi.mocked(chime).mock.calls.length).toBe(rang);
    await tick(RING_SECONDS * 1000);
    expect(posts("/api/calls/7/end/")).toHaveLength(0);
    expect(calls.getState().phase).toBe("live");
  });

  it("holds the other end's candidates until it knows their description, then adds them in order", async () => {
    await calls.place(PERSON, false);
    await flush();
    server.signals[7] = [
      { id: 1, kind: "ice", payload: JSON.stringify({ candidate: "c1" }) },
      { id: 2, kind: "ice", payload: JSON.stringify({ candidate: "c2" }) },
    ];
    await tick(SIGNAL_POLL_MS);
    expect(peer().iceAdded).toEqual([]);
    server.signals[7] = [{ id: 3, kind: "answer", payload: JSON.stringify({ type: "answer", sdp: "s" }) }];
    await tick(SIGNAL_POLL_MS);
    expect(peer().iceAdded).toEqual([{ candidate: "c1" }, { candidate: "c2" }]);
    // A candidate that arrives after goes straight in.
    server.signals[7] = [{ id: 4, kind: "ice", payload: JSON.stringify({ candidate: "c3" }) }];
    await tick(SIGNAL_POLL_MS);
    expect(peer().iceAdded).toHaveLength(3);
  });

  it("asks only for what it has not seen, so a signal is never handled twice", async () => {
    await calls.place(PERSON, false);
    await flush();
    server.signals[7] = [{ id: 4, kind: "ice", payload: JSON.stringify({ candidate: "c1" }) }];
    server.status[7] = "ringing";
    server.calls.length = 0;
    await tick(SIGNAL_POLL_MS * 2);
    expect(server.calls.map((call) => call.url)).toEqual(["/api/calls/7/signals/?after=0", "/api/calls/7/signals/?after=4"]);
  });

  it("ignores what is not valid JSON, and a signal that is not for this end", async () => {
    await calls.place(PERSON, false);
    await flush();
    server.signals[7] = [
      { id: 1, kind: "ice", payload: "{not json" },
      { id: 2, kind: "offer", payload: JSON.stringify({ type: "offer", sdp: "x" }) },
    ];
    await tick(SIGNAL_POLL_MS);
    expect(peer().remoteDescription).toBeNull();
    expect(calls.getState().phase).toBe("ringing");
  });

  it("shows the other end's picture and voice when they arrive", async () => {
    await calls.place(PERSON, false);
    await flush();
    const stream = { id: "remote" };
    peer().emitTrack(stream);
    expect(calls.getState().remote).toBe(stream);
  });

  it("says the network is blocking it when the connection fails", async () => {
    await calls.place(PERSON, false);
    await flush();
    peer().setState("failed");
    expect(calls.getState().notice).toBe("network");
    expect(calls.getState().phase).toBe("ringing");
  });

  it("is a declined call when they turn it down, said so, and everything it opened is closed", async () => {
    await calls.place(PERSON, false);
    await flush();
    const closing = peer();
    server.status[7] = "declined";
    await tick(SIGNAL_POLL_MS);
    expect(calls.getState()).toMatchObject({ phase: "ended", notice: "declined" });
    expect(closing.closed).toBe(true);
    expect(web.streams[0]!.tracks.every((track) => track.stopped)).toBe(true);
  });

  it("is no answer when nobody picked up, and a call that ended on their side is said to have ended", async () => {
    await calls.place(PERSON, false);
    await flush();
    server.status[7] = "missed";
    await tick(SIGNAL_POLL_MS);
    expect(calls.getState().notice).toBe("no_answer");
    await tick(LINGER_MS + 10);
    await calls.place(PERSON, false);
    await flush();
    server.status[7] = "ended";
    await tick(SIGNAL_POLL_MS);
    expect(calls.getState().notice).toBe("ended");
  });

  it("gives up after the ring is over, tells the server it was missed, and lets the microphone go", async () => {
    await calls.place(PERSON, false);
    await flush();
    await tick(RING_SECONDS * 1000);
    expect(form(posts("/api/calls/7/end/")[0]!)).toEqual({ reason: "missed" });
    expect(calls.getState()).toMatchObject({ phase: "ended", notice: "over" });
    expect(web.streams[0]!.tracks.every((track) => track.stopped)).toBe(true);
    expect(peer().closed).toBe(true);
  });

  it("is hung up by the person: a call still ringing is missed, one in progress is ended", async () => {
    await calls.place(PERSON, false);
    await flush();
    await calls.pressHangUp();
    expect(form(posts("/api/calls/7/end/")[0]!)).toEqual({ reason: "missed" });
    await tick(LINGER_MS + 10);
    await calls.place(PERSON, false);
    await flush();
    server.status[7] = "active";
    await tick(SIGNAL_POLL_MS);
    expect(calls.getState().phase).toBe("live");
    await calls.pressHangUp();
    expect(form(posts("/api/calls/7/end/")[1]!)).toEqual({ reason: "ended" });
    expect(calls.getState().notice).toBe("over");
  });

  it("drops the call if the person hangs up while the browser is still asking for the microphone", async () => {
    web = installWebRtc({ hold: true });
    const placing = calls.place(PERSON, false);
    await flush();
    await calls.pressHangUp();
    web.release();
    await placing;
    await flush();
    expect(posts("/api/calls/start/")).toHaveLength(0);
    expect(web.streams[0]!.tracks.every((track) => track.stopped)).toBe(true);
    expect(FakePeer.all).toHaveLength(0);
  });

  it("closes the call that was made if the person hung up while the server was making it", async () => {
    let release: (() => void) | undefined;
    server.start = () => {
      throw new Error("never");
    };
    const mocked = mockFetch({
      "/api/calls/start/": () => new Promise<Response>((resolve) => (release = () => resolve(jsonResponse({ ok: true, call: callJson(), ice: ICE })))) as unknown as Response,
      "/api/calls/": () => jsonResponse({ ok: true, call: callJson() }),
    });
    const seen: Call[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      seen.push({ url: new URL(String(input), "http://localhost").pathname, init });
      return mocked.fn(input, init);
    });
    const placing = calls.place(PERSON, false);
    await flush();
    await calls.pressHangUp();
    release?.();
    await placing;
    await flush();
    const end = seen.find((call) => call.url === "/api/calls/7/end/");
    expect(end).toBeDefined();
    expect(form(end!)).toEqual({ reason: "missed" });
    expect(FakePeer.all).toHaveLength(0);
  });
});

describe("a call coming in", () => {
  it("rings, says whose and whether it is video, and does not open the microphone yet", async () => {
    calls.incoming(INCOMING);
    expect(calls.getState()).toMatchObject({ phase: "incoming", id: 9, name: "Sam", initials: "SA", video: false, caller: false, notice: "incoming_voice" });
    expect(chime).toHaveBeenCalledWith(2, 880);
    expect(web.asked).toEqual([]);
    calls.reset();
    calls.incoming({ ...INCOMING, video: true });
    expect(calls.getState().notice).toBe("incoming_video");
  });

  it("is told again on every beat and keeps what is on the screen, and is not rung over a call in progress", async () => {
    calls.incoming(INCOMING);
    const first = calls.getState();
    calls.incoming(INCOMING);
    expect(calls.getState()).toBe(first);
    calls.incoming({ ...INCOMING, id: 10, from: "Other" });
    expect(calls.getState().name).toBe("Sam");
    calls.incoming(null);
    expect(calls.getState().phase).toBe("incoming");
  });

  it("can be answered: the microphone, the server, the other end's offer, and this end's answer", async () => {
    server.signals[9] = [{ id: 1, kind: "offer", payload: JSON.stringify({ type: "offer", sdp: "their-offer" }) }];
    calls.incoming(INCOMING);
    await calls.answer();
    await flush();
    expect(web.asked).toEqual([{ audio: true, video: false }]);
    expect(posts("/api/calls/9/answer/")).toHaveLength(1);
    expect(calls.getState()).toMatchObject({ phase: "live", answeredAt: "2026-10-03T10:00:00+00:00", notice: "" });
    expect(peer().config).toEqual({ iceServers: ICE });
    await tick(SIGNAL_POLL_MS);
    expect(peer().remoteDescription).toEqual({ type: "offer", sdp: "their-offer" });
    const answer = posts("/api/calls/9/signals/").find((call) => form(call).kind === "answer");
    expect(JSON.parse(form(answer!).payload)).toEqual({ type: "answer", sdp: "answer-sdp" });
    // The ringing stopped the moment it was answered.
    const rang = vi.mocked(chime).mock.calls.length;
    await tick(RING_REPEAT_MS * 3);
    expect(vi.mocked(chime).mock.calls.length).toBe(rang);
  });

  it("opens the camera for a video call it answers, and only for one", async () => {
    calls.incoming({ ...INCOMING, video: true });
    await calls.answer();
    await flush();
    expect(web.asked).toEqual([{ audio: true, video: true }]);
  });

  it("says the call is over when the server will not take the answer", async () => {
    server.answer = () => jsonResponse({ ok: false, error: "المكالمة خلصت." }, 400);
    calls.incoming(INCOMING);
    await calls.answer();
    await flush();
    expect(calls.getState()).toMatchObject({ phase: "ended", notice: "over" });
    expect(web.streams[0]!.tracks.every((track) => track.stopped)).toBe(true);
  });

  it("is turned down, with the reason, when the microphone is refused - and not rung again by the next beat", async () => {
    web = installWebRtc({ denied: true });
    calls.incoming(INCOMING);
    await calls.answer();
    await flush();
    expect(form(posts("/api/calls/9/end/")[0]!)).toEqual({ reason: "declined" });
    expect(calls.getState().notice).toBe("mic_denied");
    await tick(LINGER_MS + 10);
    calls.incoming(INCOMING);
    expect(calls.getState().phase).toBe("idle");
  });

  it("is declined with the red button, once, and the next beat does not ring it again before the server catches up", async () => {
    calls.incoming(INCOMING);
    await calls.pressHangUp();
    expect(posts("/api/calls/9/end/")).toHaveLength(1);
    expect(form(posts("/api/calls/9/end/")[0]!)).toEqual({ reason: "declined" });
    expect(calls.getState().notice).toBe("declined_by_me");
    await tick(LINGER_MS + 10);
    calls.incoming(INCOMING);
    expect(calls.getState().phase).toBe("idle");
  });

  it("stops ringing when the caller gives up before it is answered, and says it was missed", async () => {
    calls.incoming(INCOMING);
    server.status[9] = "missed";
    await tick(RING_POLL_MS);
    expect(calls.getState()).toMatchObject({ phase: "ended", notice: "missed" });
    const rang = vi.mocked(chime).mock.calls.length;
    await tick(RING_REPEAT_MS * 3);
    expect(vi.mocked(chime).mock.calls.length).toBe(rang);
  });

  it("keeps ringing while the caller is still there", async () => {
    calls.incoming(INCOMING);
    await tick(RING_POLL_MS * 3);
    expect(calls.getState().phase).toBe("incoming");
  });

  it("can be rung again after its last words have been read, and while they are still on screen", async () => {
    calls.incoming(INCOMING);
    await calls.pressHangUp();
    expect(calls.getState().phase).toBe("ended");
    calls.incoming({ ...INCOMING, id: 11, from: "Nada" });
    expect(calls.getState()).toMatchObject({ phase: "incoming", id: 11, name: "Nada" });
  });

  it("does not take what the server says of a call that is no longer the one on the screen", async () => {
    calls.incoming(INCOMING);
    await calls.answer();
    await flush();
    server.signals[9] = [{ id: 1, kind: "ice", payload: JSON.stringify({ candidate: "late" }) }];
    const old = peer();
    await calls.pressHangUp();
    await tick(SIGNAL_POLL_MS * 2);
    expect(old.iceAdded).toEqual([]);
  });
});

describe("on the line", () => {
  async function live(video = false) {
    server.start = () => jsonResponse({ ok: true, call: callJson({ video }), ice: ICE });
    await calls.place(PERSON, video);
    await flush();
    server.status[7] = "active";
    await tick(SIGNAL_POLL_MS);
  }

  it("mutes the microphone and puts it back, and the state says which", async () => {
    await live();
    const [audio] = web.streams[0]!.getAudioTracks();
    calls.toggleMute();
    expect([audio!.enabled, calls.getState().muted]).toEqual([false, true]);
    calls.toggleMute();
    expect([audio!.enabled, calls.getState().muted]).toEqual([true, false]);
  });

  it("turns the camera off and on for a video call, and does nothing for a voice call", async () => {
    await live(true);
    const [video] = web.streams[0]!.getVideoTracks();
    calls.toggleCamera();
    expect([video!.enabled, calls.getState().cameraOff]).toEqual([false, true]);
    calls.toggleCamera();
    expect(calls.getState().cameraOff).toBe(false);
    calls.reset();
    await live();
    calls.toggleCamera();
    expect(calls.getState().cameraOff).toBe(false);
  });

  it("does nothing to mute when there is no call", () => {
    calls.toggleMute();
    calls.toggleCamera();
    expect(calls.getState().muted).toBe(false);
  });

  it("tells the server as the page goes away: a call in progress ended, one still ringing missed, and nothing when there is none", async () => {
    calls.leaving("tok");
    expect(web.beacons).toEqual([]);
    await calls.place(PERSON, false);
    await flush();
    calls.leaving("tok");
    expect(web.beacons[0]!.url).toBe("/api/calls/7/end/");
    expect(Object.fromEntries(web.beacons[0]!.data.entries())).toEqual({ reason: "missed", csrfmiddlewaretoken: "tok" });
    server.status[7] = "active";
    await tick(SIGNAL_POLL_MS);
    calls.leaving("tok");
    expect(Object.fromEntries(web.beacons[1]!.data.entries()).reason).toBe("ended");
  });

  it("is the button's own: a finished call's last words are dismissed by it", async () => {
    calls.incoming(INCOMING);
    await calls.pressHangUp();
    expect(calls.getState().phase).toBe("ended");
    await calls.pressHangUp();
    expect(calls.getState().phase).toBe("idle");
  });

  it("closes the peer, the microphone and every timer when it ends, so nothing polls a dead call", async () => {
    await live();
    await calls.pressHangUp();
    server.calls.length = 0;
    await tick(SIGNAL_POLL_MS * 5 + RING_SECONDS * 1000);
    expect(server.calls.filter((call) => call.url.includes("/signals/"))).toEqual([]);
    expect(peer().closed).toBe(true);
  });
});

describe("subscribing", () => {
  it("tells whoever draws it on every change, until they stop listening", async () => {
    const heard: string[] = [];
    const stop = calls.subscribe(() => heard.push(calls.getState().phase));
    calls.incoming(INCOMING);
    await calls.pressHangUp();
    stop();
    calls.reset();
    expect(heard).toEqual(["incoming", "ended"]);
  });

  it("keeps the same state object until something changes, so a screen is not drawn again for nothing", () => {
    const state = calls.getState();
    expect(calls.getState()).toBe(state);
  });
});
