import { vi } from "vitest";

/** A track of a fake stream: it can be switched off and stopped, and remembers that it was. */
export class FakeTrack {
  enabled = true;
  stopped = false;
  constructor(readonly kind: "audio" | "video") {}
  stop() {
    this.stopped = true;
  }
}

export class FakeStream {
  readonly tracks: FakeTrack[];
  constructor(video = false) {
    this.tracks = video ? [new FakeTrack("audio"), new FakeTrack("video")] : [new FakeTrack("audio")];
  }
  getTracks() {
    return this.tracks;
  }
  getAudioTracks() {
    return this.tracks.filter((track) => track.kind === "audio");
  }
  getVideoTracks() {
    return this.tracks.filter((track) => track.kind === "video");
  }
}

/** A peer connection that does nothing but remember what it was told, and lets a test play the network's part. */
export class FakePeer {
  static all: FakePeer[] = [];
  readonly added: FakeTrack[] = [];
  readonly iceAdded: unknown[] = [];
  remoteDescription: unknown = null;
  localDescription: unknown = null;
  closed = false;
  connectionState = "new";
  onicecandidate: ((event: { candidate: { toJSON: () => unknown } | null }) => void) | null = null;
  ontrack: ((event: { streams: unknown[] }) => void) | null = null;
  onconnectionstatechange: (() => void) | null = null;

  constructor(readonly config: unknown) {
    FakePeer.all.push(this);
  }
  addTrack(track: FakeTrack) {
    this.added.push(track);
  }
  async createOffer() {
    return { type: "offer", sdp: "offer-sdp" };
  }
  async createAnswer() {
    return { type: "answer", sdp: "answer-sdp" };
  }
  async setLocalDescription(description: unknown) {
    this.localDescription = description;
  }
  async setRemoteDescription(description: unknown) {
    this.remoteDescription = description;
  }
  async addIceCandidate(candidate: unknown) {
    this.iceAdded.push(candidate);
  }
  close() {
    this.closed = true;
  }
  /** The network found a path: this end has a candidate for the other. */
  emitCandidate(candidate: unknown) {
    this.onicecandidate?.({ candidate: { toJSON: () => candidate } });
  }
  emitTrack(stream: unknown) {
    this.ontrack?.({ streams: [stream] });
  }
  setState(state: string) {
    this.connectionState = state;
    this.onconnectionstatechange?.();
  }
}

export interface WebRtcHandles {
  /** What each `getUserMedia` was asked for, in order. */
  asked: { audio: unknown; video: unknown }[];
  /** The streams it handed out. */
  streams: FakeStream[];
  beacons: { url: string; data: FormData }[];
}

/**
 * The browser's part of a call, faked: a microphone (and a camera) that can be refused or slow, the peer connection, and
 * the beacon a page sends as it goes away. Returns what was asked of them.
 */
export function installWebRtc(options: { denied?: boolean; unsupported?: boolean; hold?: boolean } = {}): WebRtcHandles & { release: () => void } {
  FakePeer.all = [];
  const handles: WebRtcHandles = { asked: [], streams: [], beacons: [] };
  let release: () => void = () => undefined;
  const getUserMedia = vi.fn(async (constraints: { audio: unknown; video: unknown }) => {
    handles.asked.push(constraints);
    if (options.denied) throw new DOMException("denied", "NotAllowedError");
    const stream = new FakeStream(Boolean(constraints.video));
    handles.streams.push(stream);
    if (options.hold) await new Promise<void>((resolve) => (release = resolve));
    return stream as unknown as MediaStream;
  });
  vi.stubGlobal("navigator", {
    ...navigator,
    mediaDevices: options.unsupported ? undefined : { getUserMedia },
    sendBeacon: (url: string, data: FormData) => {
      handles.beacons.push({ url, data });
      return true;
    },
  });
  vi.stubGlobal("RTCPeerConnection", FakePeer);
  // The arrays are the ones the fakes write to: a test reads them as things happen.
  return { asked: handles.asked, streams: handles.streams, beacons: handles.beacons, release: () => release() };
}
