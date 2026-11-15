import { describe, expect, it } from "vitest";
import { arabicTime, shiftHours, shiftName, shiftTitle } from "./shiftHours";

const nine = { ar: "9:00 AM", en: "9:00 AM" };
const five = { ar: "5:00 PM", en: "5:00 PM" };

describe("a shift's hours", () => {
  it("reads from and to with morning and evening words in Arabic", () => {
    expect(shiftHours(nine, five, "ar")).toBe("من 9:00 صباحًا إلى 5:00 مساءً");
    expect(arabicTime("12:30 am")).toBe("12:30 صباحًا");
  });

  it("keeps AM and PM in English", () => {
    expect(shiftHours(nine, five, "en")).toBe("9:00 AM – 5:00 PM");
  });

  it("has nothing to say without both ends", () => {
    expect(shiftHours(null, five, "ar")).toBe("—");
  });

  it("drops a name that is only the hours", () => {
    expect(shiftName("12:00 PM - 5:00 PM")).toBe("");
    expect(shiftName("الشيفت 1")).toBe("الشيفت 1");
    expect(shiftTitle("12:00 PM - 5:00 PM", nine, five, "ar")).toBe("من 9:00 صباحًا إلى 5:00 مساءً");
    expect(shiftTitle("شيفت صباحي", nine, five, "ar")).toBe("شيفت صباحي — من 9:00 صباحًا إلى 5:00 مساءً");
  });
});
