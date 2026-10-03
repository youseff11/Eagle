import { api } from "../api/client";
import type { AttendanceGate, Lang, PunchAction, PunchAnswer } from "../api/types";
import { clockText } from "./clock";

/**
 * Punching in and out, the way `static/js/attendance.js` does it - the same endpoint, the same words, the same two
 * things kept in the browser. Nothing here reads a position except at the moment a button is pressed, and nothing
 * reads a screen or a camera: section 14 of the attendance spec rules out continuous tracking, and the way to keep
 * that promise is to have no code that could break it. (`attendance.test.ts` looks for exactly that.)
 */

export type Say = (text: [string, string], tone?: "warn") => void;

export const TEXT = {
  locating: ["بنحدد الموقع...", "Finding your location..."] as [string, string],
  denied: [
    "الموقع مرفوض من المتصفح — التسجيل هيتبعت من غيره والـHR هتراجعه.",
    "Location was blocked - the punch goes without it and HR will review it.",
  ] as [string, string],
  sending: ["بنسجل...", "Recording..."] as [string, string],
  failed: ["مانفعش يتسجل. جرب تاني.", "Could not record it. Try again."] as [string, string],
  done: ["اتسجل", "Recorded"] as [string, string],
};

/** The key the classic page keeps the token under: the same browser stays the same device in both interfaces. */
export const DEVICE_KEY = "eagle.device";
/** What "later" and "still working" remember for the rest of the browser session (the classic page's keys too). */
export const DISMISSED_KEY = "eagle.gate.dismissed";
export const EXTRA_KEY = "eagle.gate.extra";
/** Somebody on extra time sees the reminder again every hour: the one way the day is lost is walking away. */
export const EXTRA_NUDGE_MS = 60 * 60 * 1000;

/**
 * A random token the browser keeps, so the server can tell one browser from another. It identifies the browser and
 * nothing else: it is generated here, never derived from the machine, and clearing site data throws it away (the
 * browser then lands in HR's approval queue, which is exactly what should happen).
 */
export function deviceToken(): string {
  try {
    const kept = window.localStorage.getItem(DEVICE_KEY);
    if (kept) return kept;
  } catch {
    /* private mode: a token for this page only */
  }
  const bytes = new Uint8Array(16);
  if (window.crypto?.getRandomValues) window.crypto.getRandomValues(bytes);
  else for (let index = 0; index < bytes.length; index++) bytes[index] = Math.floor(Math.random() * 256);
  const token = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  try {
    window.localStorage.setItem(DEVICE_KEY, token);
  } catch {
    /* kept for this page only */
  }
  return token;
}

export interface Coords {
  lat: number;
  lng: number;
  accuracy: number;
}

/**
 * One fix, asked for once. It resolves with `null` rather than failing: a refused or unavailable position is a thing
 * to record and flag (HR reviews it), not a reason to stop somebody clocking in.
 */
export function position(): Promise<Coords | null> {
  return new Promise((resolve) => {
    if (!navigator.geolocation) {
      resolve(null);
      return;
    }
    let settled = false;
    const done = (value: Coords | null) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      resolve(value);
    };
    // Some browsers never call either callback when the permission prompt is dismissed rather than answered.
    const timer = window.setTimeout(() => done(null), 13000);
    navigator.geolocation.getCurrentPosition(
      (pos) => done({ lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy: Math.round(pos.coords.accuracy || 0) }),
      () => done(null),
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 0 },
    );
  });
}

/**
 * One punch, start to finish. A position is read only for a check-in or a check-out on a day that asks for one, and
 * only now. `say` reports progress to whoever asked. The answer is the server's: a refusal is `ok: false` with its
 * reason, never an exception; a reply that never came throws, and the punch may or may not have been recorded.
 */
export async function punch(action: PunchAction, needsLocation: boolean, say: Say): Promise<PunchAnswer> {
  const wantsLocation = needsLocation && (action === "check_in" || action === "check_out");
  let coords: Coords | null = null;
  if (wantsLocation) {
    say(TEXT.locating);
    coords = await position();
    if (!coords) say(TEXT.denied, "warn");
    else say(TEXT.sending);
  } else {
    say(TEXT.sending);
  }
  const form = new FormData();
  form.append("action", action);
  form.append("device", deviceToken());
  if (coords) {
    form.append("lat", String(coords.lat));
    form.append("lng", String(coords.lng));
    form.append("accuracy", String(coords.accuracy));
  }
  return api<PunchAnswer>("/api/attendance/punch/", { multipart: form });
}

