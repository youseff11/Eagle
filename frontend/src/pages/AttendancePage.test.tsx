import { QueryClient } from "@tanstack/react-query";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { qk } from "../api/keys";
import type { AttendanceCard } from "../api/types";
import { ToastProvider } from "../components/Toasts";
import { EXTRA_KEY, postponed } from "../lib/attendance";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { AttendancePage, offered } from "./AttendancePage";

const both = (ar: string, en: string) => ({ ar, en });

function card(over: Partial<AttendanceCard> = {}, day: Partial<AttendanceCard["day"]> = {}): AttendanceCard {
  return {
    ok: true,
    enabled: true,
    work_date: "2026-09-21",
    plan: { working: true, label: "9:00 AM - 5:00 PM", mode: { value: "remote", ar: "عن بُعد", en: "Remote" }, start: both("9:00 AM", "9:00 AM"), end: both("5:00 PM", "5:00 PM") },
    needs_location: false,
    day: {
      state: "none",
      check_in: null,
      check_out: null,
      extra_started_at: null,
      extra_running: false,
      break_minutes: 0,
      on_break: false,
      hours: "0:00",
      late_minutes: 0,
      needs_review: false,
      review_reason: "",
      checkout_missed: false,
      shift_end: "2026-09-21T14:00:00+00:00",
      ...day,
    },
    conf: { grace_minutes: 10, missing_checkout_after_minutes: 60 },
    summary: { scheduled_days: 22, present_days: 15, office_days: 5, remote_days: 10, late_days: 3, late_minutes: 41, short_minutes: 20, overtime_minutes: 90 },
    recent: [
      {
        date: "2026-09-20",
        mode: { value: "remote", ar: "عن بُعد", en: "Remote" },
        schedule: "9:00 AM - 5:00 PM",
        check_in: both("9:12 AM", "9:12 AM"),
        check_out: both("5:30 PM", "5:30 PM"),
        hours: "8:10",
        status: { value: "present", tone: "ok", ar: "حاضر", en: "Present" },
        late_minutes: 12,
        overtime_minutes: 30,
        checkout_missed: false,
      },
      {
        date: "2026-09-19",
        mode: null,
        schedule: "",
        check_in: null,
        check_out: null,
        hours: "0:00",
        status: { value: "unexcused", tone: "dead", ar: "غياب بدون إذن", en: "Unexcused" },
        late_minutes: 0,
        overtime_minutes: 0,
        checkout_missed: true,
      },
    ],
    devices: [
      { label: "abcdef0123", status: "approved" },
      { label: "Office laptop", status: "pending" },
      { label: "9999999999", status: "rejected" },
    ],
    ...over,
  };
}

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
});

function open(
  body: () => AttendanceCard | Response = () => card(),
  reply: () => Response | Promise<Response> = () => jsonResponse(OK),
  lang: "ar" | "en" = "ar",
) {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role: "translator" }, 0, ["attendance"])),
    "/api/attendance/punch/": reply,
    "/api/v1/attendance/": () => {
      const answer = body();
      return answer instanceof Response ? answer : jsonResponse(answer);
    },
  });
  vi.stubGlobal("fetch", mocked.fn);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 } } });
  const view = renderWithProviders(
    <ToastProvider>
      <AttendancePage />
    </ToastProvider>,
    { lang, client },
  );
  return { ...view, calls: mocked.calls };
}

const punches = (calls: { url: string }[]) => calls.filter((call) => call.url === "/api/attendance/punch/");
const cardOf = (container: HTMLElement) => container.querySelector("#punchCard") as HTMLElement;
const buttons = (container: HTMLElement) => Array.from(cardOf(container).querySelectorAll("[data-punch]")).map((b) => b.getAttribute("data-punch"));

describe("offered: the buttons a day shows", () => {
  const day = (over: Partial<AttendanceCard["day"]> = {}) => card({}, over).day;
  const AFTER = Date.parse("2026-09-21T14:00:01+00:00");
  const BEFORE = Date.parse("2026-09-21T13:59:59+00:00");
  const names = (state: ReturnType<typeof offered>) => Object.entries(state).filter(([, on]) => on).map(([name]) => name);

  it("offers only the check-in before the person has checked in", () => {
    expect(names(offered(day(), BEFORE))).toEqual(["check_in"]);
  });

  it("offers a break and the check-out in the shift, and extra time only after it ends", () => {
    expect(names(offered(day({ state: "open" }), BEFORE))).toEqual(["break_start", "check_out"]);
    expect(names(offered(day({ state: "open" }), AFTER))).toEqual(["break_start", "extra_start", "check_out"]);
  });

  it("offers ending the break and the check-out while on a break, and no extra time", () => {
    expect(names(offered(day({ state: "open", on_break: true }), AFTER))).toEqual(["break_end", "check_out"]);
  });

  it("does not offer extra time again once it is running", () => {
    expect(names(offered(day({ state: "open", extra_running: true }), AFTER))).toEqual(["break_start", "check_out"]);
  });

  it("offers nothing on a closed day", () => {
    expect(names(offered(day({ state: "closed" }), AFTER))).toEqual([]);
  });

  it("never offers extra time on a day with no shift", () => {
    expect(names(offered(day({ state: "open", shift_end: null }), AFTER))).toEqual(["break_start", "check_out"]);
  });
});

