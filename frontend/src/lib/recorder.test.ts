import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { formatSeconds, RecorderError, recordingSupported, startRecording } from "./recorder";

/** A MediaRecorder that records nothing: what the page does with it is what is tested. */
class FakeRecorder {
  static supported = new Set<string>();
  static failToCreate = false;
  static created: FakeRecorder[] = [];
  static isTypeSupported(mime: string): boolean {
    if (mime === "audio/throws") throw new Error("old browser");
    return FakeRecorder.supported.has(mime);
  }

  state: "inactive" | "recording" = "inactive";
  mimeType: string;
  chunks: Blob[] = [];
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  stopCalls = 0;

  constructor(
    readonly stream: FakeStream,
    options?: { mimeType?: string },
  ) {
    if (FakeRecorder.failToCreate) throw new Error("no recorder");
    this.mimeType = options?.mimeType ?? "";
    FakeRecorder.created.push(this);
  }

  start() {
    this.state = "recording";
  }

  /** What the browser says while it records. */
  hear(data: string) {
    this.ondataavailable?.({ data: new Blob([data]) });
  }

  stop() {
    this.stopCalls += 1;
    this.state = "inactive";
    this.onstop?.();
  }
}

class FakeTrack {
  stopped = false;
  stop() {
    this.stopped = true;
  }
}

class FakeStream {
  tracks = [new FakeTrack(), new FakeTrack()];
  getTracks() {
    return this.tracks;
  }
}

let streams: FakeStream[] = [];

function microphone(behaviour: "allow" | { name: string } = "allow") {
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: vi.fn(async () => {
        if (behaviour !== "allow") throw Object.assign(new Error("no"), { name: behaviour.name });
        const stream = new FakeStream();
        streams.push(stream);
        return stream;
      }),
    },
  });
}

beforeEach(() => {
  FakeRecorder.supported = new Set(["audio/webm"]);
  FakeRecorder.failToCreate = false;
  FakeRecorder.created = [];
  streams = [];
  vi.stubGlobal("MediaRecorder", FakeRecorder);
  microphone();
});
afterEach(() => {
  vi.unstubAllGlobals();
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: undefined });
});

describe("formatSeconds", () => {
  it("writes minutes and seconds like a player", () => {
    expect([0, 7, 59, 60, 61, 300, 3599.9].map(formatSeconds)).toEqual(["0:00", "0:07", "0:59", "1:00", "1:01", "5:00", "59:59"]);
    expect(formatSeconds(-3)).toBe("0:00");
  });
});

describe("what the browser can record", () => {
  it("is nothing without a recorder or without a microphone to ask for", () => {
    expect(recordingSupported()).toBe(true);
    vi.unstubAllGlobals();
    expect(recordingSupported()).toBe(false);
    vi.stubGlobal("MediaRecorder", FakeRecorder);
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: undefined });
    expect(recordingSupported()).toBe(false);
  });

  it("asks for the first format it says it can record, in the order WhatsApp likes them", async () => {
    FakeRecorder.supported = new Set(["audio/webm", "audio/mp4", "audio/ogg;codecs=opus"]);
    await startRecording();
    expect(FakeRecorder.created[0]!.mimeType).toBe("audio/ogg;codecs=opus");
    FakeRecorder.supported = new Set(["audio/webm;codecs=opus", "audio/webm"]);
    await startRecording();
    expect(FakeRecorder.created[1]!.mimeType).toBe("audio/webm;codecs=opus");
    FakeRecorder.supported = new Set(["audio/mp4"]);
    await startRecording();
    expect(FakeRecorder.created[2]!.mimeType).toBe("audio/mp4");
  });

  it("lets the browser choose when it will not say, and names the file by what it chose", async () => {
    FakeRecorder.supported = new Set();
    const recording = await startRecording();
    const recorder = FakeRecorder.created[0]!;
    expect(recorder.mimeType).toBe("");
    recorder.mimeType = "audio/ogg;codecs=opus";
    recorder.hear("sound");
    const taken = await recording.stop();
    expect(taken.extension).toBe(".ogg");
    expect(taken.blob.type).toBe("audio/ogg;codecs=opus");
  });
});

describe("starting", () => {
  it("says so when the browser cannot record at all", async () => {
    vi.unstubAllGlobals();
    await expect(startRecording()).rejects.toMatchObject({ code: "unsupported" });
  });

  it("says denied when the person, or the browser, says no to the microphone", async () => {
    for (const name of ["NotAllowedError", "SecurityError"]) {
      microphone({ name });
      await expect(startRecording(), name).rejects.toMatchObject({ code: "denied" });
    }
    expect(FakeRecorder.created).toHaveLength(0);
  });

  it("says failed for anything else - no microphone at all, one that is busy", async () => {
    for (const name of ["NotFoundError", "NotReadableError", "AbortError"]) {
      microphone({ name });
      await expect(startRecording(), name).rejects.toMatchObject({ code: "failed" });
    }
  });

  it("lets the microphone go if the recorder cannot be made", async () => {
    FakeRecorder.failToCreate = true;
    await expect(startRecording()).rejects.toBeInstanceOf(RecorderError);
    expect(streams[0]!.tracks.every((track) => track.stopped)).toBe(true);
  });
});

describe("stopping and dropping", () => {
  it("hands back what was heard, with the format it came in, and lets the microphone go", async () => {
    FakeRecorder.supported = new Set(["audio/mp4"]);
    const recording = await startRecording();
    const recorder = FakeRecorder.created[0]!;
    recorder.hear("one ");
    recorder.hear("two");
    recorder.hear("");
    const taken = await recording.stop();
    expect(taken.extension).toBe(".m4a");
    expect(taken.blob.size).toBe("one two".length);
    expect(streams[0]!.tracks.every((track) => track.stopped)).toBe(true);
  });

  it("knows the extension of each format it can be given, and the one it cannot name", async () => {
    for (const [mime, extension] of [
      ["audio/ogg;codecs=opus", ".ogg"],
      ["audio/mp4", ".m4a"],
      ["audio/webm;codecs=opus", ".webm"],
      ["audio/x-strange", ".webm"],
    ] as const) {
      FakeRecorder.supported = new Set([mime]);
      const recording = await startRecording();
      FakeRecorder.created.at(-1)!.hear("x");
      expect((await recording.stop()).extension, mime).toBe(extension);
    }
  });

  it("is a failure, not an empty note, when nothing was heard", async () => {
    const recording = await startRecording();
    await expect(recording.stop()).rejects.toMatchObject({ code: "failed" });
    expect(streams[0]!.tracks.every((track) => track.stopped)).toBe(true);
  });

  it("drops it: the recorder is stopped, the microphone let go, and nothing is reported", async () => {
    const recording = await startRecording();
    const recorder = FakeRecorder.created[0]!;
    const heard = vi.fn();
    recorder.hear("sound");
    recorder.onstop = heard;
    recording.cancel();
    expect(recorder.stopCalls).toBe(1);
    expect(heard).not.toHaveBeenCalled();
    expect(recorder.onstop).toBeNull();
    expect(recorder.ondataavailable).toBeNull();
    expect(streams[0]!.tracks.every((track) => track.stopped)).toBe(true);
  });

  it("can be dropped twice without a complaint", async () => {
    const recording = await startRecording();
    recording.cancel();
    expect(() => recording.cancel()).not.toThrow();
  });
});
