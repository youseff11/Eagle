import type { Lang } from "../api/types";

/**
 * A time of day the server wrote (`8:05 PM`, Cairo, twelve hours), as the page shows it: the same in both languages.
 *
 * Arabic readers see `AM` and `PM` too, not `ص` and `م`: inside Arabic text the right-to-left rule reorders `9:00 ص - 5:00 م`
 * into another time, and Latin letters keep the order they were written in. Nothing is done to it: the app never works out a
 * time itself. (`lang` stays in the signature: every caller already passes it.)
 */
export function clockText(time: string, _lang: Lang): string {
  return time;
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