describe("AttendancePage: today", () => {
  it("shows the date, the shift, the mode and the grace, with nothing punched yet", async () => {
    const view = open();
    expect(await screen.findByText("حضوري", { selector: "h1" })).toBeInTheDocument();
    await screen.findByText("اليوم", { selector: "h3" });
    const today = cardOf(view.container);
    expect(within(today).getByText("9:00 AM - 5:00 PM", { selector: ".chip" })).toBeInTheDocument();
    expect(within(today).getByText("عن بُعد")).toBeInTheDocument();
    expect(today.querySelector(".punch__meta")).toHaveTextContent("الشيفت 9:00 AM – 5:00 PM·سماح 10 دقايق");
    expect(Array.from(today.querySelectorAll(".punch__value")).map((cell) => cell.textContent)).toEqual(["—", "—", "0د", "0:00"]);
    expect(view.container.querySelector(".page-head__sub")).toHaveTextContent("2026-09-21");
    expect(buttons(view.container)).toEqual(["check_in"]);
  });

  it("says a day with no shift has none, and that a punch is still taken", async () => {
    open(() => card({ plan: { working: false, label: "", mode: null, start: null, end: null } }));
    expect(await screen.findByText("مفيش شيفت النهارده")).toBeInTheDocument();
    expect(screen.getByText("تقدر تسجل برضه، والـHR هتراجعه.")).toBeInTheDocument();
  });

  it("says office for an office day", async () => {
    open(() => card({ plan: { working: true, label: "x", mode: { value: "office", ar: "من المكتب", en: "Office" }, start: both("9:00 AM", "9:00 AM"), end: both("5:00 PM", "5:00 PM") } }));
    expect(await screen.findByText("من المكتب", { selector: ".badge" })).toBeInTheDocument();
  });

  it("draws what was punched: the times, the break, the hours, and extra time running", async () => {
    const view = open(() =>
      card({}, {
        state: "open",
        check_in: both("9:14 AM", "9:14 AM"),
        break_minutes: 30,
        hours: "7:20",
        extra_running: true,
        extra_started_at: both("5:05 PM", "5:05 PM"),
      }),
    );
    await screen.findByText("اكسترا تايم شغال");
    const values = Array.from(cardOf(view.container).querySelectorAll(".punch__value")).map((cell) => cell.textContent);
    expect(values).toEqual(["9:14 AM", "—", "30د", "7:20"]);
    expect(view.container.querySelector("[data-extra-line]")).toHaveTextContent("اكسترا تايم شغال من 5:05 PM");
  });

  it("flags a day that needs review, and says when the check-out was missed", async () => {
    open(() => card({}, { needs_review: true, review_reason: "No check-out by the deadline", checkout_missed: true }));
    expect(await screen.findByText(/اليوم ده مش محسوب — مسجلتش انصراف في الميعاد./)).toBeInTheDocument();
    expect(screen.getByText("No check-out by the deadline")).toHaveClass("mono");
  });

  it("says the rule about a forgotten check-out and how long the window is", async () => {
    open();
    expect(await screen.findByText("لو نسيت تسجل انصراف، اليوم كله مش هيتحسب.")).toBeInTheDocument();
    expect(screen.getByText("60")).toHaveClass("mono");
  });

  it("says the location is read at the press and never otherwise", async () => {
    open();
    expect(await screen.findByText("الموقع بيتقرا لحظة الضغط على الزرار بس. مفيش تتبع مستمر ولا كاميرا ولا لقطات شاشة.")).toBeInTheDocument();
  });

  it("shows extra time only after the shift has ended, and the clock moves it in without a reload", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(new Date("2026-09-21T13:59:00+00:00"));
    const view = open(() => card({}, { state: "open", check_in: both("9:00 AM", "9:00 AM") }));
    await act(async () => void (await vi.advanceTimersByTimeAsync(0)));
    await screen.findByText("اليوم", { selector: "h3" });
    expect(buttons(view.container)).toEqual(["break_start", "check_out"]);
    await act(async () => void (await vi.advanceTimersByTimeAsync(70000)));
    expect(buttons(view.container)).toEqual(["break_start", "extra_start", "check_out"]);
  });
});

