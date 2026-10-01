import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { RecorderError, startRecording, type Recording } from "../lib/recorder";
import { useVoiceRecorder } from "./useVoiceRecorder";

vi.mock("../lib/recorder", async (original) => ({
  ...(await original<typeof import("../lib/recorder")>()),
  startRecording: vi.fn(),
}));

const starting = vi.mocked(startRecording);

type FakeTake = Recording & { stop: Mock<Recording["stop"]>; cancel: Mock<Recording["cancel"]> };

function recording(extension = ".webm"): FakeTake {
  return {
    stop: vi.fn<Recording["stop"]>(async () => ({ blob: new Blob(["sound"], { type: "audio/webm" }), extension })),
    cancel: vi.fn<Recording["cancel"]>(),
  };
}

let addresses = 0;
const created = vi.fn();
const revoked = vi.fn();

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  addresses = 0;
  created.mockImplementation(() => `blob:take-${++addresses}`);
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: created, revokeObjectURL: revoked }));
  starting.mockReset();
});
afterEach(() => {
  vi.useRealTimers();
  created.mockReset();
  revoked.mockReset();
});

/** Start and let the microphone answer. */
async function begin(result: { current: ReturnType<typeof useVoiceRecorder> }, take = recording()) {
  starting.mockResolvedValueOnce(take);
  await act(async () => result.current.start());
  return take;
}

describe("recording", () => {
  it("is asked for, then runs with a clock that counts the seconds", async () => {
    const { result } = renderHook(() => useVoiceRecorder(300));
    expect(result.current.phase).toBe("idle");
    starting.mockResolvedValueOnce(recording());
    act(() => result.current.start());
    expect(result.current.phase).toBe("starting");
    await act(async () => Promise.resolve());
    expect(result.current.phase).toBe("recording");
    await act(async () => vi.advanceTimersByTime(5000));
    expect(result.current.seconds).toBe(5);
  });

  it("stops into a take that can be listened to, as long as it ran, with a playable address", async () => {
    const { result } = renderHook(() => useVoiceRecorder(300));
    const take = await begin(result);
    await act(async () => vi.advanceTimersByTime(7000));
    await act(async () => result.current.stop());
    expect(take.stop).toHaveBeenCalledTimes(1);
    expect(result.current.phase).toBe("ready");
    expect(result.current.seconds).toBe(7);
    expect(result.current.recorded).toMatchObject({ seconds: 7, extension: ".webm" });
    expect(result.current.url).toBe("blob:take-1");
    // The clock stops with the recording.
    await act(async () => vi.advanceTimersByTime(5000));
    expect(result.current.seconds).toBe(7);
  });

  it("is never shorter than a second, so a tap is still a note with a length", async () => {
    const { result } = renderHook(() => useVoiceRecorder(300));
    await begin(result);
    await act(async () => result.current.stop());
    expect(result.current.recorded?.seconds).toBe(1);
  });

  it("stops by itself when the time is up", async () => {
    const { result } = renderHook(() => useVoiceRecorder(3));
    const take = await begin(result);
    await act(async () => vi.advanceTimersByTime(3000));
    expect(take.stop).toHaveBeenCalledTimes(1);
    expect(result.current.phase).toBe("ready");
    expect(result.current.recorded?.seconds).toBe(3);
  });

  it("does not start a second one while one runs or while a take waits to be sent", async () => {
    const { result } = renderHook(() => useVoiceRecorder(300));
    await begin(result);
    act(() => result.current.start());
    expect(starting).toHaveBeenCalledTimes(1);
    await act(async () => result.current.stop());
    act(() => result.current.start());
    expect(starting).toHaveBeenCalledTimes(1);
    expect(result.current.phase).toBe("ready");
  });

  it("does not start twice when asked twice before the browser has answered", async () => {
    const { result } = renderHook(() => useVoiceRecorder(300));
    starting.mockResolvedValue(recording());
    act(() => {
      result.current.start();
      result.current.start();
    });
    await act(async () => Promise.resolve());
    expect(starting).toHaveBeenCalledTimes(1);
  });
});

