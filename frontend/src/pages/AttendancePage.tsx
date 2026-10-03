import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { qk } from "../api/keys";
import { useAttendance } from "../api/queries";
import type { AttendanceCard, PunchAction } from "../api/types";
import { Icon } from "../components/Icon";
import { useToasts } from "../components/Toasts";
import { useNow } from "../hooks/useNow";
import { usePreferences } from "../i18n/Preferences";
import { outcome, postponed, punch, type Say } from "../lib/attendance";
import { cairoClock } from "../lib/clock";

type Day = AttendanceCard["day"];

/** The buttons the day offers right now - never one the server would refuse (`attendance.punch` still decides). */
export function offered(day: Day, now: number): Record<PunchAction, boolean> {
  const afterShift = day.shift_end !== null && now >= Date.parse(day.shift_end);
  const open = day.state === "open";
  return {
    check_in: day.state === "none",
    break_start: open && !day.on_break,
    break_end: open && day.on_break,
    extra_start: open && !day.on_break && !day.extra_running && afterShift,
    check_out: open,
  };
}

function Both({ value }: { value: { ar: string; en: string } | null }) {
  const { lang } = usePreferences();
  return <>{value ? (lang === "en" ? value.en : value.ar) : "—"}</>;
}

function PunchCard({ card }: { card: AttendanceCard }) {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const client = useQueryClient();
  const now = useNow(20000);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ text: string; tone: "ok" | "warn" | "muted" }>({ text: "", tone: "muted" });
  const { plan, day, conf } = card;
  const buttons = offered(day, now);

  const say: Say = (text, tone) => setStatus({ text: lang === "en" ? text[1] : text[0], tone: tone === "warn" ? "warn" : "muted" });

  const press = async (action: PunchAction) => {
    if (busy) return;
    setBusy(true);
    try {
      const answer = await punch(action, card.needs_location, say);
      const result = outcome(action, answer, lang);
      if (!result.ok) {
        setStatus({ text: result.text, tone: "warn" });
        push({ level: "warning", title: result.text });
        return;
      }
      setStatus({ text: result.text, tone: result.level === "warning" ? "warn" : "ok" });
      push({ level: result.level, title: result.text });
      // Pressing Extra time must not bring the extra-time screen straight back.
      if (action === "extra_start") postponed.snoozeExtra(card.work_date);
      // Whatever the screen over every page was asking, this answers it; the next beat says the rest.
      client.setQueryData(qk.gate, null);
      await client.invalidateQueries({ queryKey: qk.attendance });
    } catch {
      // No answer is not "no": the punch may have gone through, and the card asks again.
      setStatus({ text: t("مانفعش يتسجل. جرب تاني.", "Could not record it. Try again."), tone: "warn" });
      void client.invalidateQueries({ queryKey: qk.attendance });
    } finally {
      setBusy(false);
    }
  };

  const action = (name: PunchAction, icon: string, label: string, className = "btn btn--block") =>
    buttons[name] && (
      <button className={className} type="button" data-punch={name} disabled={busy} onClick={() => void press(name)}>
        <Icon name={icon} size="sm" />
        <span>{label}</span>
      </button>
    );

  return (
    <div className="card punch" id="punchCard" data-state={day.state} data-needs-location={card.needs_location ? "1" : "0"}>
      <div className="card__head">
        <Icon name="timer" />
        <h3>{t("اليوم", "Today")}</h3>
        <div className="grow" />
        {plan.working ? (
          <>
            <span className="chip mono">{plan.label}</span>
            <span className="badge badge--info">
              {plan.mode?.value === "remote" ? t("عن بُعد", "Remote") : t("من المكتب", "Office")}
            </span>
          </>
        ) : (
          <span className="badge">{t("مفيش شيفت النهارده", "Not rostered today")}</span>
        )}
      </div>

      <div className="punch__clock">
        <div className="punch__now mono" id="punchClock">
          {cairoClock(new Date(now), lang)}
        </div>
        <div className="punch__meta muted">
          {plan.working ? (
            <>
              <span>{t("الشيفت", "Shift")}</span>{" "}
              <span className="mono">
                <Both value={plan.start} /> – <Both value={plan.end} />
              </span>
              <span className="muted">·</span>
              <span>{t("سماح", "Grace")}</span> <span className="mono">{conf.grace_minutes}</span> <span>{t("دقايق", "min")}</span>
            </>
          ) : (
            <span>{t("تقدر تسجل برضه، والـHR هتراجعه.", "You can still punch; HR will review it.")}</span>
          )}
        </div>
      </div>

      <div className="punch__grid">
        <div className="punch__cell">
          <div className="punch__label">{t("حضور", "In")}</div>
          <div className="punch__value mono" data-field="check_in">
            <Both value={day.check_in} />
          </div>
        </div>
        <div className="punch__cell">
          <div className="punch__label">{t("انصراف", "Out")}</div>
          <div className="punch__value mono" data-field="check_out">
            <Both value={day.check_out} />
          </div>
        </div>
        <div className="punch__cell">
          <div className="punch__label">{t("بريك", "Break")}</div>
          <div className="punch__value mono" data-field="break_minutes">
            {day.break_minutes}
            {t("د", "m")}
          </div>
        </div>
        <div className="punch__cell">
          <div className="punch__label">{t("ساعات", "Hours")}</div>
          <div className="punch__value mono" data-field="hours">
            {day.hours}
          </div>
        </div>
      </div>

      <div className="punch__actions">
        {action("check_in", "play", t("تسجيل حضور", "Check in"), "btn btn--primary btn--block")}
        {action("break_start", "pause", t("ابدأ بريك", "Start break"))}
        {action("break_end", "play", t("إنهاء البريك", "End break"))}
        {action("extra_start", "plus", t("اكسترا تايم", "Extra time"))}
        {action("check_out", "stop", t("تسجيل انصراف", "Check out"), "btn btn--danger btn--block")}
      </div>

      {day.extra_started_at && (
        <div className="punch__extra" data-extra-line>
          <span className="badge badge--ok">{t("اكسترا تايم شغال", "Extra time running")}</span> <span>{t("من", "since")}</span>{" "}
          <span className="mono">
            <Both value={day.extra_started_at} />
          </span>
        </div>
      )}

      <div className={`punch__status ${status.tone}`} id="punchStatus" aria-live="polite">
        {status.text}
      </div>

      <div className="note note--warn mt">
        <Icon name="alert" />
        <div>
          <b>{t("لو نسيت تسجل انصراف، اليوم كله مش هيتحسب.", "Forget to check out and the whole day does not count.")}</b>{" "}
          <span>{t("مهلة الانصراف بعد نهاية الشيفت:", "Check-out window after the shift:")}</span>{" "}
          <span className="mono">{conf.missing_checkout_after_minutes}</span>{" "}
          <span>
            {t(
              "دقيقة. هتكمّل؟ دوس «اكسترا تايم» والـHR تراجعه (الساعة بساعة ونص).",
              "minutes. Staying on? Press Extra time and HR reviews it (paid at time and a half).",
            )}
          </span>
        </div>
      </div>

      {day.needs_review && (
        <div className="note note--warn">
          <Icon name="alert" />
          <div>
            {day.checkout_missed && (
              <b>{t("اليوم ده مش محسوب — مسجلتش انصراف في الميعاد.", "This day does not count - no check-out in time.")} </b>
            )}
            <span>{t("اليوم ده متعلّم للمراجعة:", "This day is flagged for review:")}</span> <span className="mono">{day.review_reason}</span>
          </div>
        </div>
      )}
    </div>
  );
}

