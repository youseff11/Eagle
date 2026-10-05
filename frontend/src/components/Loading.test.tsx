import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PreferencesProvider } from "../i18n/Preferences";
import { Loading, LOADING_DELAY_MS } from "./Loading";

afterEach(() => vi.useRealTimers());

const draw = () =>
  render(
    <PreferencesProvider initialLang="ar" initialTheme="dark">
      <Loading className="card empty" />
    </PreferencesProvider>,
  );

describe("Loading", () => {
  it("draws nothing at first: a page that opens at once never flashes it", () => {
    vi.useFakeTimers();
    const { container } = draw();
    expect(container.querySelector(".empty")).toBeNull();
    act(() => void vi.advanceTimersByTime(LOADING_DELAY_MS - 50));
    expect(container.querySelector(".empty")).toBeNull();
  });

  it("shows a quiet turning mark after the delay, with its words only for a screen reader", () => {
    vi.useFakeTimers();
    const { container } = draw();
    act(() => void vi.advanceTimersByTime(LOADING_DELAY_MS + 10));
    const mark = container.querySelector(".empty") as HTMLElement;
    expect(mark).toHaveAttribute("role", "status");
    expect(mark.querySelector("svg.spin")).not.toBeNull();
    expect(screen.getByText("بيحمّل...")).toHaveClass("sr-only");
  });

  it("goes away without a trace if the page is gone before the delay", () => {
    vi.useFakeTimers();
    const { unmount } = draw();
    unmount();
    expect(() => act(() => void vi.advanceTimersByTime(LOADING_DELAY_MS * 2))).not.toThrow();
  });
});