export interface Outcome {
  ok: boolean;
  text: string;
  level: "success" | "warning";
}

/** What the server said, as a message: a refusal, lateness, extra time. */
export function outcome(action: PunchAction, answer: PunchAnswer | null, lang: Lang): Outcome {
  const text = (pair: [string, string]) => (lang === "en" ? pair[1] : pair[0]);
  if (!answer || !answer.ok) {
    const reason = answer && !answer.ok ? (lang === "en" ? answer.en : answer.ar) : "";
    return { ok: false, text: reason || text(TEXT.failed), level: "warning" };
  }
  const at = clockText(answer.at, lang);
  if (action === "check_in" && answer.late_minutes) {
    return {
      ok: true,
      level: "warning",
      text:
        lang === "en"
          ? `Checked in at ${at} - ${answer.late_minutes} minutes late. This went to HR.`
          : `اتسجل حضورك ${at} — متأخر ${answer.late_minutes} دقيقة، والتأخير اتحوّل للـHR.`,
    };
  }
  if (action === "check_out" && answer.overtime_minutes) {
    return {
      ok: true,
      level: "success",
      text:
        lang === "en"
          ? `Checked out at ${at} - ${answer.overtime_minutes} minutes of extra time sent to HR for review.`
          : `اتسجل انصرافك ${at} — ${answer.overtime_minutes} دقيقة اكسترا تايم اتبعتت للـHR تراجعها.`,
    };
  }
  if (action === "extra_start") {
    return {
      ok: true,
      level: "success",
      text:
        lang === "en"
          ? `Extra time started at ${at}. Your team leader and the admins were told. Check out when you finish.`
          : `الاكسترا تايم بدأ ${at}. التيم ليدر والأدمن اتبلّغوا. سجّل انصراف لما تخلص.`,
    };
  }
  return { ok: true, level: "success", text: `${text(TEXT.done)} ${at}` };
}

// ---------------------------------------------------------------------------------------------------------------------
// What the person put off: the reminder after the shift, and extra time.
// ---------------------------------------------------------------------------------------------------------------------

/** `check_out:2026-09-21`: which reminder, of which day. */
export const dismissKey = (gate: Pick<AttendanceGate, "kind" | "date">): string => `${gate.kind}:${gate.date}`;

function read(key: string): string {
  try {
    return window.sessionStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function write(key: string, value: string): void {
  try {
    window.sessionStorage.setItem(key, value);
  } catch {
    /* kept in memory only */
  }
}

/** What this browser session has put off. Memory first (a browser may refuse storage), the session's storage second. */
export class Postponed {
  private dismissed = new Set<string>();
  private extra: { date: string; at: number } = { date: "", at: 0 };

  constructor() {
    this.reload();
  }

  /** Read what the session's storage says (the classic pages write the same keys, so the two interfaces agree). */
  reload(): void {
    this.dismissed = new Set();
    this.extra = { date: "", at: 0 };
    const kept = read(DISMISSED_KEY);
    if (kept) this.dismissed.add(kept);
    const [date, at] = read(EXTRA_KEY).split("|");
    if (date && at) this.extra = { date, at: Number(at) || 0 };
  }

  /** «بعدين» on the reminder after the shift: put off for good for that day (the check-in cannot be put off at all). */
  dismiss(gate: AttendanceGate): void {
    if (gate.kind !== "check_out") return;
    this.dismissed.add(dismissKey(gate));
    write(DISMISSED_KEY, dismissKey(gate));
  }

  /** «لسه شغال» (or pressing Extra time): the extra-time screen is put off for an hour. */
  snoozeExtra(date: string, now: number = Date.now()): void {
    if (!date) return;
    this.extra = { date, at: now };
    write(EXTRA_KEY, `${date}|${now}`);
  }

  /** Whether the screen is put off right now. A check-in never is. */
  hides(gate: AttendanceGate, now: number = Date.now()): boolean {
    if (gate.kind === "check_out") return this.dismissed.has(dismissKey(gate));
    if (gate.kind === "extra") return this.extra.date === gate.date && now - this.extra.at < EXTRA_NUDGE_MS;
    return false;
  }
}

/** The one record of it for this page: the card and the screen over every page must agree on what was put off. */
export const postponed = new Postponed();
