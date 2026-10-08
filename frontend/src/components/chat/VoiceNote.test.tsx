import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PreferencesProvider } from "../../i18n/Preferences";
import { VoiceNote } from "./VoiceNote";

/** A note as the page draws it, and its <audio>: jsdom plays nothing, so what the browser would learn is told to it. */
function draw(length: string, url = "/files/in/note.ogg", lang: "ar" | "en" = "ar") {
  const view = render(
    <PreferencesProvider initialLang={lang} initialTheme="dark">
      <VoiceNote url={url} length={length} />
    </PreferencesProvider>,
  );
  const audio = view.container.querySelector("audio") as HTMLAudioElement;
  const time = () => view.container.querySelector(".voice__time")!.textContent;
  const knows = (duration: number) => {
    Object.defineProperty(audio, "duration", { configurable: true, value: duration });
    fireEvent(audio, new Event("loadedmetadata"));
  };
  return { ...view, audio, time, knows };
}

/** A note whose place can be read and put, as the browser's can: the bar is 200px wide, from 100px to 300px. */
function placed(length: string, lang: "ar" | "en" = "ar") {
  const note = draw(length, "/files/in/note.ogg", lang);
  const moved: number[] = [];
  let at = 0;
  Object.defineProperty(note.audio, "currentTime", {
    configurable: true,
    get: () => at,
    set: (value: number) => {
      at = value;
      moved.push(value);
    },
  });
  const bar = note.container.querySelector(".voice__bar") as HTMLElement;
  bar.getBoundingClientRect = () => ({ left: 100, right: 300, width: 200, top: 0, bottom: 4, height: 4, x: 100, y: 0, toJSON: () => ({}) });
  /** The sound plays on: the browser says where it has got to. */
  const plays = (seconds: number) => {
    at = seconds;
    fireEvent(note.audio, new Event("play"));
    fireEvent(note.audio, new Event("timeupdate"));
  };
  return { ...note, bar, moved, plays, at: () => at };
}

describe("the length of a voice note", () => {
  it("is the server's when it has one, and the file does not change it", () => {
    const note = draw("0:07");
    expect(note.time()).toBe("0:07");
    note.knows(83.4);
    expect(note.time()).toBe("0:07");
  });

  it("is read from the file when the server has none, and not a wrong 0:00 before that", () => {
    const note = draw("");
    expect(note.time()).toBe("--:--");
    expect(screen.queryByText("0:00")).not.toBeInTheDocument();
    note.knows(83.4);
    expect(note.time()).toBe("1:23");
  });

  it("rounds to the nearest second and keeps minutes for a long note", () => {
    const note = draw("");
    note.knows(3599.6);
    expect(note.time()).toBe("60:00");
  });

  it("finds the length of a file whose header has none, by asking for a place past its end", () => {
    const note = draw("");
    let at = 0;
    Object.defineProperty(note.audio, "currentTime", { configurable: true, get: () => at, set: (value: number) => (at = value) });
    note.knows(Infinity);
    expect(at).toBe(1e101);
    expect(note.time()).toBe("--:--");
    // The browser has read to the end and now knows.
    Object.defineProperty(note.audio, "duration", { configurable: true, value: 12.2 });
    fireEvent(note.audio, new Event("timeupdate"));
    expect(note.time()).toBe("0:12");
    expect(at).toBe(0);
  });

  it("asks for that place once, however many times the browser says the length changed", () => {
    const note = draw("");
    const asked: number[] = [];
    Object.defineProperty(note.audio, "currentTime", { configurable: true, get: () => 0, set: (value: number) => asked.push(value) });
    note.knows(Infinity);
    fireEvent(note.audio, new Event("durationchange"));
    fireEvent(note.audio, new Event("durationchange"));
    expect(asked).toEqual([1e101]);
  });

  it("starts again for another file", () => {
    const note = draw("");
    note.knows(30);
    expect(note.time()).toBe("0:30");
    note.rerender(
      <PreferencesProvider initialLang="ar" initialTheme="dark">
        <VoiceNote url="/files/in/other.ogg" length="" />
      </PreferencesProvider>,
    );
    expect(note.time()).toBe("--:--");
  });
});

