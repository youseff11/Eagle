import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// A layout cannot be measured here (no screen), so what the phone needs is pinned where it is written: the rules that keep the
// top bar's seven controls, the two-column cards and the emoji panel inside a 320px screen. Measured once in a real browser at
// 392, 360 and 320px, in Arabic and in English.
const css = (path: string) => readFileSync(resolve(import.meta.dirname, "../../..", path), "utf-8");

describe("on a phone", () => {
  const styles = css("frontend/src/styles.css");

  it("fits the top bar's controls: smaller buttons, no divider, no live dot", () => {
    const block = /@media \(max-width: 480px\) \{([\s\S]*?)\n\}/.exec(styles)?.[1] ?? "";
    expect(block).toMatch(/\.topbar \.icon-btn \{ width: 34px; height: 34px; \}/);
    expect(block).toMatch(/\.topbar \.menu-toggle \{ width: 34px; height: 34px; \}/);
    expect(block).toMatch(/\.topbar__divider \{ display: none; \}/);
    expect(block).toMatch(/\.topbar \.realtime-dot \{ display: none; \}/);
    expect(block).toMatch(/\.topbar \{ padding-inline: 8px; gap: 4px; \}/);
  });

  it("lets a two-column grid shrink to the screen instead of pushing its cards off the edge", () => {
    expect(css("static/css/app.css")).toMatch(/\.grid--2 \{ grid-template-columns: repeat\(auto-fit, minmax\(min\(330px, 100%\), 1fr\)\); \}/);
  });

  it("stretches the emoji panel over the box it belongs to", () => {
    const block = /@media \(max-width: 760px\) \{([\s\S]*?)\n\}/.exec(styles)?.[1] ?? "";
    expect(block).toMatch(/\.emoji \{ position: static; \}/);
    expect(block).toMatch(/\.emoji__pop \{ inset-inline: 8px; width: auto;/);
  });
});
