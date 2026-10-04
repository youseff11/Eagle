import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { navigation } from "../lib/navigation";
import { jsonResponse } from "../test/helpers";
import { useHeartbeat } from "./useHeartbeat";

const PENDING = { id: 5, task_code: "TSK-00001", seconds_left: 59 };
let answer: unknown;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.useFakeTimers();
  answer = { ok: true, attendance: null, pending: null, call: null };
  fetchMock = vi.fn(async () => jsonResponse(answer));
  vi.stubGlobal("fetch", fetchMock);
  vi.spyOn(navigation, "assign").mockImplementation(() => undefined);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("useHeartbeat", () => {
  it("beats at once and then on the interval, asking for no notification rows", async () => {
    const { unmount } = renderHook(() => useHeartbeat(4000));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]![0])).toBe("/api/heartbeat/?after=9007199254740991");
    await vi.advanceTimersByTimeAsync(4000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    unmount();
    await vi.advanceTimersByTimeAsync(20_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("never beats faster than every three seconds", async () => {
    renderHook(() => useHeartbeat(100));
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(2900);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(100);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  describe("a call that is ringing", () => {
    const CALL = { id: 9, video: false, from: "Mona", initials: "MO", chat_url: "/ops/chats/u/4/" };

    it("keeps the person here and tells it, on every beat while it rings: this app rings it itself", async () => {
      const heard: unknown[] = [];
      answer = { ok: true, attendance: null, pending: null, call: CALL };
      renderHook(() => useHeartbeat(4000, undefined, undefined, undefined, (call) => heard.push(call)));
      await vi.advanceTimersByTimeAsync(0);
      await vi.advanceTimersByTimeAsync(4000);
      expect(navigation.assign).not.toHaveBeenCalled();
      expect(heard).toEqual([CALL, CALL]);
    });

    it("tells nothing is ringing once it is not", async () => {
      const heard: unknown[] = [];
      answer = { ok: true, attendance: null, pending: null, call: CALL };
      renderHook(() => useHeartbeat(4000, undefined, undefined, undefined, (call) => heard.push(call)));
      await vi.advanceTimersByTimeAsync(0);
      answer = { ok: true, attendance: null, pending: null, call: null };
      await vi.advanceTimersByTimeAsync(4000);
      expect(heard).toEqual([CALL, null]);
    });

    it("says nothing when a beat fails", async () => {
      const heard: unknown[] = [];
      answer = { ok: true, attendance: null, pending: null, call: CALL };
      renderHook(() => useHeartbeat(4000, undefined, undefined, undefined, (call) => heard.push(call)));
      await vi.advanceTimersByTimeAsync(0);
      fetchMock.mockImplementationOnce(async () => {
        throw new TypeError("network down");
      });
      await vi.advanceTimersByTimeAsync(4000);
      expect(heard).toEqual([CALL]);
    });

    it("does not stop the check-in screen from being told, and it does not send the person away", async () => {
      const gates: unknown[] = [];
      const calls: unknown[] = [];
      answer = { ok: true, attendance: { kind: "check_in" }, attendance_screen: true, pending: null, call: CALL };
      renderHook(() => useHeartbeat(4000, undefined, undefined, (gate) => gates.push(gate), (call) => calls.push(call)));
      await vi.advanceTimersByTimeAsync(0);
      expect(navigation.assign).not.toHaveBeenCalled();
      expect(gates).toEqual([{ kind: "check_in" }]);
      expect(calls).toEqual([CALL]);
    });

  });

  it("keeps the person here for an assignment waiting for an answer: this app draws the accept screen itself", async () => {
    answer = { ok: true, attendance: null, pending: PENDING, call: null };
    renderHook(() => useHeartbeat(4000));
    await vi.advanceTimersByTimeAsync(0);
    expect(navigation.assign).not.toHaveBeenCalled();
  });

  it("tells what each beat says about a hand-off: the hand-off, then nothing once it is gone", async () => {
    const heard: unknown[] = [];
    answer = { ok: true, attendance: null, pending: PENDING, call: null };
    renderHook(() => useHeartbeat(4000, undefined, (pending) => heard.push(pending)));
    await vi.advanceTimersByTimeAsync(0);
    expect(heard).toEqual([PENDING]);
    answer = { ok: true, attendance: null, pending: null, call: null };
    await vi.advanceTimersByTimeAsync(4000);
    expect(heard).toEqual([PENDING, null]);
  });

  it("says nothing about a hand-off when a beat fails, and leaves what was shown as it was", async () => {
    const heard: unknown[] = [];
    answer = { ok: true, attendance: null, pending: PENDING, call: null };
    renderHook(() => useHeartbeat(4000, undefined, (pending) => heard.push(pending)));
    await vi.advanceTimersByTimeAsync(0);
    fetchMock.mockImplementationOnce(async () => {
      throw new TypeError("network down");
    });
    await vi.advanceTimersByTimeAsync(4000);
    expect(heard).toEqual([PENDING]);
    await vi.advanceTimersByTimeAsync(4000);
    expect(heard).toEqual([PENDING, PENDING]);
  });

  describe("the check-in screen, when this app draws it", () => {
    const GATE = { kind: "check_in", date: "2026-09-21", shift: "Shift 1" };

    it("keeps the person here and tells what is asked, for each of the three kinds", async () => {
      for (const kind of ["check_in", "check_out", "extra"]) {
        vi.mocked(navigation.assign).mockClear();
        const heard: unknown[] = [];
        const gate = { ...GATE, kind };
        answer = { ok: true, attendance: gate, attendance_screen: true, pending: null, call: null };
        const { unmount } = renderHook(() => useHeartbeat(4000, undefined, undefined, (asked) => heard.push(asked)));
        await vi.advanceTimersByTimeAsync(0);
        expect(navigation.assign, kind).not.toHaveBeenCalled();
        expect(heard, kind).toEqual([gate]);
        unmount();
      }
    });

    it("tells nothing is asked once it is done, and what is asked again when it comes back", async () => {
      const heard: unknown[] = [];
      answer = { ok: true, attendance: GATE, attendance_screen: true, pending: null, call: null };
      renderHook(() => useHeartbeat(4000, undefined, undefined, (asked) => heard.push(asked)));
      await vi.advanceTimersByTimeAsync(0);
      answer = { ok: true, attendance: null, attendance_screen: true, pending: null, call: null };
      await vi.advanceTimersByTimeAsync(4000);
      answer = { ok: true, attendance: { ...GATE, kind: "check_out" }, attendance_screen: true, pending: null, call: null };
      await vi.advanceTimersByTimeAsync(4000);
      expect(heard).toEqual([GATE, null, { ...GATE, kind: "check_out" }]);
    });

    it("says nothing when a beat fails: the screen stays as it was until the next one tells the truth", async () => {
      const heard: unknown[] = [];
      answer = { ok: true, attendance: GATE, attendance_screen: true, pending: null, call: null };
      renderHook(() => useHeartbeat(4000, undefined, undefined, (asked) => heard.push(asked)));
      await vi.advanceTimersByTimeAsync(0);
      fetchMock.mockImplementationOnce(async () => {
        throw new TypeError("network down");
      });
      await vi.advanceTimersByTimeAsync(4000);
      expect(heard).toEqual([GATE]);
    });

    it("tells nothing is asked to a person whose screen is not drawn here and who owes nothing", async () => {
      const heard: unknown[] = [];
      answer = { ok: true, attendance: null, attendance_screen: false, pending: null, call: null };
      renderHook(() => useHeartbeat(4000, undefined, undefined, (asked) => heard.push(asked)));
      await vi.advanceTimersByTimeAsync(0);
      expect(heard).toEqual([null]);
      expect(navigation.assign).not.toHaveBeenCalled();
    });

  });

  it("does not start a second beat while the first is still waiting for its answer", async () => {
    let release: (value: Response) => void = () => undefined;
    fetchMock.mockImplementationOnce(() => new Promise<Response>((resolve) => (release = resolve)));
    renderHook(() => useHeartbeat(4000));
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(12_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    release(jsonResponse({ ok: true, attendance: null, pending: null, call: null }));
    await vi.advanceTimersByTimeAsync(4000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("stays put when nothing is due", async () => {
    renderHook(() => useHeartbeat(4000));
    await vi.advanceTimersByTimeAsync(4000);
    expect(navigation.assign).not.toHaveBeenCalled();
  });

  it("survives a failed beat and tries again", async () => {
    fetchMock.mockRejectedValueOnce(new Error("offline"));
    renderHook(() => useHeartbeat(4000));
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(4000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  describe("the boards fingerprint", () => {
    const beatWith = (live: string | undefined) => {
      answer = { ok: true, attendance: null, pending: null, call: null, ...(live === undefined ? {} : { live }) };
    };

    it("says nothing on the first answer and calls back when the value changes", async () => {
      const onLive = vi.fn();
      beatWith("aaa");
      renderHook(() => useHeartbeat(4000, onLive));
      await vi.advanceTimersByTimeAsync(0);
      expect(onLive).not.toHaveBeenCalled();

      await vi.advanceTimersByTimeAsync(4000);
      expect(onLive).not.toHaveBeenCalled(); // same value: nothing moved

      beatWith("bbb");
      await vi.advanceTimersByTimeAsync(4000);
      expect(onLive).toHaveBeenCalledTimes(1);

      await vi.advanceTimersByTimeAsync(4000);
      expect(onLive).toHaveBeenCalledTimes(1); // and only once per change
    });

    it("ignores an answer that carries no fingerprint", async () => {
      const onLive = vi.fn();
      beatWith("aaa");
      renderHook(() => useHeartbeat(4000, onLive));
      await vi.advanceTimersByTimeAsync(0);
      beatWith(undefined);
      await vi.advanceTimersByTimeAsync(4000);
      beatWith("aaa");
      await vi.advanceTimersByTimeAsync(4000);
      expect(onLive).not.toHaveBeenCalled();
    });

    it("uses the callback it was last given, without restarting the beat", async () => {
      const first = vi.fn();
      const second = vi.fn();
      beatWith("aaa");
      const { rerender } = renderHook(({ cb }) => useHeartbeat(4000, cb), { initialProps: { cb: first } });
      await vi.advanceTimersByTimeAsync(0);
      rerender({ cb: second });
      beatWith("bbb");
      await vi.advanceTimersByTimeAsync(4000);
      expect(first).not.toHaveBeenCalled();
      expect(second).toHaveBeenCalledTimes(1);
      expect(fetchMock).toHaveBeenCalledTimes(2); // no extra beat from the re-render
    });

  });
});