describe("moving inside a voice note", () => {
  it("puts it where the bar is touched, counted from the right in Arabic", () => {
    const note = placed("1:40");
    note.knows(100);
    // 250px is three quarters of the way from the left, a quarter of the way from the right.
    fireEvent.pointerDown(note.bar, { clientX: 250, pointerId: 1 });
    fireEvent.pointerUp(note.bar, { clientX: 250, pointerId: 1 });
    expect(note.at()).toBeCloseTo(25, 5);
    expect(note.bar).toHaveAttribute("aria-valuenow", "25");
  });

  it("puts it where the bar is touched, counted from the left in English", () => {
    const note = placed("1:40", "en");
    note.knows(100);
    fireEvent.pointerDown(note.bar, { clientX: 250, pointerId: 1 });
    fireEvent.pointerUp(note.bar, { clientX: 250, pointerId: 1 });
    expect(note.at()).toBeCloseTo(75, 5);
  });

  it("follows a drag and moves the sound once, where the finger is let go", () => {
    const note = placed("1:40", "en");
    note.knows(100);
    fireEvent.pointerDown(note.bar, { clientX: 120, pointerId: 1 });
    expect(note.container.querySelector(".voice")).toHaveClass("is-dragging");
    fireEvent.pointerMove(note.bar, { clientX: 200, pointerId: 1 });
    // What is shown follows the finger, the sound does not move yet.
    expect(note.bar).toHaveAttribute("aria-valuenow", "50");
    expect(note.moved).toEqual([]);
    fireEvent.pointerUp(note.bar, { clientX: 280, pointerId: 1 });
    expect(note.moved).toEqual([90]);
    expect(note.container.querySelector(".voice")).not.toHaveClass("is-dragging");
  });

  it("is not carried off by what the player says while a finger is on the bar", () => {
    const note = placed("1:40", "en");
    note.knows(100);
    fireEvent.pointerDown(note.bar, { clientX: 200, pointerId: 1 });
    note.plays(3);
    expect(note.bar).toHaveAttribute("aria-valuenow", "50");
  });

  it("stays where it was when the finger is taken away", () => {
    const note = placed("1:40", "en");
    note.knows(100);
    note.plays(12);
    fireEvent.pointerDown(note.bar, { clientX: 280, pointerId: 1 });
    fireEvent.pointerCancel(note.bar, { pointerId: 1 });
    expect(note.moved).toEqual([]);
    expect(note.bar).toHaveAttribute("aria-valuenow", "12");
  });

  it("keeps clear of the very end, which would end it and start it over", () => {
    const note = placed("1:40", "en");
    note.knows(100);
    fireEvent.pointerDown(note.bar, { clientX: 400, pointerId: 1 });
    fireEvent.pointerUp(note.bar, { clientX: 400, pointerId: 1 });
    expect(note.at()).toBeLessThan(100);
    expect(note.at()).toBeGreaterThan(99);
    fireEvent.pointerDown(note.bar, { clientX: -50, pointerId: 1 });
    fireEvent.pointerUp(note.bar, { clientX: -50, pointerId: 1 });
    expect(note.at()).toBe(0);
  });

  it("does not move a note whose length nobody knows yet", () => {
    const note = placed("");
    expect(note.bar).toHaveAttribute("aria-disabled", "true");
    expect(note.bar).toHaveAttribute("tabindex", "-1");
    fireEvent.pointerDown(note.bar, { clientX: 250, pointerId: 1 });
    fireEvent.pointerUp(note.bar, { clientX: 250, pointerId: 1 });
    expect(note.moved).toEqual([]);
  });

  it("moves by the server's length when the file has not said its own", () => {
    const note = placed("0:40", "en");
    fireEvent.pointerDown(note.bar, { clientX: 200, pointerId: 1 });
    fireEvent.pointerUp(note.bar, { clientX: 200, pointerId: 1 });
    expect(note.at()).toBe(20);
  });

  it("is moved by the arrow keys, five seconds at a time, the way the bar fills", () => {
    const rtl = placed("1:40");
    rtl.knows(100);
    rtl.plays(30);
    fireEvent.keyDown(rtl.bar, { key: "ArrowLeft" });
    expect(rtl.at()).toBe(35);
    fireEvent.keyDown(rtl.bar, { key: "ArrowRight" });
    expect(rtl.at()).toBe(30);
    fireEvent.keyDown(rtl.bar, { key: "Home" });
    expect(rtl.at()).toBe(0);
    fireEvent.keyDown(rtl.bar, { key: "End" });
    expect(rtl.at()).toBeGreaterThan(99);
    rtl.unmount();

    const ltr = placed("1:40", "en");
    ltr.knows(100);
    ltr.plays(30);
    fireEvent.keyDown(ltr.bar, { key: "ArrowRight" });
    expect(ltr.at()).toBe(35);
    fireEvent.keyDown(ltr.bar, { key: "ArrowLeft" });
    fireEvent.keyDown(ltr.bar, { key: "ArrowLeft" });
    expect(ltr.at()).toBe(25);
  });

  it("does not go before its start with the keys", () => {
    const note = placed("1:40", "en");
    note.knows(100);
    note.plays(2);
    fireEvent.keyDown(note.bar, { key: "ArrowLeft" });
    expect(note.at()).toBe(0);
  });

  it("says where it is and how long it is to a screen reader", () => {
    const note = placed("1:40", "en");
    note.knows(100);
    note.plays(65);
    expect(note.bar).toHaveAttribute("role", "slider");
    expect(note.bar).toHaveAttribute("aria-valuemax", "100");
    expect(note.bar).toHaveAttribute("aria-valuetext", "1:05 / 1:40");
  });
});

