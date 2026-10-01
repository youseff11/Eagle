import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { Lang, Theme } from "../api/types";

/**
 * Language and theme, the way the classic pages do them.
 *
 * Every piece of text is written in both languages at the place it is used,
 * `t("عربي", "English")` - the same rule as `data-ar` / `data-en` in the
 * templates and `E.t` in chat.js - so a string with only one language cannot
 * exist. Arabic is the default and the page is right-to-left unless English is
 * chosen. A change is saved with the person through `/api/prefs/`, the endpoint
 * the classic pages use, so both interfaces agree.
 */
interface Preferences {
  lang: Lang;
  dir: "rtl" | "ltr";
  theme: Theme;
  t: (ar: string, en: string) => string;
  setLang: (lang: Lang) => void;
  setTheme: (theme: Theme) => void;
}

const PreferencesContext = createContext<Preferences | null>(null);

export function PreferencesProvider(props: { initialLang: Lang; initialTheme: Theme; children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(props.initialLang);
  const [theme, setThemeState] = useState<Theme>(props.initialTheme);

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  }, [lang]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const save = useCallback((fields: Record<string, string>) => {
    // Best effort: the screen has already changed, and the next visit re-reads it.
    void api("/api/prefs/", { form: fields }).catch(() => undefined);
  }, []);

  const value = useMemo<Preferences>(
    () => ({
      lang,
      dir: lang === "ar" ? "rtl" : "ltr",
      theme,
      t: (ar, en) => (lang === "ar" ? ar : en),
      setLang: (next) => {
        setLangState(next);
        save({ lang: next });
      },
      setTheme: (next) => {
        setThemeState(next);
        save({ theme: next });
      },
    }),
    [lang, theme, save],
  );

  return <PreferencesContext.Provider value={value}>{props.children}</PreferencesContext.Provider>;
}

export function usePreferences(): Preferences {
  const value = useContext(PreferencesContext);
  if (!value) throw new Error("usePreferences needs a PreferencesProvider above it");
  return value;
}