function Fortnight({ card }: { card: AttendanceCard }) {
  const { t, lang } = usePreferences();
  return (
    <div className="card">
      <div className="card__head">
        <Icon name="history" />
        <h3>{t("آخر أسبوعين", "The last fortnight")}</h3>
      </div>
      <div className="table-wrap table-wrap--cards">
        <table className="table table--cards">
          <thead>
            <tr>
              <th>{t("اليوم", "Date")}</th>
              <th>{t("النظام", "Mode")}</th>
              <th>{t("الشيفت", "Shift")}</th>
              <th>{t("حضور", "In")}</th>
              <th>{t("انصراف", "Out")}</th>
              <th>{t("ساعات", "Hours")}</th>
              <th>{t("الحالة", "Status")}</th>
            </tr>
          </thead>
          <tbody>
            {card.recent.map((day) => (
              <tr key={day.date} data-day={day.date}>
                <td className="mono">{day.date}</td>
                <td>{day.mode ? <span className="chip">{lang === "en" ? day.mode.en : day.mode.ar}</span> : <span className="muted">—</span>}</td>
                <td className="mono muted">{day.schedule || "—"}</td>
                <td className="mono">
                  <Both value={day.check_in} />
                </td>
                <td className="mono">
                  <Both value={day.check_out} />
                </td>
                <td className="mono">{day.hours}</td>
                <td>
                  <span className={`badge${day.status.tone ? ` badge--${day.status.tone}` : ""}`}>{lang === "en" ? day.status.en : day.status.ar}</span>
                  {day.late_minutes > 0 && <span className="badge badge--wait mono"> +{day.late_minutes}{t("د", "m")}</span>}
                  {day.overtime_minutes > 0 && (
                    <span className="badge badge--ok mono"> OT {day.overtime_minutes}{t("د", "m")}</span>
                  )}
                  {day.checkout_missed && <span className="badge badge--dead">{t("مسجلش انصراف", "No check-out")}</span>}
                </td>
              </tr>
            ))}
            {card.recent.length === 0 && (
              <tr>
                <td colSpan={7} className="empty">
                  {t("مفيش أيام مسجلة لسه.", "Nothing recorded yet.")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Side({ card }: { card: AttendanceCard }) {
  const { t } = usePreferences();
  const { summary } = card;
  const row = (label: string, value: string | number) => (
    <div className="kv">
      <span>{label}</span>
      <b className="mono">{value}</b>
    </div>
  );
  return (
    <div className="sticky-side">
      <div className="card">
        <div className="card__head">
          <Icon name="chart" />
          <h3>{t("الشهر ده", "This month")}</h3>
        </div>
        {row(t("أيام مجدولة", "Scheduled days"), summary.scheduled_days)}
        {row(t("أيام حضور", "Days present"), summary.present_days)}
        {row(t("من المكتب", "Office"), summary.office_days)}
        {row(t("عن بُعد", "Remote"), summary.remote_days)}
        {row(t("مرات التأخير", "Late"), `${summary.late_days} · ${summary.late_minutes}${t("د", "m")}`)}
        {row(t("نقص ساعات", "Short"), `${summary.short_minutes}${t("د", "m")}`)}
        {row(t("أوفرتايم", "Overtime"), `${summary.overtime_minutes}${t("د", "m")}`)}
      </div>

      <div className="note note--info">
        <Icon name="shield" />
        <div>
          {t(
            "الموقع بيتقرا لحظة الضغط على الزرار بس. مفيش تتبع مستمر ولا كاميرا ولا لقطات شاشة.",
            "Your location is read at the moment you press the button, and at no other moment. No continuous tracking, no camera, no screenshots.",
          )}
        </div>
      </div>

      {card.devices.length > 0 && (
        <div className="card card--flat">
          <div className="card__head">
            <Icon name="shield-check" />
            <h3>{t("أجهزتي", "My devices")}</h3>
          </div>
          {card.devices.map((device, index) => (
            <div className="kv" key={`${device.label}-${index}`}>
              <span className="mono muted">{device.label}</span>
              {device.status === "approved" ? (
                <span className="badge badge--ok">{t("معتمد", "Approved")}</span>
              ) : device.status === "pending" ? (
                <span className="badge badge--wait">{t("مستني موافقة", "Pending")}</span>
              ) : (
                <span className="badge badge--dead">{t("مرفوض", "Rejected")}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** The person's own attendance: today's punch card, the last fortnight read only, this month, their devices. */
export function AttendancePage() {
  const { t } = usePreferences();
  const query = useAttendance();
  const card = query.data;

  return (
    <>
      <div className="page-head">
        <h1>{t("حضوري", "My attendance")}</h1>
        {card && <div className="page-head__sub mono">{card.work_date}</div>}
      </div>

      {card ? (
        <div className="grid grid--main">
          <div className="stack">
            <PunchCard card={card} />
            <Fortnight card={card} />
          </div>
          <Side card={card} />
        </div>
      ) : query.isError ? (
        <div className="card empty" role="alert">
          <Icon name="alert" size="xl" />
          <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
        </div>
      ) : (
        <div className="card empty">
          <Icon name="refresh" size="xl" />
          <span>{t("بيحمّل...", "Loading...")}</span>
        </div>
      )}
    </>
  );
}