describe("AttendancePage: punching", () => {
  it("checks in, shows it, and tells the screen over every page that it is answered", async () => {
    const user = userEvent.setup();
    let punched = false;
    const view = open(
      // A shift that has not ended: extra time is not offered yet, whatever the day of the test run.
      () => (punched ? card({}, { state: "open", check_in: both("9:05 AM", "9:05 AM"), hours: "0:00", shift_end: "2099-01-01T00:00:00+00:00" }) : card()),
      () => {
        punched = true;
        return jsonResponse(OK);
      },
    );
    view.client.setQueryData(qk.gate, { kind: "check_in" });
    await user.click(await screen.findByRole("button", { name: "تسجيل حضور" }));
    expect(await screen.findByText("اتسجل 9:05 AM", { selector: ".punch__status" })).toHaveClass("ok");
    await waitFor(() => expect(buttons(view.container)).toEqual(["break_start", "check_out"]));
    expect(view.client.getQueryData(qk.gate)).toBeNull();
    expect(cardOf(view.container).querySelector('[data-field="check_in"]')).toHaveTextContent("9:05 AM");
  });

  it("sends the action, this browser's token, and no position on a remote day", async () => {
    const user = userEvent.setup();
    const view = open();
    await user.click(await screen.findByRole("button", { name: "تسجيل حضور" }));
    await waitFor(() => expect(punches(view.calls)).toHaveLength(1));
    const form = (view.calls.find((call) => call.url === "/api/attendance/punch/")!.init!.body) as FormData;
    expect(form.get("action")).toBe("check_in");
    expect(form.get("device")).toMatch(/^[0-9a-f]{32}$/);
    expect(form.has("lat")).toBe(false);
  });

  it("reads a position at the press, on an office day, and only for the check-in and the check-out", async () => {
    const user = userEvent.setup();
    const getCurrentPosition = vi.fn((ok: PositionCallback, _fail: PositionErrorCallback, _options?: PositionOptions) =>
      ok({ coords: { latitude: 30.1, longitude: 31.2, accuracy: 9 } } as GeolocationPosition),
    );
    vi.stubGlobal("navigator", { ...navigator, geolocation: { getCurrentPosition, watchPosition: vi.fn() } });
    open(() => card({ needs_location: true }, { state: "open", check_in: both("9:00 AM", "9:00 AM") }));
    await user.click(await screen.findByRole("button", { name: "ابدأ بريك" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "ابدأ بريك" })).toBeEnabled());
    expect(getCurrentPosition).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "تسجيل انصراف" }));
    await waitFor(() => expect(getCurrentPosition).toHaveBeenCalledTimes(1));
  });

  it("says how late, as a warning", async () => {
    const user = userEvent.setup();
    open(undefined, () => jsonResponse({ ...OK, late_minutes: 14 }));
    await user.click(await screen.findByRole("button", { name: "تسجيل حضور" }));
    expect(await screen.findByText("اتسجل حضورك 9:05 AM — متأخر 14 دقيقة، والتأخير اتحوّل للـHR.", { selector: ".punch__status" })).toHaveClass("warn");
  });

  it("starts extra time, and the screen over every page is told not to come straight back", async () => {
    const user = userEvent.setup();
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(new Date("2026-09-21T14:30:00+00:00"));
    open(() => card({}, { state: "open", check_in: both("9:00 AM", "9:00 AM") }), () => jsonResponse({ ...OK, action: "extra_start", at: "5:30 PM" }));
    await act(async () => void (await vi.advanceTimersByTimeAsync(0)));
    await user.click(await screen.findByRole("button", { name: "اكسترا تايم" }));
    await waitFor(() => expect(window.sessionStorage.getItem(EXTRA_KEY)).toMatch(/^2026-09-21\|\d+$/));
  });

  it("stays as it was and says why when the server refuses, in its words", async () => {
    const user = userEvent.setup();
    const view = open(undefined, () => jsonResponse({ ok: false, error: "x", ar: "الجهاز ده مستني موافقة", en: "Waiting for approval" }));
    await user.click(await screen.findByRole("button", { name: "تسجيل حضور" }));
    expect(await screen.findByText("الجهاز ده مستني موافقة", { selector: ".punch__status" })).toHaveClass("warn");
    expect(buttons(view.container)).toEqual(["check_in"]);
    expect(screen.getByRole("button", { name: "تسجيل حضور" })).toBeEnabled();
  });

  it("says it could not record when no answer came, and asks the card again to see what is true", async () => {
    const user = userEvent.setup();
    const view = open(undefined, () => {
      throw new TypeError("network");
    });
    await user.click(await screen.findByRole("button", { name: "تسجيل حضور" }));
    expect(await screen.findByText("مانفعش يتسجل. جرب تاني.", { selector: ".punch__status" })).toHaveClass("warn");
    await waitFor(() => expect(view.calls.filter((call) => call.url === "/api/v1/attendance/").length).toBeGreaterThan(1));
  });

  it("sends one request for two presses", async () => {
    const user = userEvent.setup();
    let release: (() => void) | undefined;
    const view = open(undefined, () => new Promise<Response>((resolve) => (release = () => resolve(jsonResponse(OK)))));
    const button = await screen.findByRole("button", { name: "تسجيل حضور" });
    await user.click(button);
    await user.click(button);
    expect(punches(view.calls)).toHaveLength(1);
    expect(button).toBeDisabled();
    release?.();
    await waitFor(() => expect(button).toBeEnabled());
    expect(punches(view.calls)).toHaveLength(1);
  });
});

