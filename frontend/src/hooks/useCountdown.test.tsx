import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useCountdown } from "./useCountdown";

beforeEach(() => vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] }));
afterEach(() => vi.useRealTimers());

describe("useCountdown", () => {
  it("counts down by itself once a second, from what the server said", () => {
    const { result } = renderHook(() => useCountdown(60, 1));
    expect(result.current).toBe(60);
    act(() => void vi.advanceTimersByTime(1000));
    expect(result.current).toBe(59);
    act(() => void vi.advanceTimersByTime(4000));
    expect(result.current).toBe(55);
  });

  it("stops at zero and never goes below it", () => {
    const { result } = renderHook(() => useCountdown(3, 1));
    act(() => void vi.advanceTimersByTime(10_000));
    expect(result.current).toBe(0);
  });

  it("has nothing to count while there is no number", () => {
    const { result } = renderHook(() => useCountdown(null, 1));
    expect(result.current).toBeNull();
  });

  it("keeps its own count when the server's number agrees to within a couple of seconds", () => {
    const { result, rerender } = renderHook(({ seconds }) => useCountdown(seconds, 1), { initialProps: { seconds: 60 } });
    act(() => void vi.advanceTimersByTime(10_000));
    expect(result.current).toBe(50);
    // The next beat says 49: a second of lag, not a reason to jump.
    rerender({ seconds: 49 });
    expect(result.current).toBe(50);
  });

  it("takes the server's word when the two disagree by more", () => {
    const { result, rerender } = renderHook(({ seconds }) => useCountdown(seconds, 1), { initialProps: { seconds: 60 } });
    act(() => void vi.advanceTimersByTime(10_000));
    // A page that slept: the browser's timers stopped, the server's clock did not.
    rerender({ seconds: 20 });
    expect(result.current).toBe(20);
    act(() => void vi.advanceTimersByTime(2000));
    expect(result.current).toBe(18);
  });

  it("starts again for another hand-off, and shows the server's number at once", () => {
    const { result, rerender } = renderHook(({ seconds, key }) => useCountdown(seconds, key), { initialProps: { seconds: 60, key: 1 } });
    act(() => void vi.advanceTimersByTime(30_000));
    expect(result.current).toBe(30);
    rerender({ seconds: 58, key: 2 });
    expect(result.current).toBe(58);
  });

  it("stops its timer when it is gone", () => {
    const { unmount } = renderHook(() => useCountdown(60, 1));
    expect(vi.getTimerCount()).toBe(1);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
