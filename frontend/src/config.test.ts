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
    });
  });

  it("falls back to the page's own attributes, then to Arabic and dark", () => {
    expect(readConfig(page(undefined, { lang: "en", theme: "light" }))).toMatchObject({ lang: "en", theme: "light" });
    expect(readConfig(page())).toEqual({ lang: "ar", theme: "dark", pollMs: 4000 });
  });

  it("does not trust a broken or out-of-range config", () => {
    expect(readConfig(page("{not json"))).toEqual({ lang: "ar", theme: "dark", pollMs: 4000 });
    expect(readConfig(page('{"lang":"fr","theme":"blue","pollMs":-5}'))).toEqual({
      lang: "ar",
      theme: "dark",
      pollMs: 4000,
    });
  });
});
