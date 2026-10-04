import { describe, expect, it } from "vitest";
import { hasMoney, minutesHm } from "./payroll";

describe("hasMoney", () => {
  it("is false for nothing and true for any amount, a negative one included: it must be seen", () => {
    expect(hasMoney("0.00")).toBe(false);
    expect(hasMoney("")).toBe(false);
    expect(hasMoney("1500.00")).toBe(true);
    expect(hasMoney("-1000.00")).toBe(true);
  });

  it("is false for a word that is not a number", () => {
    expect(hasMoney("abc")).toBe(false);
  });
});

describe("minutesHm", () => {
  it("writes minutes as hours and minutes", () => {
    expect(minutesHm(126)).toBe("2:06");
    expect(minutesHm(0)).toBe("0:00");
    expect(minutesHm(-90)).toBe("-1:30");
  });
});
