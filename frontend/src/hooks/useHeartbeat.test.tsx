import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { navigation } from "../lib/navigation";
import { jsonResponse } from "../test/helpers";
import { useHeartbeat } from "./useHeartbeat";

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

  it("sends the person to the classic interface when the check-in screen is due", async () => {
    answer = { ok: true, attendance: { kind: "check_in" }, pending: null, call: null };
    renderHook(() => useHeartbeat(4000));
    await vi.advanceTimersByTimeAsync(0);
    expect(navigation.assign).toHaveBeenCalledWith("/");
  });

  it("does the same for an assignment waiting for an answer, and for a ringing call", async () => {
    for (const waiting of [
      { ok: true, attendance: null, pending: { id: 5, task: "TSK-00001" }, call: null },
      { ok: true, attendance: null, pending: null, call: { id: 9, from: "Mona" } },
    ]) {
      vi.mocked(navigation.assign).mockClear();
      answer = waiting;
      const { unmount } = renderHook(() => useHeartbeat(4000));
      await vi.advanceTimersByTimeAsync(0);
      expect(navigation.assign, JSON.stringify(waiting)).toHaveBeenCalledWith("/");
      unmount();
    }
  });

  it("does not send anyone away for the reminders that can be put off", async () => {
    for (const kind of ["check_out", "extra"]) {
      answer = { ok: true, attendance: { kind }, pending: null, call: null };
      const { unmount } = renderHook(() => useHeartbeat(4000));
      await vi.advanceTimersByTimeAsync(0);
      unmount();
    }
    expect(navigation.assign).not.toHaveBeenCalled();
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
});
