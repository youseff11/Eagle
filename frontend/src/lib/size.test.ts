import { describe, expect, it } from "vitest";
import { filesProblem } from "../components/chat/Composer";
import { prettySize } from "./size";

describe("prettySize", () => {
  it("writes bytes, kilobytes and megabytes the way a person reads them", () => {
    expect(prettySize(0)).toBe("0 B");
    expect(prettySize(1023)).toBe("1023 B");
    expect(prettySize(1024)).toBe("1 KB");
    expect(prettySize(34 * 1024 + 300)).toBe("34 KB");
    expect(prettySize(1.5 * 1024 * 1024)).toBe("1.5 MB");
    expect(prettySize(25 * 1024 * 1024)).toBe("25 MB");
  });
});

describe("filesProblem", () => {
  const limits = { count: 2, bytes: 10, total_bytes: 15 };
  const file = (size: number) => new File(["x".repeat(size)], "f");

  it("is nothing for files within every limit, at the limit included", () => {
    expect(filesProblem([], limits)).toBe("");
    expect(filesProblem([file(10), file(5)], limits)).toBe("");
  });

  it("names the first limit that is broken: how many, how big, how big together", () => {
    expect(filesProblem([file(1), file(1), file(1)], limits)).toBe("count");
    expect(filesProblem([file(11)], limits)).toBe("big");
    expect(filesProblem([file(10), file(6)], limits)).toBe("total");
  });
});
