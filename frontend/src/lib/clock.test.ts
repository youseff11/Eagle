import { describe, expect, it } from "vitest";
import { cairoClock, cairoToday, clockText, listStamp } from "./clock";

describe("clockText", () => {
  it("writes AM and PM in Arabic as in English: the right-to-left rule would reorder a time with Arabic markers", () => {
    expect(clockText("5:30 PM", "ar")).toBe("5:30 PM");
    expect(clockText("9:00 AM", "ar")).toBe("9:00 AM");
    expect(clockText("5:30 PM", "en")).toBe("5:30 PM");
  });

  it("does not touch a time that already says ص or م (it is the server's word)", () => {
    expect(clockText("5:30 م", "ar")).toBe("5:30 م");
  });
});

describe("listStamp", () => {
  // Sunday 18 October 2026, one in the afternoon in Cairo.
  const now = new Date("2026-10-18T10:00:00Z");

  it("says the time for a conversation that moved today", () => {
    expect(listStamp("5:20 PM", "2026-10-18", "ar", now)).toBe("5:20 PM");
    expect(listStamp("5:20 PM", "2026-10-18", "en", now)).toBe("5:20 PM");
  });

  it("says yesterday for yesterday, in the reader's language", () => {
    expect(listStamp("4:51 PM", "2026-10-17", "ar", now)).toBe("أمس");
    expect(listStamp("4:51 PM", "2026-10-17", "en", now)).toBe("Yesterday");
  });

  it("says the weekday within the week", () => {
    expect(listStamp("2:08 PM", "2026-10-14", "ar", now)).toBe("الأربعاء");
    expect(listStamp("2:08 PM", "2026-10-14", "en", now)).toBe("Wednesday");
    expect(listStamp("2:08 PM", "2026-10-12", "en", now)).toBe("Monday");
  });

  it("says the date once it is a week old, with the year only for another year", () => {
    expect(listStamp("2:08 PM", "2026-10-11", "en", now)).toBe("11/10");
    expect(listStamp("2:08 PM", "2026-09-27", "ar", now)).toBe("27/9");
    expect(listStamp("2:08 PM", "2025-11-27", "ar", now)).toBe("27/11/2025");
  });

  it("counts the day in Cairo, not on the computer's own clock", () => {
    // 22:30 UTC on the 17th is already the 18th in Cairo: a message of the 17th is yesterday's there.
    const lateNight = new Date("2026-10-17T22:30:00Z");
    expect(cairoToday(lateNight)).toBe("2026-10-18");
    expect(listStamp("9:00 PM", "2026-10-17", "en", lateNight)).toBe("Yesterday");
  });

  it("falls back to the time without a date the server wrote", () => {
    expect(listStamp("5:20 PM", "", "en", now)).toBe("5:20 PM");
    expect(listStamp("5:20 PM", "not a date", "en", now)).toBe("5:20 PM");
  });
});

describe("cairoClock", () => {
  it("says Cairo time on a twelve-hour clock with AM or PM in both languages", () => {
    const noon = new Date("2026-10-06T12:30:00Z");
    for (const lang of ["ar", "en"] as const) {
      const text = cairoClock(noon, lang);
      expect(text).toMatch(/^\d{1,2}:\d{2} (AM|PM)$/);
      expect(text).not.toMatch(/[ص م]$/);
    }
  });
});
