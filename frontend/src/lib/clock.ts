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

const WEEKDAYS: [string, string][] = [
  ["الأحد", "Sunday"],
  ["الاثنين", "Monday"],
  ["الثلاثاء", "Tuesday"],
  ["الأربعاء", "Wednesday"],
  ["الخميس", "Thursday"],
  ["الجمعة", "Friday"],
  ["السبت", "Saturday"],
];

/** Today in Cairo as `YYYY-MM-DD`, the shape the server writes a message's `date` in. */
export function cairoToday(now: Date = new Date()): string {
  try {
    return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Cairo", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
  } catch {
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  }
}

/**
 * When a conversation last moved, as WhatsApp's list says it: the time today, «أمس» / "Yesterday", the weekday within the
 * week, and the date after that (`27/11`, with the year once it is another year's). `time` and `date` are the server's
 * (Cairo); without a date, or a date that is not one, the time is all there is to say.
 */
export function listStamp(time: string, date: string, lang: Lang, now: Date = new Date()): string {
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  const today = /^(\d{4})-(\d{2})-(\d{2})$/.exec(cairoToday(now));
  if (!day || !today) return clockText(time, lang);
  const at = Date.UTC(+day[1]!, +day[2]! - 1, +day[3]!);
  const days = Math.round((Date.UTC(+today[1]!, +today[2]! - 1, +today[3]!) - at) / 86_400_000);
  if (days <= 0) return clockText(time, lang);
  if (days === 1) return lang === "ar" ? "أمس" : "Yesterday";
  if (days < 7) return WEEKDAYS[new Date(at).getUTCDay()]![lang === "ar" ? 0 : 1];
  const short = `${+day[3]!}/${+day[2]!}`;
  return day[1] === today[1] ? short : `${short}/${day[1]}`;
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
