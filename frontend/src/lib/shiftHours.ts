import type { Stamp } from "../api/types";

/**
 * A shift's hours as people read them. In Arabic it is "من 9:00 صباحًا إلى 5:00 مساءً": the words between the two times keep
 * the right-to-left rule from swapping them, which a bare "9:00 AM – 5:00 PM" in an Arabic line does. English stays "9:00 AM – 5:00 PM".
 * The rest of the site keeps AM / PM (`clock.py`); this is for a shift's window only (15/11/2026).
 */

const TIME = /^\s*(\d{1,2}:\d{2})\s*(AM|PM)\s*$/i;
const WINDOW = /^\s*(\d{1,2}:\d{2}\s*(?:AM|PM))\s*[-–]\s*(\d{1,2}:\d{2}\s*(?:AM|PM))\s*$/i;

/** "9:00 AM" -> "9:00 صباحًا", "5:00 PM" -> "5:00 مساءً"; anything else as it came. */
export function arabicTime(text: string): string {
  const found = TIME.exec(text);
  if (!found) return text;
  return `${found[1]} ${found[2]!.toUpperCase() === "AM" ? "صباحًا" : "مساءً"}`;
}

/** The window from two times as the server sends them (`{ar, en}`), in the reader's language. */
export function shiftHours(start: Stamp | null | undefined, end: Stamp | null | undefined, lang: string): string {
  if (!start || !end) return "—";
  if (lang === "ar") return `من ${arabicTime(start.ar)} إلى ${arabicTime(end.ar)}`;
  return `${start.en} – ${end.en}`;
}

/**
 * A shift's name, unless the name is only its hours ("12:00 PM - 5:00 PM": what a shift made from the file's "new shift" boxes
 * without a name is called), in which case it is ``""`` and the hours beside it say it all.
 */
export function shiftName(label: string | null | undefined): string {
  return label && !WINDOW.test(label) ? label : "";
}

/** "Name — hours", or the hours alone when the name is only the hours. */
export function shiftTitle(label: string | null | undefined, start: Stamp | null | undefined, end: Stamp | null | undefined, lang: string): string {
  const name = shiftName(label);
  const hours = shiftHours(start, end, lang);
  return name ? `${name} — ${hours}` : hours;
}
