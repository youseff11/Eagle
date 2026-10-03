import { ApiError, api } from "../api/client";
import type { CallInfo, CallSignals, CallStarted } from "../api/types";
import { chime } from "./chime";

/**
 * Calls between colleagues - voice or video, browser to browser (WebRTC), as `static/js/calls.js` does them.
 *
 * The server only keeps the record and passes the two browsers' connection details between them
 * (`/api/calls/...`, the classic endpoints, unchanged). A ringing call reaches the person through the heartbeat, so it
 * rings on whatever page they have open. Nothing here involves a client: a call is between two people of the staff, and
 * the camera and the microphone are opened only for a call this person placed or answered, never otherwise.
 *
 * One engine for the whole page (`calls`): the overlay draws what it says, the chat's buttons place a call, the heartbeat
 * tells it one is ringing. It is a plain object with subscribers, so it can be driven and tested without a browser.
 */

export type Phase = "idle" | "incoming" | "starting" | "ringing" | "connecting" | "live" | "ended";

/** What the line under the name says. The words are the page's (`CallOverlay`); `detail` is the server's own, when it gave one. */
export type Notice =
  | ""
  | "opening_mic"
  | "ringing"
  | "incoming_voice"
  | "incoming_video"
  | "connecting"
  | "network"
  | "ended"
  | "declined_by_me"
  | "declined"
  | "no_answer"
  | "missed"
  | "mic_denied"
  | "could_not_call"
  | "over";

export interface CallState {
  phase: Phase;
  id: number;
  name: string;
  initials: string;
  video: boolean;
  /** This person placed it (as opposed to answering). */
  caller: boolean;
  notice: Notice;
  /** The server's own words for why it could not be placed, in Arabic. */
  detail: string;
  /** When it was answered (ISO), for the clock. */
  answeredAt: string;
  muted: boolean;
  cameraOff: boolean;
  local: MediaStream | null;
  remote: MediaStream | null;
}

/** How long a call rings before it is a missed call (`services.CALL_RING_SECONDS`). */
export const RING_SECONDS = 45;
/** How often the two browsers ask for each other's connection details. */
export const SIGNAL_POLL_MS = 1000;
/** How often a ringing phone asks whether the caller has given up. */
export const RING_POLL_MS = 2000;
/** The ring is repeated at this pace while the phone rings. */
export const RING_REPEAT_MS = 2200;
/** How long the last word ("Call ended") stays on the screen. */
export const LINGER_MS = 1400;

const IDLE: CallState = {
  phase: "idle",
  id: 0,
  name: "",
  initials: "",
  video: false,
  caller: false,
  notice: "",
  detail: "",
  answeredAt: "",
  muted: false,
  cameraOff: false,
  local: null,
  remote: null,
};

type Listener = () => void;

/** The sentence the server wrote for a refusal (it comes back as the error's code or its message), or `""`. */
function sentence(error: unknown): string {
  if (!(error instanceof ApiError)) return "";
  return /[^\x00-\x7f]/.test(error.code) ? error.code : error.detail;
}

async function media(video: boolean): Promise<MediaStream> {
  if (!navigator.mediaDevices?.getUserMedia) throw new Error("unsupported");
  // The microphone for every call; the camera only for a video call, and only because somebody pressed that button.
  return navigator.mediaDevices.getUserMedia({ audio: true, video });
}

export class CallEngine {
  private state: CallState = { ...IDLE };
  private listeners = new Set<Listener>();
  private peer: RTCPeerConnection | null = null;
  private after = 0;
  private pendingIce: RTCIceCandidateInit[] = [];
  private ring: ReturnType<typeof setInterval> | null = null;
  private poll: ReturnType<typeof setInterval> | null = null;
  private giveUp: ReturnType<typeof setTimeout> | null = null;
  private linger: ReturnType<typeof setTimeout> | null = null;
  /** Calls turned down here, so the heartbeat does not ring them again before the server has caught up. */
  private declined = new Set<number>();
  /** A newer attempt started while an older one was waiting for the microphone: the older one stops. */
  private attempt = 0;

