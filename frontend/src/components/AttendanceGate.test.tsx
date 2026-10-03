import { QueryClient } from "@tanstack/react-query";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { qk } from "../api/keys";
import type { AttendanceGate as Gate } from "../api/types";
import { DEVICE_KEY, DISMISSED_KEY, EXTRA_KEY, EXTRA_NUDGE_MS, postponed } from "../lib/attendance";
import { jsonResponse, mockFetch, renderWithProviders } from "../test/helpers";
import { AttendanceGate } from "./AttendanceGate";
import { ToastProvider } from "./Toasts";

const both = (ar: string, en: string) => ({ ar, en });

const CHECK_IN: Gate = {
  kind: "check_in",
  date: "2026-09-21",
  shift: "9:00 ص - 5:00 م",
  start: both("9:00 ص", "9:00 AM"),
  end: both("5:00 م", "5:00 PM"),
  grace_until: both("9:10 ص", "9:10 AM"),
  grace: 10,
  late_now: 0,
  needs_location: false,
  checkout_after: 60,
};
const CHECK_OUT: Gate = {
  kind: "check_out",
  date: "2026-09-21",
  shift: "9:00 ص - 5:00 م",
  end: both("5:00 م", "5:00 PM"),
  deadline: both("6:00 م", "6:00 PM"),
  needs_location: false,
};
const EXTRA: Gate = {
  kind: "extra",
  date: "2026-09-21",
  shift: "9:00 ص - 5:00 م",
  end: both("5:00 م", "5:00 PM"),
  extra_since: both("5:05 م", "5:05 PM"),
  deadline: both("1:00 ص", "1:00 AM"),
  needs_location: false,
};

const OK = { ok: true, action: "check_in", at: "9:05 AM", late_minutes: 0, overtime_minutes: 0 };

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  postponed.reload();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.documentElement.classList.remove("has-gate");
});

