import { describe, expect, it } from "vitest";
import { deadlineLeft } from "./timeLeft";

const ar = (a: string) => a;
const en = (_a: string, e: string) => e;
const NOW = Date.parse("2026-10-02T12:00:00Z");
const at = (minutes: number) => new Date(NOW + minutes * 60000).toISOString();

describe("deadlineLeft", () => {
  it("says days and hours when there are whole days, and no minutes", () => {
    expect(deadlineLeft(at(2 * 1440 + 3 * 60 + 7), NOW, ar)).toEqual({ late: false, text: "باقي 2 يوم و3 ساعة على الديدلاين" });
  });

  it("says hours and minutes under a day", () => {
    expect(deadlineLeft(at(5 * 60 + 30), NOW, ar).text).toBe("باقي 5 ساعة و30 دقيقة على الديدلاين");
  });

  it("says only minutes under an hour, and 0 minutes for an exact hour boundary the way the classic page does", () => {
    expect(deadlineLeft(at(45), NOW, ar).text).toBe("باقي 45 دقيقة على الديدلاين");
    expect(deadlineLeft(at(0), NOW, ar).text).toBe("باقي 0 دقيقة على الديدلاين");
    // Exactly 2 hours: nothing to add about minutes.
    expect(deadlineLeft(at(120), NOW, ar).text).toBe("باقي 2 ساعة على الديدلاين");
  });

  it("says how late it already is, in the same parts", () => {
    expect(deadlineLeft(at(-(1440 + 120)), NOW, ar)).toEqual({ late: true, text: "الديدلاين فات من 1 يوم و2 ساعة" });
    expect(deadlineLeft(at(-10), NOW, ar).text).toBe("الديدلاين فات من 10 دقيقة");
  });

  it("writes English with plurals", () => {
    expect(deadlineLeft(at(1440 + 60), NOW, en).text).toBe("1 day 1 hour left until the deadline");
    expect(deadlineLeft(at(2 * 1440 + 2 * 60), NOW, en).text).toBe("2 days 2 hours left until the deadline");
    expect(deadlineLeft(at(1), NOW, en).text).toBe("1 minute left until the deadline");
    expect(deadlineLeft(at(-90), NOW, en)).toEqual({ late: true, text: "Deadline passed 1 hour 30 minutes ago" });
  });

  it("says nothing for no deadline or one that is not a time", () => {
    expect(deadlineLeft("", NOW, ar)).toEqual({ text: "", late: false });
    expect(deadlineLeft("not a date", NOW, ar)).toEqual({ text: "", late: false });
  });
});
