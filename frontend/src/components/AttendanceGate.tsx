import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { qk } from "../api/keys";
import { useGate } from "../api/queries";
import type { AttendanceGate as Gate, PunchAction } from "../api/types";
import { useNow } from "../hooks/useNow";
import { usePreferences } from "../i18n/Preferences";
import { outcome, postponed, punch, type Say } from "../lib/attendance";
import { cairoClock } from "../lib/clock";
import { Icon } from "./Icon";
import { useToasts } from "./Toasts";

function Fact({ label, value, mono = true }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="kv">
      <span>{label}</span>
      <b className={mono ? "mono" : undefined}>{value || "—"}</b>
    </div>
  );
}

/**
 * The check-in screen, and the reminders after the shift. The server decides when it opens (`attendance.gate_for`,
 * carried by the heartbeat); this only draws what it asks, over whatever page the person is on, exactly as the
 * classic page does (`templates/partials/attendance_gate.html`):
 *
 *  - `check_in`: a shift is on and nobody has checked in. It stays until they do: no Escape, no click outside, no
 *    close button, and the page behind it cannot be reached (it is inert) - so it cannot be skipped by accident.
 *  - `check_out`: the shift is over and the day is still open. «بعدين» puts it off for the rest of the session, because
 *    the check-in screen is the one that must not be skipped, not this reminder; but a forgotten check-out costs the
 *    whole day, so it says so.
 *  - `extra`: extra time is running. «لسه شغال» puts it off for an hour, and it comes back.
 *
 * A position is read at the moment a button is pressed and at no other (`lib/attendance.ts`).
 */