function setup(gate: Gate | null, reply: () => Response | Promise<Response> = () => jsonResponse(OK), lang: "ar" | "en" = "ar") {
  const mocked = mockFetch({ "/api/attendance/punch/": reply, "/api/v1/attendance/": () => jsonResponse({ ok: true }) });
  vi.stubGlobal("fetch", mocked.fn);
  // What the page that carried the app asked (`main.tsx` writes it before the first paint), then what each beat says.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 } } });
  client.setQueryData(qk.gate, gate);
  const view = renderWithProviders(
    <ToastProvider>
      <div className="shell">the page</div>
      <AttendanceGate />
    </ToastProvider>,
    { lang, client },
  );
  // The cache hands a new answer to the screen on a macrotask: wait for it, as the heartbeat's next beat would.
  const tell = (next: Gate | null) =>
    act(async () => {
      view.client.setQueryData(qk.gate, next);
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  return { ...view, tell, calls: mocked.calls };
}

const punches = (calls: { url: string; init?: RequestInit }[]) => calls.filter((call) => call.url === "/api/attendance/punch/");
const form = (call: { init?: RequestInit }) => call.init!.body as FormData;
const dialog = () => screen.queryByRole("dialog");

function geolocation(answer: "fix" | "denied") {
  const getCurrentPosition = vi.fn((ok: PositionCallback, fail: PositionErrorCallback, _options?: PositionOptions) => {
    if (answer === "fix") ok({ coords: { latitude: 30.1, longitude: 31.2, accuracy: 9 } } as GeolocationPosition);
    else fail({ code: 1 } as GeolocationPositionError);
  });
  vi.stubGlobal("navigator", { ...navigator, geolocation: { getCurrentPosition, watchPosition: vi.fn() } });
  return getCurrentPosition;
}

describe("AttendanceGate: the check-in", () => {
  it("is not there when nothing is asked", () => {
    setup(null);
    expect(dialog()).toBeNull();
    expect(document.documentElement.classList.contains("has-gate")).toBe(false);
  });

  it("opens over the page with the shift, when it starts and until when it is on time", () => {
    setup(CHECK_IN);
    const box = screen.getByRole("dialog", { name: "سجّل حضورك" });
    expect(box).toHaveAttribute("data-gate", "check_in");
    expect(within(box).getByText("9:00 ص - 5:00 م")).toBeInTheDocument();
    expect(within(box).getByText("9:00 ص")).toHaveClass("mono");
    expect(within(box).getByText("9:10 ص")).toBeInTheDocument();
    expect(within(box).getByText("10")).toBeInTheDocument();
    expect(within(box).getByText("لو نسيت تسجل انصراف، اليوم كله مش هيتحسب.")).toBeInTheDocument();
    expect(within(box).getByRole("button", { name: "تسجيل حضور" })).toBeInTheDocument();
  });

  it("shows a clock in Cairo time, twelve hours, in the page's language", () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    // 06:07 UTC is 9:07 in Cairo (UTC+3 in September).
    vi.setSystemTime(new Date("2026-09-21T06:07:00Z"));
    setup(CHECK_IN);
    expect(document.querySelector("[data-gate-clock]")).toHaveTextContent("9:07 ص");
  });

  it("cannot be put off: no close button, no later, not by Escape, not by a click outside", async () => {
    const user = userEvent.setup();
    setup(CHECK_IN);
    const box = screen.getByRole("dialog");
    expect(within(box).queryByRole("button", { name: /بعدين|إغلاق|لسه شغال/ })).toBeNull();
    await user.keyboard("{Escape}");
    fireEvent.mouseDown(box);
    fireEvent.click(box);
    expect(dialog()).toBeInTheDocument();
  });

  it("makes the page behind it unreachable while it is up, and reachable again when it goes", async () => {
    const view = setup(CHECK_IN);
    const page = view.container.querySelector(".shell") as HTMLElement;
    expect(page).toHaveAttribute("inert");
    expect(document.documentElement.classList.contains("has-gate")).toBe(true);
    await view.tell(null);
    expect(page).not.toHaveAttribute("inert");
    expect(document.documentElement.classList.contains("has-gate")).toBe(false);
    expect(dialog()).toBeNull();
  });

  it("says how late the person already is, only when they are", () => {
    setup({ ...CHECK_IN, late_now: 14 });
    const note = document.querySelector("[data-gate-late]") as HTMLElement;
    expect(note).toHaveTextContent("انت متأخر 14 دقيقة — التأخير هيتحسب ويتحوّل للـHR.");
  });

  it("is quiet about lateness on time", () => {
    setup(CHECK_IN);
    expect(document.querySelector("[data-gate-late]")).toBeNull();
  });

  it("puts the first button in the focus so the next key press is on it", () => {
    setup(CHECK_IN);
    expect(screen.getByRole("button", { name: "تسجيل حضور" })).toHaveFocus();
  });

  it("checks in with this browser's token and no position on a remote day, and goes", async () => {
    const user = userEvent.setup();
    const geo = geolocation("fix");
    const { calls } = setup(CHECK_IN);
    await user.click(screen.getByRole("button", { name: "تسجيل حضور" }));
    await waitFor(() => expect(dialog()).toBeNull());
    expect(punches(calls)).toHaveLength(1);
    expect(form(punches(calls)[0]!).get("action")).toBe("check_in");
    expect(form(punches(calls)[0]!).get("device")).toBe(window.localStorage.getItem(DEVICE_KEY));
    expect(form(punches(calls)[0]!).has("lat")).toBe(false);
    expect(geo).not.toHaveBeenCalled();
    expect(await screen.findByText("اتسجل 9:05 ص")).toBeInTheDocument();
  });

  it("asks the browser for a position once, at the press, on an office day, and sends it", async () => {
    const user = userEvent.setup();
    const geo = geolocation("fix");
    const { calls } = setup({ ...CHECK_IN, needs_location: true });
    expect(geo).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "تسجيل حضور" }));
    await waitFor(() => expect(punches(calls)).toHaveLength(1));
    expect(geo).toHaveBeenCalledTimes(1);
    expect(form(punches(calls)[0]!).get("lat")).toBe("30.1");
    expect(form(punches(calls)[0]!).get("lng")).toBe("31.2");
    expect(form(punches(calls)[0]!).get("accuracy")).toBe("9");
  });

  it("goes without a position when the browser refuses, and says HR will review it", async () => {
    const user = userEvent.setup();
    geolocation("denied");
    const { calls } = setup({ ...CHECK_IN, needs_location: true }, () => new Promise<Response>(() => undefined));
    await user.click(screen.getByRole("button", { name: "تسجيل حضور" }));
    expect(await screen.findByText("الموقع مرفوض من المتصفح — التسجيل هيتبعت من غيره والـHR هتراجعه.")).toHaveClass("warn");
    await waitFor(() => expect(punches(calls)).toHaveLength(1));
    expect(form(punches(calls)[0]!).has("lat")).toBe(false);
  });

  it("tells how late it was, as a warning, and goes", async () => {
    const user = userEvent.setup();
    setup({ ...CHECK_IN, late_now: 14 }, () => jsonResponse({ ...OK, late_minutes: 14 }));
    await user.click(screen.getByRole("button", { name: "تسجيل حضور" }));
    const toast = await screen.findByText("اتسجل حضورك 9:05 ص — متأخر 14 دقيقة، والتأخير اتحوّل للـHR.");
    expect(toast.closest(".toast")).toHaveClass("toast--warning");
    expect(dialog()).toBeNull();
  });

  it("stays and says why when the server refuses, in the server's words", async () => {
    const user = userEvent.setup();
    setup(CHECK_IN, () => jsonResponse({ ok: false, error: "device", ar: "الجهاز ده مستني موافقة", en: "This device is waiting for approval" }));
    await user.click(screen.getByRole("button", { name: "تسجيل حضور" }));
    expect(await screen.findAllByText("الجهاز ده مستني موافقة")).toHaveLength(2);
    expect(dialog()).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "تسجيل حضور" })).toBeEnabled();
  });

  it("stays and says it could not record when no answer came, and lets the person try again", async () => {
    const user = userEvent.setup();
    setup(CHECK_IN, () => {
      throw new TypeError("network");
    });
    await user.click(screen.getByRole("button", { name: "تسجيل حضور" }));
    expect(await screen.findByText("مانفعش يتسجل. جرب تاني.")).toHaveClass("warn");
    expect(dialog()).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "تسجيل حضور" })).toBeEnabled();
  });

  it("sends one request for two presses", async () => {
    const user = userEvent.setup();
    let release: (() => void) | undefined;
    const { calls } = setup(CHECK_IN, () => new Promise<Response>((resolve) => (release = () => resolve(jsonResponse(OK)))));
    const button = screen.getByRole("button", { name: "تسجيل حضور" });
    await user.click(button);
    await user.click(button);
    expect(button).toBeDisabled();
    expect(punches(calls)).toHaveLength(1);
    release?.();
    await waitFor(() => expect(dialog()).toBeNull());
    expect(punches(calls)).toHaveLength(1);
  });

  it("comes back if the server still says a check-in is due after it was recorded", async () => {
    const user = userEvent.setup();
    const view = setup(CHECK_IN);
    await user.click(screen.getByRole("button", { name: "تسجيل حضور" }));
    await waitFor(() => expect(dialog()).toBeNull());
    await view.tell(CHECK_IN);
    expect(dialog()).toBeInTheDocument();
  });

  it("asks the card to read again after a punch", async () => {
    const user = userEvent.setup();
    const view = setup(CHECK_IN);
    const spy = vi.spyOn(view.client, "invalidateQueries");
    await user.click(screen.getByRole("button", { name: "تسجيل حضور" }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: qk.attendance }));
  });

  it("speaks English too", async () => {
    setup({ ...CHECK_IN, late_now: 3 }, undefined, "en");
    const box = screen.getByRole("dialog", { name: "Check in" });
    expect(within(box).getByText("9:10 AM")).toBeInTheDocument();
    expect(within(box).getByText("You are late by")).toBeInTheDocument();
    expect(within(box).getByRole("button", { name: "Check in" })).toBeInTheDocument();
  });
});

