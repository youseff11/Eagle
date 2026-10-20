import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { celebrate } from "../lib/celebrate";
import * as sound from "../lib/chime";
import { renderWithProviders } from "../test/helpers";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { Celebration, STICKER } from "./Celebration";

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

// 20/10/2026: «لما حالة تتغير لـ تم التعاقد حط تسقيف واحتفال ... وصوت تشجيع».
describe("Celebration", () => {
  it("shows nothing until a contract is won, then the company, and plays the cheer", () => {
    const cheer = vi.spyOn(sound, "cheer").mockImplementation(() => undefined);
    renderWithProviders(<Celebration />);
    expect(screen.queryByText("مبروك! تعاقد جديد")).toBeNull();
    act(() => celebrate("Lingua GmbH"));
    expect(screen.getByRole("status")).toHaveTextContent("مبروك! تعاقد جديد");
    expect(screen.getByText("Lingua GmbH")).toBeInTheDocument();
    expect(screen.getByText("ايوا كدا يا معلم هو ده الشغل")).toBeInTheDocument();
    // The owner's sticker, from the file that is there.
    expect(screen.getByRole("status").querySelector("img")).toHaveAttribute("src", STICKER);
    expect(existsSync(resolve(__dirname, "../../..", STICKER.slice(1)))).toBe(true);
    expect(cheer).toHaveBeenCalledTimes(1);
  });

  it("goes by itself after a few seconds, or at once on a click", async () => {
    vi.spyOn(sound, "cheer").mockImplementation(() => undefined);
    vi.useFakeTimers();
    renderWithProviders(<Celebration />);
    act(() => celebrate("Lingua GmbH"));
    act(() => void vi.advanceTimersByTime(6000));
    expect(screen.queryByRole("status")).toBeNull();
    vi.useRealTimers();
    act(() => celebrate("Other AG"));
    await userEvent.setup().click(screen.getByRole("status"));
    expect(screen.queryByRole("status")).toBeNull();
  });
});