  // -- the state, for whoever draws it ---------------------------------------------------------------------------

  getState = (): CallState => this.state;

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private set(patch: Partial<CallState>): void {
    this.state = { ...this.state, ...patch };
    for (const listener of this.listeners) listener();
  }

  /** There is a call on the screen (ringing, in progress, or its last word): another cannot be placed over it. */
  get busy(): boolean {
    return this.state.phase !== "idle" && this.state.phase !== "ended";
  }

  /** Back to nothing, whatever was going on: for a test, and for the page that is going away. */
  reset(): void {
    this.cleanup();
    this.declined.clear();
    this.attempt += 1;
    this.set({ ...IDLE });
  }

  // -- sound and clocks --------------------------------------------------------------------------------------------

  private startRinging(): void {
    this.stopRinging();
    chime(2, 880);
    this.ring = setInterval(() => chime(2, 880), RING_REPEAT_MS);
  }

  private stopRinging(): void {
    if (this.ring) clearInterval(this.ring);
    this.ring = null;
  }

  private stopTimers(): void {
    this.stopRinging();
    if (this.poll) clearInterval(this.poll);
    if (this.giveUp) clearTimeout(this.giveUp);
    this.poll = null;
    this.giveUp = null;
  }

  // -- plumbing ---------------------------------------------------------------------------------------------------

  private send(kind: string, payload: unknown): void {
    if (!this.state.id) return;
    void api(`/api/calls/${this.state.id}/signals/`, { form: { kind, payload: JSON.stringify(payload) } }).catch(() => undefined);
  }

  private connect(ice: RTCIceServer[] | undefined, local: MediaStream): RTCPeerConnection {
    const peer = new RTCPeerConnection({ iceServers: ice ?? [] });
    for (const track of local.getTracks()) peer.addTrack(track, local);
    peer.onicecandidate = (event) => {
      if (event.candidate) this.send("ice", event.candidate.toJSON());
    };
    peer.ontrack = (event) => {
      const stream = event.streams[0];
      if (stream) this.set({ remote: stream });
    };
    peer.onconnectionstatechange = () => {
      if (peer.connectionState === "failed") this.set({ notice: "network" });
    };
    this.peer = peer;
    return peer;
  }

  private addIce(candidate: RTCIceCandidateInit): void {
    if (!this.peer) return;
    if (!this.peer.remoteDescription) {
      this.pendingIce.push(candidate);
      return;
    }
    void this.peer.addIceCandidate(candidate).catch(() => undefined);
  }

  private flushIce(): void {
    const queue = this.pendingIce;
    this.pendingIce = [];
    for (const candidate of queue) this.addIce(candidate);
  }

  private handle(signal: { kind: string; payload: string }): void {
    let data: unknown;
    try {
      data = JSON.parse(signal.payload);
    } catch {
      return;
    }
    const peer = this.peer;
    if (!peer) return;
    if (signal.kind === "offer" && !this.state.caller) {
      void peer
        .setRemoteDescription(data as RTCSessionDescriptionInit)
        .then(() => {
          this.flushIce();
          return peer.createAnswer();
        })
        .then((answer) => peer.setLocalDescription(answer).then(() => this.send("answer", answer)))
        .catch(() => undefined);
    } else if (signal.kind === "answer" && this.state.caller) {
      void peer
        .setRemoteDescription(data as RTCSessionDescriptionInit)
        .then(() => this.flushIce())
        .catch(() => undefined);
    } else if (signal.kind === "ice") {
      this.addIce(data as RTCIceCandidateInit);
    }
  }

