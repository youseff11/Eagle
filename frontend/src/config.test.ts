import { describe, expect, it } from "vitest";
import { readConfig } from "./config";

function page(config?: string, attrs: { lang?: string; theme?: string } = {}): Document {
  const doc = document.implementation.createHTMLDocument("t");
  if (attrs.lang) doc.documentElement.lang = attrs.lang;
  if (attrs.theme) doc.documentElement.dataset.theme = attrs.theme;
  if (config !== undefined) {
    const node = doc.createElement("script");
    node.id = "app-config";
    node.type = "application/json";
    node.textContent = config;
    doc.body.appendChild(node);
  }
  return doc;
}

describe("readConfig", () => {
  it("reads what the server page wrote", () => {
    expect(readConfig(page('{"lang":"en","theme":"light","pollMs":2500}'))).toEqual({
      lang: "en",
      theme: "light",
      pollMs: 2500,
      gate: null,
    });
  });

  it("falls back to the page's own attributes, then to Arabic and dark", () => {
    expect(readConfig(page(undefined, { lang: "en", theme: "light" }))).toMatchObject({ lang: "en", theme: "light" });
    expect(readConfig(page())).toEqual({ lang: "ar", theme: "dark", pollMs: 4000, gate: null });
  });

  it("does not trust a broken or out-of-range config", () => {
    expect(readConfig(page("{not json"))).toEqual({ lang: "ar", theme: "dark", pollMs: 4000, gate: null });
    expect(readConfig(page('{"lang":"fr","theme":"blue","pollMs":-5}'))).toEqual({
      lang: "ar",
      theme: "dark",
      pollMs: 4000,
      gate: null,
    });
  });

  it("carries what the check-in screen asks, when the server wrote one of the three kinds", () => {
    const gate = { kind: "check_in", date: "2026-09-21", shift: "Shift 1", grace: 10, late_now: 0 };
    expect(readConfig(page(JSON.stringify({ gate }))).gate).toEqual(gate);
    expect(readConfig(page(JSON.stringify({ gate: { kind: "extra", date: "2026-09-21" } }))).gate).toMatchObject({ kind: "extra" });
  });

  it("lets nothing else through as a gate: a kind it does not know, a string, a number, nothing", () => {
    for (const gate of [{ kind: "party" }, { kind: 5 }, {}, "check_in", 7, true, null, [1]]) {
      expect(readConfig(page(JSON.stringify({ gate }))).gate, JSON.stringify(gate)).toBeNull();
    }
    expect(readConfig(page('{"lang":"en"}')).gate).toBeNull();
  });
});