describe("AttendanceGate: the reminder after the shift", () => {
  it("says the shift is over and by when to check out, and offers three things", () => {
    setup(CHECK_OUT);
    const box = screen.getByRole("dialog", { name: "الشيفت خلص" });
    expect(within(box).getByText("5:00 م")).toBeInTheDocument();
    expect(within(box).getByText("6:00 م")).toBeInTheDocument();
    expect(within(box).getByRole("button", { name: "تسجيل انصراف" })).toHaveClass("btn--danger");
    expect(within(box).getByRole("button", { name: "اكسترا تايم" })).toBeInTheDocument();
    expect(within(box).getByRole("button", { name: "بعدين" })).toBeInTheDocument();
  });

  it("checks out, asking for a position when the day does", async () => {
    const user = userEvent.setup();
    const geo = geolocation("fix");
    const { calls } = setup({ ...CHECK_OUT, needs_location: true }, () => jsonResponse({ ...OK, action: "check_out", overtime_minutes: 0 }));
    await user.click(screen.getByRole("button", { name: "تسجيل انصراف" }));
    await waitFor(() => expect(dialog()).toBeNull());
    expect(form(punches(calls)[0]!).get("action")).toBe("check_out");
    expect(geo).toHaveBeenCalledTimes(1);
  });

  it("can be put off with «بعدين»: it goes, for that day, and the browser remembers", async () => {
    const user = userEvent.setup();
    const view = setup(CHECK_OUT);
    await user.click(screen.getByRole("button", { name: "بعدين" }));
    expect(dialog()).toBeNull();
    expect(window.sessionStorage.getItem(DISMISSED_KEY)).toBe("check_out:2026-09-21");
    // The next beat says the same thing: it stays put off.
    await view.tell({ ...CHECK_OUT });
    expect(dialog()).toBeNull();
    // Another day's reminder is a new one.
    await view.tell({ ...CHECK_OUT, date: "2026-09-22" });
    expect(dialog()).toBeInTheDocument();
  });

  it("does not ask for it again after the page is opened anew, in the same browser session", () => {
    window.sessionStorage.setItem(DISMISSED_KEY, "check_out:2026-09-21");
    postponed.reload();
    setup(CHECK_OUT);
    expect(dialog()).toBeNull();
  });

  it("starts extra time and goes, and the extra-time screen does not come straight back", async () => {
    const user = userEvent.setup();
    const { calls, tell } = setup(CHECK_OUT, () => jsonResponse({ ...OK, action: "extra_start", at: "5:05 PM" }));
    await user.click(screen.getByRole("button", { name: "اكسترا تايم" }));
    await waitFor(() => expect(dialog()).toBeNull());
    expect(form(punches(calls)[0]!).get("action")).toBe("extra_start");
    expect(window.sessionStorage.getItem(EXTRA_KEY)).toMatch(/^2026-09-21\|\d+$/);
    expect(await screen.findByText(/الاكسترا تايم بدأ 5:05 م/)).toBeInTheDocument();
    // The beat that follows now says extra time is running: it is the one that was just put off.
    await tell(EXTRA);
    expect(dialog()).toBeNull();
  });

  it("does not ask for a position for extra time", async () => {
    const user = userEvent.setup();
    const geo = geolocation("fix");
    setup({ ...CHECK_OUT, needs_location: true }, () => jsonResponse({ ...OK, action: "extra_start" }));
    await user.click(screen.getByRole("button", { name: "اكسترا تايم" }));
    await waitFor(() => expect(dialog()).toBeNull());
    expect(geo).not.toHaveBeenCalled();
  });
});