  private async pollSignals(): Promise<void> {
    const id = this.state.id;
    if (!id) return;
    let answer: CallSignals;
    try {
      answer = await api<CallSignals>(`/api/calls/${id}/signals/?after=${this.after}`);
    } catch {
      return;
    }
    // The call this was asked for is over or another one: nothing in the answer is for what is on the screen now.
    if (!answer.ok || this.state.id !== id) return;
    for (const signal of answer.signals ?? []) {
      this.after = Math.max(this.after, signal.id);
      this.handle(signal);
    }
    const status = answer.call?.status;
    if (status === "active" && this.state.phase !== "live") {
      this.stopRinging();
      if (this.giveUp) clearTimeout(this.giveUp);
      this.giveUp = null;
      this.set({ phase: "live", notice: "", answeredAt: answer.call.answered_at });
    }
    if (status && status !== "ringing" && status !== "active") {
      this.finish(status === "declined" ? "declined" : status === "missed" ? "no_answer" : "ended");
    }
  }

  /** Close everything this call opened - the peer, the microphone, the camera, the timers - and keep the words. */
  private cleanup(): void {
    this.stopTimers();
    if (this.linger) clearTimeout(this.linger);
    this.linger = null;
    if (this.peer) {
      try {
        this.peer.close();
      } catch {
        /* already closed */
      }
    }
    this.peer = null;
    for (const track of this.state.local?.getTracks() ?? []) track.stop();
    this.pendingIce = [];
    this.after = 0;
  }

  private finish(notice: Notice, detail = ""): void {
    this.cleanup();
    this.attempt += 1;
    this.set({ phase: "ended", id: 0, notice, detail, local: null, remote: null, muted: false, cameraOff: false, answeredAt: "" });
    this.linger = setTimeout(() => {
      this.linger = null;
      if (this.state.phase === "ended") this.set({ ...IDLE });
    }, notice || detail ? LINGER_MS : 0);
  }

  // -- placing one ------------------------------------------------------------------------------------------------

  /** Ring a colleague. Nothing happens while a call is on the screen. */
  async place(person: { userId: number; name: string; initials: string }, video: boolean): Promise<void> {
    if (this.busy) return;
    if (this.linger) clearTimeout(this.linger);
    this.linger = null;
    const attempt = ++this.attempt;
    this.set({ ...IDLE, phase: "starting", name: person.name, initials: person.initials, video, caller: true, notice: "opening_mic" });
    let local: MediaStream;
    try {
      local = await media(video);
    } catch {
      if (attempt === this.attempt) this.finish("mic_denied");
      return;
    }
    // Hung up while the browser was asking for the microphone: let it go.
    if (attempt !== this.attempt) {
      for (const track of local.getTracks()) track.stop();
      return;
    }
    this.set({ local });
    let started: CallStarted;
    try {
      started = await api<CallStarted>("/api/calls/start/", { form: { user: String(person.userId), video: video ? "1" : "" } });
    } catch (error) {
      if (attempt === this.attempt) this.finish("could_not_call", sentence(error));
      return;
    }
    if (attempt !== this.attempt) {
      // Hung up while the server was making the call: the call exists and nobody is on it.
      void api(`/api/calls/${started.call.id}/end/`, { form: { reason: "missed" } }).catch(() => undefined);
      return;
    }
    this.set({ id: started.call.id, phase: "ringing", notice: "ringing" });
    const peer = this.connect(started.ice, local);
    this.startRinging();
    this.poll = setInterval(() => void this.pollSignals(), SIGNAL_POLL_MS);
    this.giveUp = setTimeout(() => void this.hangUp("missed"), RING_SECONDS * 1000);
    try {
      const offer = await peer.createOffer();
      await peer.setLocalDescription(offer);
      this.send("offer", offer);
    } catch {
      if (attempt === this.attempt) void this.hangUp("missed");
    }
  }

  // -- taking one -------------------------------------------------------------------------------------------------

  /** The heartbeat says a call is ringing for this person. Said again every beat: what is already on the screen is left alone. */
  incoming(info: CallInfo | null): void {
    if (!info || this.busy || this.declined.has(info.id)) return;
    if (this.linger) clearTimeout(this.linger);
    this.linger = null;
    this.set({
      ...IDLE,
      phase: "incoming",
      id: info.id,
      name: info.from,
      initials: info.initials,
      video: info.video,
      caller: false,
      notice: info.video ? "incoming_video" : "incoming_voice",
    });
    this.startRinging();
    // Stop ringing if the caller gives up before this is answered.
    this.poll = setInterval(() => {
      if (this.state.phase !== "incoming") return;
      const id = this.state.id;
      void api<CallSignals>(`/api/calls/${id}/signals/?after=0`)
        .then((answer) => {
          const status = answer.call?.status;
          if (status && status !== "ringing" && this.state.phase === "incoming" && this.state.id === id) this.finish("missed");
        })
        .catch(() => undefined);
    }, RING_POLL_MS);
  }

