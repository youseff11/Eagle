import { describe, expect, it } from "vitest";
import { lengthOfTime } from "./duration";

const ar = (a: string) => a;
const en = (_a: string, e: string) => e;

describe("lengthOfTime", () => {
  it("writes days, hours and minutes the way the classic page does", () => {
    expect(lengthOfTime(1530, ar)).toBe("1 يوم 1 ساعة 30 دقيقة");
    expect(lengthOfTime(90, ar)).toBe("1 ساعة 30 دقيقة");
    expect(lengthOfTime(45, ar)).toBe("45 دقيقة");
    expect(lengthOfTime(24 * 60 * 3, ar)).toBe("3 يوم");
  });

  it("writes it in English, with a plural for days", () => {
    expect(lengthOfTime(1530, en)).toBe("1 day 1 h 30 min");
    expect(lengthOfTime(2 * 24 * 60, en)).toBe("2 days");
  });

  it("leaves out what is zero, and says zero minutes for nothing at all", () => {
    expect(lengthOfTime(24 * 60 + 5, ar)).toBe("1 يوم 5 دقيقة");
    expect(lengthOfTime(0, ar)).toBe("0 دقيقة");
    expect(lengthOfTime(-5, en)).toBe("0 min");
    expect(lengthOfTime(Number.NaN, en)).toBe("0 min");
  });
});