export function AttendanceGate() {
  const { t, lang } = usePreferences();
  const gate = useGate();
  const client = useQueryClient();
  const { push } = useToasts();
  const now = useNow(15000);
  const titleId = useId();
  const [, redraw] = useState(0);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ text: string; tone?: "warn" } | null>(null);
  const box = useRef<HTMLDivElement>(null);

  const shown = gate !== null && !postponed.hides(gate, now) ? gate : null;
  const kind = shown?.kind ?? null;

  // The page behind it cannot be reached while it is up (a keyboard would otherwise tab straight past it).
  useEffect(() => {
    if (kind === null) return;
    const shell = document.querySelector(".shell");
    shell?.setAttribute("inert", "");
    document.documentElement.classList.add("has-gate");
    return () => {
      shell?.removeAttribute("inert");
      document.documentElement.classList.remove("has-gate");
    };
  }, [kind]);

  // A new screen takes the focus: the person's next key press is on its button.
  useEffect(() => {
    if (kind !== null) box.current?.querySelector<HTMLElement>("[data-gate-punch]")?.focus();
  }, [kind]);

  // A message about the last punch belongs to the screen it was about.
  useEffect(() => setStatus(null), [kind]);

  if (shown === null) return null;

  const say: Say = (text, tone) => setStatus({ text: lang === "en" ? text[1] : text[0], tone });

  const press = async (action: PunchAction, current: Gate) => {
    if (busy) return;
    setBusy(true);
    setStatus(null);
    try {
      const answer = await punch(action, current.needs_location, say);
      const result = outcome(action, answer, lang);
      if (!result.ok) {
        setStatus({ text: result.text, tone: "warn" });
        push({ level: "warning", title: result.text });
        return;
      }
      push({ level: result.level, title: result.text });
      // Pressing Extra time must not bring the extra-time screen straight back.
      if (action === "extra_start") postponed.snoozeExtra(current.date);
      client.setQueryData(qk.gate, null);
      void client.invalidateQueries({ queryKey: qk.attendance });
    } catch {
      // No answer is not "no": the punch may have gone through, and the next beat says so.
      setStatus({ text: t("مانفعش يتسجل. جرب تاني.", "Could not record it. Try again."), tone: "warn" });
    } finally {
      setBusy(false);
    }
  };

  const later = (current: Gate) => {
    if (current.kind === "check_out") postponed.dismiss(current);
    else if (current.kind === "extra") postponed.snoozeExtra(current.date);
    redraw((count) => count + 1);
  };

  const pick = (both: { ar: string; en: string }) => (lang === "en" ? both.en : both.ar);
  const punchButton = (action: PunchAction, current: Gate, icon: string, label: string, danger = false): ReactNode => (
    <button
      className={`btn ${danger ? "btn--danger" : action === "check_in" ? "btn--primary btn--block" : ""}`}
      type="button"
      data-gate-punch={action}
      disabled={busy}
      onClick={() => void press(action, current)}
    >
      <Icon name={icon} size="sm" />
      <span>{label}</span>
    </button>
  );

  return (
    <div className="modal-backdrop gate" role="dialog" aria-modal="true" aria-labelledby={titleId} data-gate={shown.kind}>
      <div className="modal gate__box" ref={box}>
        {shown.kind === "check_in" && (
          <div>
            <div className="ask__icon">
              <Icon name="timer" />
            </div>
            <div className="modal__title" id={titleId}>
              {t("سجّل حضورك", "Check in")}
            </div>
            <div className="punch__now mono" data-gate-clock>
              {cairoClock(new Date(now), lang)}
            </div>
            <div className="card card--flat gate__facts">
              <Fact label={t("الشيفت", "Shift")} value={shown.shift} mono={false} />
              <Fact label={t("بيبدأ", "Starts")} value={pick(shown.start)} />
              <Fact label={t("آخر ميعاد من غير تأخير", "On time until")} value={pick(shown.grace_until)} />
            </div>
            {shown.late_now > 0 && (
              <div className="note note--warn" data-gate-late>
                <Icon name="alert" />
                <div>
                  <span>{t("انت متأخر", "You are late by")}</span> <b className="mono">{shown.late_now}</b>{" "}
                  <span>{t("دقيقة — التأخير هيتحسب ويتحوّل للـHR.", "minutes - it will be counted and sent to HR.")}</span>
                </div>
              </div>
            )}
            <ul className="gate__rules">
              <li>
                <span>{t("مسموح بـ", "You have")}</span> <b className="mono">{shown.grace}</b>{" "}
                <span>
                  {t("دقايق بس. بعدها التأخير كله بيتحسب وبيتحوّل للـHR.", "minutes of grace. After that the whole delay counts and goes to HR.")}
                </span>
              </li>
              <li>
                <b>{t("لو نسيت تسجل انصراف، اليوم كله مش هيتحسب.", "Forget to check out and the whole day does not count.")}</b>
              </li>
              <li>
                {t(
                  "هتكمّل بعد الشيفت؟ دوس «اكسترا تايم» الأول عشان الـHR تحسبه.",
                  "Staying after the shift? Press Extra time first so HR can count it.",
                )}
              </li>
            </ul>
            <div className="modal__actions row">{punchButton("check_in", shown, "play", t("تسجيل حضور", "Check in"))}</div>
          </div>
        )}

        {shown.kind === "check_out" && (
          <div>
            <div className="ask__icon is-danger">
              <Icon name="clock" />
            </div>
            <div className="modal__title" id={titleId}>
              {t("الشيفت خلص", "Your shift is over")}
            </div>
            <div className="punch__now mono" data-gate-clock>
              {cairoClock(new Date(now), lang)}
            </div>
            <div className="card card--flat gate__facts">
              <Fact label={t("نهاية الشيفت", "Shift ended")} value={pick(shown.end)} />
              <Fact label={t("سجّل انصراف قبل", "Check out before")} value={pick(shown.deadline)} />
            </div>
            <div className="note note--warn">
              <Icon name="alert" />
              <div>
                {t(
                  "لو مسجلتش انصراف قبل الميعاد ده، اليوم كله مش هيتحسب. ولو هتكمّل شغل، دوس «اكسترا تايم»: الساعة بتتحسب بساعة ونص والتيم ليدر والأدمن بيتبلّغوا، ولازم تسجّل انصراف لما تخلص.",
                  "No check-out before this time and the whole day does not count. Staying on? Press Extra time: it is paid at time and a half, your team leader and the admins are told, and you must check out when you finish.",
                )}
              </div>
            </div>
            <div className="modal__actions row">
              {punchButton("check_out", shown, "stop", t("تسجيل انصراف", "Check out"), true)}
              {punchButton("extra_start", shown, "plus", t("اكسترا تايم", "Extra time"))}
              <button className="btn btn--ghost" type="button" data-gate-later disabled={busy} onClick={() => later(shown)}>
                <span>{t("بعدين", "Later")}</span>
              </button>
            </div>
          </div>
        )}

        {shown.kind === "extra" && (
          <div>
            <div className="ask__icon">
              <Icon name="timer" />
            </div>
            <div className="modal__title" id={titleId}>
              {t("الاكسترا تايم شغال", "Extra time is running")}
            </div>
            <div className="punch__now mono" data-gate-clock>
              {cairoClock(new Date(now), lang)}
            </div>
            <div className="card card--flat gate__facts">
              <Fact label={t("الشيفت خلص", "Shift ended")} value={pick(shown.end)} />
              <Fact label={t("الاكسترا بدأ", "Extra time since")} value={pick(shown.extra_since)} />
              <Fact label={t("سجّل انصراف قبل", "Check out before")} value={pick(shown.deadline)} />
            </div>
            <div className="note note--warn">
              <Icon name="alert" />
              <div>
                {t(
                  "لما تخلّص اكسترا تايم لازم تسجّل انصراف. لو مسجلتش قبل الميعاد ده، اليوم كله مش هيتحسب.",
                  "When you finish your extra time you must check out. No check-out before this time and the whole day does not count.",
                )}
              </div>
            </div>
            <div className="modal__actions row">
              {punchButton("check_out", shown, "stop", t("خلّصت — تسجيل انصراف", "Done - check out"), true)}
              <button className="btn btn--ghost" type="button" data-gate-later disabled={busy} onClick={() => later(shown)}>
                <span>{t("لسه شغال", "Still working")}</span>
              </button>
            </div>
          </div>
        )}

        <div className={`punch__status ${status?.tone === "warn" ? "warn" : "muted"}`} data-gate-status aria-live="polite">
          {status?.text}
        </div>
      </div>
    </div>
  );
}