describe("AttendancePage: the last fortnight and the month", () => {
  it("lists the days with their mode, shift, times, hours and status, newest first", async () => {
    const view = open();
    await screen.findByText("2026-09-20");
    const rows = Array.from(view.container.querySelectorAll("tbody tr")).map((row) => row.getAttribute("data-day"));
    expect(rows).toEqual(["2026-09-20", "2026-09-19"]);
    const first = view.container.querySelector('[data-day="2026-09-20"]') as HTMLElement;
    expect(Array.from(first.querySelectorAll("td")).slice(0, 6).map((cell) => cell.textContent)).toEqual(["2026-09-20", "عن بُعد", "9:00 AM - 5:00 PM", "9:12 AM", "5:30 PM", "8:10"]);
    expect(within(first).getByText("حاضر")).toHaveClass("badge--ok");
    expect(within(first).getByText(/\+12د/)).toHaveClass("badge--wait");
    expect(within(first).getByText(/OT 30د/)).toHaveClass("badge--ok");
  });

  it("says a day with no mode or times has none, and that a check-out was missed", async () => {
    const view = open();
    await screen.findByText("2026-09-19");
    const second = view.container.querySelector('[data-day="2026-09-19"]') as HTMLElement;
    expect(Array.from(second.querySelectorAll("td")).slice(1, 5).map((cell) => cell.textContent)).toEqual(["—", "—", "—", "—"]);
    expect(within(second).getByText("غياب بدون إذن")).toHaveClass("badge--dead");
    expect(within(second).getByText("مسجلش انصراف")).toHaveClass("badge--dead");
  });

  it("says nothing is recorded when nothing is", async () => {
    open(() => card({ recent: [] }));
    expect(await screen.findByText("مفيش أيام مسجلة لسه.")).toBeInTheDocument();
  });

  it("shows this month's figures", async () => {
    const view = open();
    await screen.findByText("الشهر ده");
    const side = screen.getByText("الشهر ده").closest(".card") as HTMLElement;
    expect(Array.from(side.querySelectorAll(".kv b")).map((one) => one.textContent)).toEqual(["22", "15", "5", "10", "3 · 41د", "20د", "90د"]);
    expect(view.container.querySelector(".sticky-side")).not.toBeNull();
  });

  it("shows the person's devices with how each stands, and none when there are none", async () => {
    const first = open();
    const card3 = (await screen.findByText("أجهزتي")).closest(".card") as HTMLElement;
    expect(within(card3).getByText("abcdef0123")).toBeInTheDocument();
    expect(within(card3).getByText("معتمد")).toHaveClass("badge--ok");
    expect(within(card3).getByText("مستني موافقة")).toHaveClass("badge--wait");
    expect(within(card3).getByText("مرفوض")).toHaveClass("badge--dead");
    first.unmount();
    open(() => card({ devices: [] }));
    await screen.findByText("الشهر ده");
    expect(screen.queryByText("أجهزتي")).toBeNull();
  });
});

describe("AttendancePage: the page itself", () => {
  it("says it could not load, and loads", async () => {
    open(() => jsonResponse({ ok: false, error: "server" }, 500));
    expect(await screen.findByText("حصلت مشكلة في التحميل.")).toBeInTheDocument();
  });

  it("speaks English too", async () => {
    open(() => card(), undefined, "en");
    expect(await screen.findByText("My attendance", { selector: "h1" })).toBeInTheDocument();
    expect(await screen.findByText("Today")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check in" })).toBeInTheDocument();
    expect(screen.getByText("The last fortnight")).toBeInTheDocument();
    expect(screen.getByText("9:12 AM")).toBeInTheDocument();
  });
});
