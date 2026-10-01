import { describe, expect, it } from "vitest";
import { safeInternalPath } from "./safeUrl";

const ORIGIN = "https://eagle.example";

describe("safeInternalPath", () => {
  it("keeps a path on this site, with its query and hash", () => {
    expect(safeInternalPath("/tasks/TSK-00001/?room=3", ORIGIN)).toBe("/tasks/TSK-00001/?room=3");
    expect(safeInternalPath("/ops/chats/g/12/#end", ORIGIN)).toBe("/ops/chats/g/12/#end");
  });

  it("refuses a path whose dot-segments turn it into another site", () => {
    for (const bad of [
      "/.//evil.example/x",
      "/..//evil.example",
      "/a/..//evil.example",
      "/%2e//evil.example",
      "/%2E//evil.example",
      "/%2e%2e//evil.example",
      "/a/%2e%2e//evil.example",
      "/ok/../..//evil.example/p?q=1#h",
    ]) {
      expect(safeInternalPath(bad, ORIGIN), bad).toBeNull();
    }
  });

  it("still resolves honest dot-segments", () => {
    expect(safeInternalPath("/a/../tasks/TSK-1/", ORIGIN)).toBe("/tasks/TSK-1/");
    expect(safeInternalPath("/./tasks/", ORIGIN)).toBe("/tasks/");
  });

  it("refuses everything that is not a plain path on this site", () => {
    for (const bad of [
      "",
      "https://evil.example/x",
      "http://eagle.example/x",
      "//evil.example/x",
      "///evil.example",
      "javascript:alert(1)",
      "JaVaScRiPt:alert(1)",
      "data:text/html,<script>1</script>",
      "tasks/relative",
      "/\\evil.example",
      "\\\\evil.example",
      "/ok\nHost: evil",
      "/tab\there",
      " /leading-space",
    ]) {
      expect(safeInternalPath(bad, ORIGIN), JSON.stringify(bad)).toBeNull();
    }
  });
});
