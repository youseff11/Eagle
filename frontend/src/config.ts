import type { Lang, Theme } from "./api/types";

/**
 * What the server page tells the app before it can ask: the language and theme
 * the page was drawn with (so nothing flashes), and how often the old pages poll.
 * Django writes it as JSON into `<script id="app-config">`; in `npm run dev`
 * there is no such script and the defaults apply.
 */
export interface AppConfig {
  lang: Lang;
  theme: Theme;
  pollMs: number;
}

export function readConfig(doc: Document = document): AppConfig {
  const fallback: AppConfig = {
    lang: doc.documentElement.lang === "en" ? "en" : "ar",
    theme: doc.documentElement.dataset.theme === "light" ? "light" : "dark",
    pollMs: 4000,
  };
  const node = doc.getElementById("app-config");
  if (!node?.textContent) return fallback;
  try {
    const raw = JSON.parse(node.textContent) as Partial<AppConfig>;
    return {
      lang: raw.lang === "en" ? "en" : raw.lang === "ar" ? "ar" : fallback.lang,
      theme: raw.theme === "light" ? "light" : raw.theme === "dark" ? "dark" : fallback.theme,
      pollMs: typeof raw.pollMs === "number" && raw.pollMs > 0 ? raw.pollMs : fallback.pollMs,
    };
  } catch {
    return fallback;
  }
}