describe("AttendanceGate: extra time is running", () => {
  it("says since when and by when to check out", () => {
    setup(EXTRA);
    const box = screen.getByRole("dialog", { name: "الاكسترا تايم شغال" });
    expect(within(box).getByText("5:05 م")).toBeInTheDocument();
    expect(within(box).getByText("1:00 ص")).toBeInTheDocument();
    expect(within(box).getByRole("button", { name: "خلّصت — تسجيل انصراف" })).toBeInTheDocument();
    expect(within(box).getByRole("button", { name: "لسه شغال" })).toBeInTheDocument();
  });

  it("goes for an hour with «لسه شغال», and comes back after it, though the answer never changed", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(new Date("2026-09-21T15:00:00Z"));
    setup(EXTRA);
    fireEvent.click(screen.getByRole("button", { name: "لسه شغال" }));
    expect(dialog()).toBeNull();
    expect(window.sessionStorage.getItem(EXTRA_KEY)).toBe(`2026-09-21|${Date.now()}`);
    await act(async () => void (await vi.advanceTimersByTimeAsync(EXTRA_NUDGE_MS - 30000)));
    expect(dialog()).toBeNull();
    await act(async () => void (await vi.advanceTimersByTimeAsync(60000)));
    expect(dialog()).toBeInTheDocument();
  });

  it("checks out and goes", async () => {
    const user = userEvent.setup();
    const { calls } = setup(EXTRA, () => jsonResponse({ ...OK, action: "check_out", overtime_minutes: 45 }));
    await user.click(screen.getByRole("button", { name: "خلّصت — تسجيل انصراف" }));
    await waitFor(() => expect(dialog()).toBeNull());
    expect(form(punches(calls)[0]!).get("action")).toBe("check_out");
    expect(await screen.findByText(/45 دقيقة اكسترا تايم اتبعتت للـHR تراجعها/)).toBeInTheDocument();
  });
});

describe("AttendanceGate: one screen at a time", () => {
  it("turns into the next one when the answer changes, and forgets what was said about the last", async () => {
    const user = userEvent.setup();
    const view = setup(CHECK_IN, () => jsonResponse({ ok: false, error: "x", ar: "رفض", en: "Refused" }, 200));
    await user.click(screen.getByRole("button", { name: "تسجيل حضور" }));
    await screen.findAllByText("رفض");
    await view.tell(CHECK_OUT);
    expect(screen.getByRole("dialog", { name: "الشيفت خلص" })).toBeInTheDocument();
    expect(document.querySelector("[data-gate-status]")).toHaveTextContent("");
    expect(screen.queryByRole("button", { name: "تسجيل حضور" })).toBeNull();
  });

  it("is only ever one dialog", async () => {
    const view = setup(CHECK_IN);
    await view.tell(EXTRA);
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });
});
