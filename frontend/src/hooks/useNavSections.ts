import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Which sections of the menu are open.
 *
 * The same rules as the classic menu, and the same place in the browser (`eagle_nav_open`, so a choice made there holds
 * here): the section the person is standing in is open whatever was saved (a menu that hides the page you are looking at is
 * worse than none); the others are as the person left them, closed the first time; and a menu that is shut all the way
 * on the first look opens its first section, because it would be two clicks to use otherwise. What the person opens or
 * closes is remembered; the section that opens because they went there is not (it is not their choice).
 */
const KEY = "eagle_nav_open";

function readSaved(): Record<string, boolean> {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(KEY) ?? "{}");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    // Only a plain yes or no is a choice; anything else somebody left in there is not.
    return Object.fromEntries(Object.entries(parsed).filter(([, value]) => typeof value === "boolean")) as Record<string, boolean>;
  } catch {
    return {};
  }
}

function save(choices: Record<string, boolean>): void {
  try {
    localStorage.setItem(KEY, JSON.stringify({ ...readSaved(), ...choices }));
  } catch {
    // A private window: this visit only, then.
  }
}

export function useNavSections(keys: string[], here: string | null) {
  const [open, setOpen] = useState<Record<string, boolean>>(readSaved);
  const settled = useRef(false);
  // A list that is rebuilt on every render is the same list: compare it by what is in it.
  const listed = keys.join(",");

  useEffect(() => {
    const all = listed ? listed.split(",") : [];
    if (all.length === 0) return;
    const first = !settled.current;
    settled.current = true;
    setOpen((now) => {
      if (here) return now[here] ? now : { ...now, [here]: true };
      if (first && !all.some((key) => now[key])) return { ...now, [all[0]!]: true };
      return now;
    });
  }, [listed, here]);

  const anyOpen = keys.some((key) => open[key]);

  const toggle = useCallback(
    (key: string) => {
      const value = !open[key];
      setOpen((now) => ({ ...now, [key]: value }));
      save({ [key]: value });
    },
    [open],
  );

  /** Shut every section while any is open; open them all once they are all shut. */
  const foldAll = useCallback(() => {
    const value = !anyOpen;
    const choices = Object.fromEntries(keys.map((key) => [key, value]));
    setOpen((now) => ({ ...now, ...choices }));
    save(choices);
  }, [anyOpen, keys]);

  return { isOpen: (key: string) => Boolean(open[key]), anyOpen, toggle, foldAll };
}
