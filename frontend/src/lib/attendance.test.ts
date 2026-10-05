import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AttendanceGate, PunchAnswer } from "../api/types";
import { jsonResponse } from "../test/helpers";
import {
  DEVICE_KEY,
  DISMISSED_KEY,
  EXTRA_KEY,
  EXTRA_NUDGE_MS,
  Postponed,
  deviceToken,
  outcome,
  position,
  punch,
} from "./attendance";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  fetchMock = vi.fn(async () => jsonResponse({ ok: true, action: "check_in", at: "9:05 AM", late_minutes: 0, overtime_minutes: 0 }));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** A browser's geolocation that answers the way the test says, and counts what it was asked. */
function geolocation(answer: "fix" | "denied" | "silent") {
  const getCurrentPosition = vi.fn((ok: PositionCallback, fail: PositionErrorCallback, _options?: PositionOptions) => {
    if (answer === "fix") ok({ coords: { latitude: 30.0444, longitude: 31.2357, accuracy: 12.6 } } as GeolocationPosition);
    else if (answer === "denied") fail({ code: 1 } as GeolocationPositionError);
  });
  const watchPosition = vi.fn();
  vi.stubGlobal("navigator", { ...navigator, geolocation: { getCurrentPosition, watchPosition } });
  return { getCurrentPosition, watchPosition };
}

describe("deviceToken", () => {
  it("is a random value of 32 hex digits, kept under the key the classic page uses", () => {
    const token = deviceToken();
    expect(token).toMatch(/^[0-9a-f]{32}$/);
    expect(window.localStorage.getItem(DEVICE_KEY)).toBe(token);
    expect(DEVICE_KEY).toBe("eagle.device");
  });

  it("is the same one every time, and the one the classic page already stored", () => {
    window.localStorage.setItem(DEVICE_KEY, "abc123");
    expect(deviceToken()).toBe("abc123");
    expect(deviceToken()).toBe("abc123");
  });

  it("is not the same between two browsers", () => {
    const first = deviceToken();
    window.localStorage.clear();
    expect(deviceToken()).not.toBe(first);
  });

  it("still gives a token when the browser refuses to keep one", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(deviceToken()).toMatch(/^[0-9a-f]{32}$/);
  });
});

describe("position", () => {
  it("asks once for one fix, as precisely as the device can, and never uses an old one", async () => {
    const geo = geolocation("fix");
    await expect(position()).resolves.toEqual({ lat: 30.0444, lng: 31.2357, accuracy: 13 });
    expect(geo.getCurrentPosition).toHaveBeenCalledTimes(1);
    expect(geo.getCurrentPosition.mock.calls[0]![2]).toEqual({ enableHighAccuracy: true, timeout: 12000, maximumAge: 0 });
    expect(geo.watchPosition).not.toHaveBeenCalled();
  });

  it("is null, not an error, for a refusal", async () => {
    geolocation("denied");
    await expect(position()).resolves.toBeNull();
  });

  it("is null when the browser has no geolocation at all", async () => {
    vi.stubGlobal("navigator", { ...navigator, geolocation: undefined });
    await expect(position()).resolves.toBeNull();
  });

  it("is null when the permission prompt is dismissed and no callback ever comes", async () => {
    vi.useFakeTimers();
    geolocation("silent");
    const asked = position();
    await vi.advanceTimersByTimeAsync(12900);
    let settled = false;
    void asked.then(() => (settled = true));
    await vi.advanceTimersByTimeAsync(0);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(200);
    await expect(asked).resolves.toBeNull();
  });
});