  async answer(): Promise<void> {
    if (this.state.phase !== "incoming") return;
    const id = this.state.id;
    const video = this.state.video;
    const attempt = ++this.attempt;
    this.stopTimers();
    this.set({ phase: "connecting", notice: "connecting" });
    let local: MediaStream;
    try {
      local = await media(video);
    } catch {
      if (attempt === this.attempt) {
        await this.hangUp("declined");
        this.set({ notice: "mic_denied" });
      }
      return;
    }
    if (attempt !== this.attempt) {
      for (const track of local.getTracks()) track.stop();
      return;
    }
    this.set({ local });
    let answered: CallStarted;
    try {
      answered = await api<CallStarted>(`/api/calls/${id}/answer/`, { form: {} });
    } catch {
      if (attempt === this.attempt) this.finish("over");
      return;
    }
    if (attempt !== this.attempt) return;
    this.connect(answered.ice, local);
    this.set({ phase: "live", notice: "", answeredAt: answered.call.answered_at });
    this.poll = setInterval(() => void this.pollSignals(), SIGNAL_POLL_MS);
    void this.pollSignals();
  }

  // -- ending it --------------------------------------------------------------------------------------------------

  /**
   * Hang up, decline, or give up ringing: the server writes one line into the chat and tells the other end. `reason` is
   * `ended`, `declined` or `missed`; a declined call is remembered so the next beat does not ring it again.
   */
  async hangUp(reason: "ended" | "declined" | "missed"): Promise<void> {
    const { id, phase } = this.state;
    if (phase === "idle") return;
    if (!id) {
      // Still waiting for the microphone or the server: nothing to tell yet, and the attempt is dropped.
      this.finish("over");
      return;
    }
    if (reason === "declined") this.declined.add(id);
    const sent = api(`/api/calls/${id}/end/`, { form: { reason } }).catch(() => undefined);
    this.finish(reason === "declined" ? "declined_by_me" : "over");
    await sent;
  }

  /** The button on the screen: what it means depends on who is ringing whom. */
  async pressHangUp(): Promise<void> {
    const { phase, caller } = this.state;
    if (phase === "ended" || phase === "idle") {
      this.reset();
      return;
    }
    // Ringing at somebody who has not answered is a call given up (missed); ringing at this person is one turned down.
    const ringingHere = phase === "incoming" || (phase === "connecting" && !caller);
    await this.hangUp(ringingHere ? "declined" : phase === "ringing" || phase === "starting" ? "missed" : "ended");
  }

  toggleMute(): void {
    const tracks = this.state.local?.getAudioTracks() ?? [];
    if (tracks.length === 0) return;
    const on = tracks[0]!.enabled;
    for (const track of tracks) track.enabled = !on;
    this.set({ muted: on });
  }

  toggleCamera(): void {
    const tracks = this.state.local?.getVideoTracks() ?? [];
    if (tracks.length === 0) return;
    const on = tracks[0]!.enabled;
    for (const track of tracks) track.enabled = !on;
    this.set({ cameraOff: on });
  }

  /** The page is going away: tell the server, so the other end is not left talking to nobody. */
  leaving(csrf: string): void {
    const { id, phase } = this.state;
    if (!id || phase === "idle" || phase === "ended" || !navigator.sendBeacon) return;
    const data = new FormData();
    data.append("reason", phase === "live" ? "ended" : "missed");
    data.append("csrfmiddlewaretoken", csrf);
    navigator.sendBeacon(`/api/calls/${id}/end/`, data);
  }
}

/** The one engine of the page. */
export const calls = new CallEngine();