describe("what goes wrong", () => {
  it("says why when the microphone was refused, and is ready to be asked again", async () => {
    const { result } = renderHook(() => useVoiceRecorder(300));
    starting.mockRejectedValueOnce(new RecorderError("denied"));
    await act(async () => result.current.start());
    expect(result.current.failure).toBe("denied");
    expect(result.current.phase).toBe("idle");
    await begin(result);
    expect(result.current.failure).toBe("");
    expect(result.current.phase).toBe("recording");
  });

  it("calls anything it cannot name a failure", async () => {
    const { result } = renderHook(() => useVoiceRecorder(300));
    starting.mockRejectedValueOnce(new Error("boom"));
    await act(async () => result.current.start());
    expect(result.current.failure).toBe("failed");
  });

  it("goes back to the start, with a failure, when what was recorded cannot be had", async () => {
    const { result } = renderHook(() => useVoiceRecorder(300));
    const take = await begin(result);
    take.stop.mockRejectedValueOnce(new RecorderError("failed"));
    await act(async () => result.current.stop());
    expect(result.current.failure).toBe("failed");
    expect(result.current.phase).toBe("idle");
    expect(result.current.recorded).toBeNull();
  });
});

describe("throwing it away", () => {
  it("drops a recording that is running: the microphone is let go and the clock stops", async () => {
    const { result } = renderHook(() => useVoiceRecorder(300));
    const take = await begin(result);
    await act(async () => vi.advanceTimersByTime(2000));
    act(() => result.current.discard());
    expect(take.cancel).toHaveBeenCalledTimes(1);
    expect(result.current.phase).toBe("idle");
    expect(result.current.seconds).toBe(0);
    await act(async () => vi.advanceTimersByTime(5000));
    expect(result.current.seconds).toBe(0);
  });

  it("drops a take: the address is let go, and a new one can be made", async () => {
    const { result } = renderHook(() => useVoiceRecorder(300));
    await begin(result);
    await act(async () => result.current.stop());
    act(() => result.current.discard());
    expect(revoked).toHaveBeenCalledWith("blob:take-1");
    expect(result.current).toMatchObject({ phase: "idle", recorded: null, url: "" });
    await begin(result);
    expect(result.current.phase).toBe("recording");
  });
});

describe("leaving", () => {
  it("lets the microphone go when the page is left while it records", async () => {
    const { result, unmount } = renderHook(() => useVoiceRecorder(300));
    const take = await begin(result);
    unmount();
    expect(take.cancel).toHaveBeenCalledTimes(1);
  });

  it("lets the address of a take go when the page is left", async () => {
    const { result, unmount } = renderHook(() => useVoiceRecorder(300));
    await begin(result);
    await act(async () => result.current.stop());
    unmount();
    expect(revoked).toHaveBeenCalledWith("blob:take-1");
  });

  it("lets the microphone go if the page was left while the browser was still asking for it", async () => {
    const { result, unmount } = renderHook(() => useVoiceRecorder(300));
    const take = recording();
    let answer: (value: Recording) => void = () => undefined;
    starting.mockReturnValueOnce(new Promise<Recording>((resolve) => (answer = resolve)));
    act(() => result.current.start());
    unmount();
    await act(async () => answer(take));
    expect(take.cancel).toHaveBeenCalledTimes(1);
  });

  it("makes no address for a take that arrives after the page was left", async () => {
    const { result, unmount } = renderHook(() => useVoiceRecorder(300));
    const take = await begin(result);
    let heard: (value: { blob: Blob; extension: string }) => void = () => undefined;
    take.stop.mockReturnValueOnce(new Promise((resolve) => (heard = resolve)));
    act(() => result.current.stop());
    unmount();
    await act(async () => heard({ blob: new Blob(["late"]), extension: ".webm" }));
    expect(created).not.toHaveBeenCalled();
  });
});
