import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { armSound, chime, resetSound } from "./chime";

/** Just enough of WebAudio to count what was played. */
class FakeContext {
  static made: FakeContext[] = [];
  /** What a browser answers to `resume()`: a page nobody has touched stays suspended. */
  static allowed = true;
  state: "suspended" | "running" = "suspended";
  currentTime = 10;
  destination = {};
  oscillators: { hz: number; start: number }[] = [];
  resumes = 0;
  constructor() {
    FakeContext.made.push(this);
  }
  async resume() {
    this.resumes += 1;
    if (FakeContext.allowed) this.state = "running";
  }
  async close() {}
  createDynamicsCompressor() {
    return {
      threshold: { value: 0 },
      knee: { value: 0 },
      ratio: { value: 0 },
      attack: { value: 0 },
      release: { value: 0 },
      connect: vi.fn(),
    };
  }
  createGain() {
    const param = { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() };
    return { gain: param, connect: (next: unknown) => next };
  }
  createOscillator() {
    const record: { hz: number; start: number } = { hz: 0, start: 0 };
    this.oscillators.push(record);
    return {
      type: "sine",
      frequency: { setValueAtTime: (hz: number) => void (record.hz = hz) },
      connect: (next: unknown) => next,
      start: (at: number) => void (record.start = at),
      stop: vi.fn(),
    };
  }
}

beforeEach(() => {
  FakeContext.made = [];
  FakeContext.allowed = true;
  vi.stubGlobal("AudioContext", FakeContext);
});

afterEach(() => {
  resetSound();
  vi.unstubAllGlobals();
});

const gesture = (name = "pointerdown") => document.dispatchEvent(new Event(name, { bubbles: true }));
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("chime", () => {
  it("is silent, and makes no audio context, until the person has touched the page", () => {
    const stop = armSound();
    chime(2, 784);
    expect(FakeContext.made).toHaveLength(0);
    stop();
  });

  it("plays after the first click: two notes, each with an octave on top, per ring", async () => {
    const stop = armSound();
    gesture("pointerdown");
    await settle();
    expect(FakeContext.made).toHaveLength(1);

    chime(2, 784);
    const played = FakeContext.made[0]!.oscillators;
    // two rings x two notes x (note + octave)
    expect(played).toHaveLength(8);
    expect(played.map((o) => Math.round(o.hz))).toEqual([784, 1568, 1176, 2352, 784, 1568, 1176, 2352]);
    // the second ring starts 0.55 s after the first
    expect(played[4]!.start - played[0]!.start).toBeCloseTo(0.55, 5);
    stop();
  });

  it("a key press opens the sound too, and the listeners go once it is running", async () => {
    const stop = armSound();
    gesture("keydown");
    await settle();
    expect(FakeContext.made).toHaveLength(1);

    gesture("pointerdown");
    gesture("keydown");
    await settle();
    expect(FakeContext.made).toHaveLength(1);
    expect(FakeContext.made[0]!.resumes).toBe(1);
    stop();
  });

  it("stays quiet, and tries again at the next gesture, when the browser refused to start it", async () => {
    FakeContext.allowed = false;
    const stop = armSound();
    gesture();
    await settle();
    chime(1);
    expect(FakeContext.made[0]!.oscillators).toHaveLength(0);

    FakeContext.allowed = true;
    gesture();
    await settle();
    chime(1);
    expect(FakeContext.made).toHaveLength(1);
    expect(FakeContext.made[0]!.oscillators).toHaveLength(4);
    stop();
  });

  it("the soft chime is made of the same notes and does not throw without WebAudio", async () => {
    vi.stubGlobal("AudioContext", undefined);
    const stop = armSound();
    gesture();
    await settle();
    expect(() => chime(1, 988, true)).not.toThrow();
    stop();
  });

  it("stops listening when asked", async () => {
    const stop = armSound();
    stop();
    gesture();
    await settle();
    expect(FakeContext.made).toHaveLength(0);
  });
});