describe("punch", () => {
  const body = () => (fetchMock.mock.calls[0]![1] as RequestInit).body as FormData;

  it("posts the action and this browser's token to the classic endpoint, as one form", async () => {
    const answer = await punch("break_start", false, () => undefined);
    expect(answer.ok).toBe(true);
    expect(String(fetchMock.mock.calls[0]![0])).toBe("/api/attendance/punch/");
    expect((fetchMock.mock.calls[0]![1] as RequestInit).method).toBe("POST");
    expect(body().get("action")).toBe("break_start");
    expect(body().get("device")).toBe(window.localStorage.getItem(DEVICE_KEY));
    expect(body().has("lat")).toBe(false);
  });

  it("reads a position for a check-in or a check-out on a day that asks for one, and sends it with that request only", async () => {
    const geo = geolocation("fix");
    const said: string[] = [];
    await punch("check_in", true, (text) => said.push(text[1]));
    expect(geo.getCurrentPosition).toHaveBeenCalledTimes(1);
    expect(body().get("lat")).toBe("30.0444");
    expect(body().get("lng")).toBe("31.2357");
    expect(body().get("accuracy")).toBe("13");
    expect(said).toEqual(["Finding your location...", "Recording..."]);
  });

  it("never reads a position for a break, for extra time, or on a day that does not ask", async () => {
    const geo = geolocation("fix");
    for (const action of ["break_start", "break_end", "extra_start"] as const) await punch(action, true, () => undefined);
    await punch("check_in", false, () => undefined);
    await punch("check_out", false, () => undefined);
    expect(geo.getCurrentPosition).not.toHaveBeenCalled();
    expect(geo.watchPosition).not.toHaveBeenCalled();
  });

  it("goes without a position when the browser refuses one, and says HR will review it", async () => {
    geolocation("denied");
    const said: [string, string | undefined][] = [];
    await punch("check_out", true, (text, tone) => said.push([text[1], tone]));
    expect(body().has("lat")).toBe(false);
    expect(said).toContainEqual(["Location was blocked - the punch goes without it and HR will review it.", "warn"]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("answers with the server's refusal as an answer, not as an exception", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ ok: false, error: "no_checkin", ar: "سجّل حضور الأول", en: "Check in first" }));
    await expect(punch("check_out", false, () => undefined)).resolves.toMatchObject({ ok: false, en: "Check in first" });
  });

  it("throws when no answer came, because the punch may have gone through", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("network"));
    await expect(punch("check_in", false, () => undefined)).rejects.toBeTruthy();
  });
});

describe("outcome", () => {
  const ok = (over: Partial<Extract<PunchAnswer, { ok: true }>> = {}): PunchAnswer => ({
    ok: true,
    action: "check_in",
    at: "9:05 AM",
    late_minutes: 0,
    overtime_minutes: 0,
    ...over,
  });

  it("is plain on time, in the page's language and with the page's AM and PM", () => {
    expect(outcome("check_in", ok(), "en")).toEqual({ ok: true, level: "success", text: "Recorded 9:05 AM" });
    expect(outcome("check_in", ok({ at: "5:05 PM" }), "ar")).toEqual({ ok: true, level: "success", text: "اتسجل 5:05 PM" });
  });

  it("says how late, and that it went to HR", () => {
    const late = outcome("check_in", ok({ late_minutes: 14 }), "en");
    expect(late).toMatchObject({ ok: true, level: "warning" });
    expect(late.text).toBe("Checked in at 9:05 AM - 14 minutes late. This went to HR.");
    expect(outcome("check_in", ok({ late_minutes: 14 }), "ar").text).toContain("متأخر 14 دقيقة");
  });

  it("says extra time went to HR for review on a check-out, and that it started on extra_start", () => {
    expect(outcome("check_out", ok({ overtime_minutes: 50 }), "en").text).toBe("Checked out at 9:05 AM - 50 minutes of extra time sent to HR for review.");
    expect(outcome("extra_start", ok(), "en").text).toContain("Your team leader and the admins were told");
    expect(outcome("extra_start", ok(), "ar").text).toContain("التيم ليدر والأدمن اتبلّغوا");
  });

  it("is the server's own reason for a refusal, in the language asked for", () => {
    const refused: PunchAnswer = { ok: false, error: "x", ar: "اقفل البريك الأول", en: "End the break first" };
    expect(outcome("check_out", refused, "en")).toEqual({ ok: false, level: "warning", text: "End the break first" });
    expect(outcome("check_out", refused, "ar").text).toBe("اقفل البريك الأول");
  });

  it("falls back to 'could not record it' when there is no reason, or no answer at all", () => {
    expect(outcome("check_in", { ok: false, error: "x" }, "en").text).toBe("Could not record it. Try again.");
    expect(outcome("check_in", null, "ar").text).toBe("مانفعش يتسجل. جرب تاني.");
  });
});