describe("what a voice note shows while it is heard", () => {
  it("shows how far it has got, and its length when it is not playing", () => {
    const note = placed("1:40");
    note.knows(100);
    expect(note.time()).toBe("1:40");
    note.plays(65);
    expect(note.time()).toBe("1:05");
    fireEvent(note.audio, new Event("ended"));
    expect(note.time()).toBe("1:40");
  });

  it("keeps its length to be read on the time", () => {
    const note = placed("1:40");
    note.knows(100);
    note.plays(65);
    expect(note.container.querySelector(".voice__time")).toHaveAttribute("title", "1:40");
  });

  it("does not show a place that is only the browser looking for the end of the file", () => {
    const note = placed("");
    note.knows(Infinity);
    expect(note.moved).toEqual([1e101]);
    // On its way to the end, the browser says where it is: that is not where the note is.
    Object.defineProperty(note.audio, "currentTime", { configurable: true, get: () => 1e101, set: () => undefined });
    fireEvent(note.audio, new Event("timeupdate"));
    expect(note.bar).toHaveAttribute("aria-valuenow", "0");
  });

  it("finds the length of a file with none in its header even when the server has given one, so it can be moved in", () => {
    const note = placed("0:12", "en");
    note.knows(Infinity);
    expect(note.moved).toEqual([1e101]);
    Object.defineProperty(note.audio, "duration", { configurable: true, value: 11.6 });
    fireEvent(note.audio, new Event("timeupdate"));
    // The server's length is still what is written.
    expect(note.time()).toBe("0:12");
    expect(note.bar).toHaveAttribute("aria-valuemax", "12");
  });
});

describe("the speed of a voice note", () => {
  const rateOf = (note: ReturnType<typeof draw>) => note.container.querySelector(".voice__rate") as HTMLButtonElement;

  it("starts at the normal speed", () => {
    const note = draw("0:07");
    expect(rateOf(note).textContent).toBe("1×");
    expect(note.audio.playbackRate).toBe(1);
    expect(rateOf(note)).not.toHaveClass("is-fast");
  });

  it("goes 1.5 times, twice, and back to the normal speed, on the sound itself", () => {
    const note = draw("0:07");
    const button = rateOf(note);
    fireEvent.click(button);
    expect(button.textContent).toBe("1.5×");
    expect(note.audio.playbackRate).toBe(1.5);
    expect(note.audio.defaultPlaybackRate).toBe(1.5);
    expect(button).toHaveClass("is-fast");
    fireEvent.click(button);
    expect(button.textContent).toBe("2×");
    expect(note.audio.playbackRate).toBe(2);
    fireEvent.click(button);
    expect(button.textContent).toBe("1×");
    expect(note.audio.playbackRate).toBe(1);
    expect(button).not.toHaveClass("is-fast");
  });

  it("is named with its value for a screen reader", () => {
    const note = draw("0:07");
    fireEvent.click(rateOf(note));
    expect(rateOf(note)).toHaveAttribute("aria-label", "السرعة 1.5×");
  });

  it("keeps its speed while it is heard, and does not restart the sound to change it", () => {
    const note = placed("0:07");
    fireEvent.click(rateOf(note));
    note.plays(3);
    fireEvent.click(rateOf(note));
    expect(note.audio.playbackRate).toBe(2);
    expect(note.at()).toBe(3);
    expect(note.moved).toEqual([]);
  });
});
