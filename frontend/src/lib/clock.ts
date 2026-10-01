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
