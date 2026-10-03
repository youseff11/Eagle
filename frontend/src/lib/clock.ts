import type { Lang } from "../api/types";

/**
 * A time of day the server wrote (`8:05 PM`, Cairo, twelve hours), in the page's language.
 *
 * The server writes the English form; Arabic readers see `ص` and `م` instead, as the classic pages draw
 * them (`Eagle.ampm`). Nothing else is done to it: the app never works out a time itself.
 */
export function clockText(time: string, lang: Lang): string {
  if (lang === "en") return time;
  return time.replace(/\bAM\b/, "ص").replace(/\bPM\b/, "م");
}

/**
 * A moment as Cairo wall-clock time on a twelve-hour clock, whatever the computer's own zone is - the clock on the
 * check-in screen, which must say what the server will say (Egypt time, always).
 */
export function cairoClock(when: Date, lang: Lang): string {
  let text: string;
  try {
    text = new Intl.DateTimeFormat("en-US", { timeZone: "Africa/Cairo", hour: "numeric", minute: "2-digit", hour12: true }).format(when);
  } catch {
    const hour = when.getHours() % 12 || 12;
    text = `${hour}:${String(when.getMinutes()).padStart(2, "0")} ${when.getHours() < 12 ? "AM" : "PM"}`;
  }
  // `Intl` writes a narrow no-break space before AM/PM in recent engines.
  return clockText(text.replace(/\u202f/g, " "), lang);
}