describe("Postponed", () => {
  const gate = (kind: AttendanceGate["kind"], date = "2026-09-21") => ({ kind, date }) as AttendanceGate;

  it("never puts off the check-in, whatever was done", () => {
    const put = new Postponed();
    put.dismiss(gate("check_in"));
    put.snoozeExtra("2026-09-21");
    expect(put.hides(gate("check_in"))).toBe(false);
    expect(window.sessionStorage.getItem(DISMISSED_KEY)).toBeNull();
  });

  it("puts the reminder after the shift off for that day, and only that day", () => {
    const put = new Postponed();
    put.dismiss(gate("check_out"));
    expect(put.hides(gate("check_out"))).toBe(true);
    expect(put.hides(gate("check_out", "2026-09-22"))).toBe(false);
    expect(window.sessionStorage.getItem(DISMISSED_KEY)).toBe("check_out:2026-09-21");
  });

  it("puts extra time off for an hour and then asks again", () => {
    const put = new Postponed();
    put.snoozeExtra("2026-09-21", 1_000_000);
    expect(put.hides(gate("extra"), 1_000_000 + EXTRA_NUDGE_MS - 1)).toBe(true);
    expect(put.hides(gate("extra"), 1_000_000 + EXTRA_NUDGE_MS)).toBe(false);
    expect(put.hides(gate("extra", "2026-09-22"), 1_000_001)).toBe(false);
    expect(window.sessionStorage.getItem(EXTRA_KEY)).toBe("2026-09-21|1000000");
  });

  it("does not put off one kind by what was put off of the other", () => {
    const put = new Postponed();
    put.dismiss(gate("check_out"));
    expect(put.hides(gate("extra"))).toBe(false);
    put.snoozeExtra("2026-09-21");
    put.dismiss(gate("check_in"));
    expect(put.hides(gate("check_out", "2026-09-30"))).toBe(false);
  });

  it("remembers across a reload of the page, and agrees with what the classic page wrote", () => {
    window.sessionStorage.setItem(DISMISSED_KEY, "check_out:2026-09-21");
    window.sessionStorage.setItem(EXTRA_KEY, `2026-09-21|${Date.now()}`);
    const put = new Postponed();
    expect(put.hides(gate("check_out"))).toBe(true);
    expect(put.hides(gate("extra"))).toBe(true);
    window.sessionStorage.clear();
    put.reload();
    expect(put.hides(gate("check_out"))).toBe(false);
    expect(put.hides(gate("extra"))).toBe(false);
  });

  it("works from memory when the browser refuses storage", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const put = new Postponed();
    put.dismiss(gate("check_out"));
    put.snoozeExtra("2026-09-21");
    expect(put.hides(gate("check_out"))).toBe(true);
    expect(put.hides(gate("extra"))).toBe(true);
  });
});

/**
 * Section 14 of the attendance spec, as a test: no continuous tracking, no camera, no screenshots. Nothing in the app's
 * own code may ask for a position except `getCurrentPosition` (once, when a button is pressed), nor for a screen or a
 * camera. The one thing that does open the microphone is the voice note in the chat, and it asks for audio and nothing else.
 */
describe("what the app is not allowed to do", () => {
  function sources(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) return sources(path);
      return /\.(ts|tsx)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name) ? [path] : [];
    });
  }
  const files = sources(join(__dirname, ".."));
  const text = (path: string) => readFileSync(path, "utf-8");

  it("has files to look at", () => {
    expect(files.length).toBeGreaterThan(40);
  });

  it("never watches a position", () => {
    expect(files.filter((path) => /watchPosition/.test(text(path)))).toEqual([]);
  });

  it("never captures a screen, a camera or a stream of either", () => {
    for (const word of ["getDisplayMedia", "captureStream", "ImageCapture", "mediaDevices.enumerateDevices"]) {
      expect(files.filter((path) => text(path).includes(word)), word).toEqual([]);
    }
  });

  it("opens the microphone for a voice note, and the microphone and the camera for a call: in those two places and no other", () => {
    const users = files.filter((path) => /getUserMedia\s*\(/.test(text(path)));
    const names = users.map((path) => path.split(/[\\/]/).pop());
    expect(names.sort()).toEqual(["calls.ts", "recorder.ts"]);
    const of = (name: string) => text(users.find((path) => path.endsWith(name))!);
    // A voice note is audio and nothing else.
    expect(of("recorder.ts")).toMatch(/getUserMedia\(\{ audio: true \}\)/);
    expect(of("recorder.ts")).not.toMatch(/video\s*:/);
    // A call asks for the camera only when it is a video call somebody placed or answered: the constraint is the call's own
    // flag, never a literal `true`.
    expect(of("calls.ts")).toMatch(/getUserMedia\(\{ audio: true, video \}\)/);
    expect(of("calls.ts")).not.toMatch(/video\s*:\s*true/);
  });

  it("keeps the attendance code away from the microphone and the camera altogether", () => {
    for (const name of ["attendance.ts", "AttendanceGate.tsx", "AttendancePage.tsx"]) {
      const path = files.find((one) => one.endsWith(name))!;
      expect(text(path), name).not.toMatch(/getUserMedia|mediaDevices|MediaStream|RTCPeerConnection/);
    }
  });

  it("asks for a position in one place only: the attendance code, at a button press", () => {
    const users = files.filter((path) => /geolocation/.test(text(path)));
    expect(users.map((path) => path.split(/[\\/]/).pop())).toEqual(["attendance.ts"]);
    expect(text(users[0]!).match(/getCurrentPosition/g)).toHaveLength(1);
  });
});
