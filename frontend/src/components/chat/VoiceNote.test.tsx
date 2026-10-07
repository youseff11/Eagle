import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PreferencesProvider } from "../../i18n/Preferences";
import { VoiceNote } from "./VoiceNote";

/** A note as the page draws it, and its <audio>: jsdom plays nothing, so what the browser would learn is told to it. */
function draw(length: string, url = "/files/in/note.ogg") {
  const view = render(
    <PreferencesProvider initialLang="ar" initialTheme="dark">
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
