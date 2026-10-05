import { describe, expect, it } from "vitest";
import { cairoClock, clockText } from "./clock";

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
