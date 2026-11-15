import { useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../api/client";
import type { ShiftPickerData } from "../api/types";
import { Icon } from "./Icon";
import { useToasts } from "./Toasts";
import { usePreferences } from "../i18n/Preferences";
import { shiftHours, shiftName, shiftTitle } from "../lib/shiftHours";

/** Why a shift choice was refused, in words (`shiftpick`'s codes). */
const SHIFT_PROBLEMS: Record<string, [string, string]> = {
  bad_new_shift: ["اكتب وقت بداية ونهاية الشيفت الجديد.", "Write a start and an end time for the new shift."],
  no_such_shift: ["الشيفت ده مش موجود.", "That shift does not exist."],
  no_days: ["اختار أيام الشغل.", "Pick the working days."],
  no_such_lead: ["التيم ليدر ده مش موجود.", "That team leader does not exist."],
  lead_not_translator: ["التيم ليدر للمترجمين بس.", "A team leader is for translators only."],
  no_first_shift: ["اختار الشيفت الأولاني الأول قبل الشيفت التاني.", "Pick the first shift before the second one."],
  shifts_overlap: ["الشيفت التاني داخل في مواعيد الشيفت الأولاني — اختار شيفت مواعيده بعده.", "The second shift overlaps the first - pick one with later hours."],
};

export interface ShiftChoice {
  template: string;
  weekdays: number[];
  new_name: string;
  new_start: string;
  new_end: string;
  team_lead?: string;
  second?: { template: string; weekdays: number[]; team_lead: string } | null;
}

/**
 * The company's shifts to pick from, the working days, and a shift nobody has made yet. It is the same card for the admin's staff
 * page and HR's employee file: `save` is whichever door the page uses, and the rule (`shiftpick`) is the same behind both.
 */
export function ShiftPicker({
  picker,
  save,
  pending,
}: {
  picker: ShiftPickerData;
  save: (choice: ShiftChoice, options: { onSuccess: (answer: { label: string }) => void; onError: (error: unknown) => void }) => void;
  pending: boolean;
}) {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const [choice, setChoice] = useState(String(picker.current ?? ""));
  const [days, setDays] = useState<number[]>(picker.days.filter((day) => day.checked).map((day) => day.num));
  const [fresh, setFresh] = useState({ name: "", start: "", end: "" });
  const [problem, setProblem] = useState("");
  const [lead, setLead] = useState(String(picker.lead ?? ""));
  const [second, setSecond] = useState(String(picker.second.current ?? ""));
  const [secondDays, setSecondDays] = useState<number[]>(picker.second.days);
  const [secondLead, setSecondLead] = useState(String(picker.second.lead ?? ""));

  useEffect(() => {
    setChoice(String(picker.current ?? ""));
    setDays(picker.days.filter((day) => day.checked).map((day) => day.num));
    setLead(String(picker.lead ?? ""));
    setSecond(String(picker.second.current ?? ""));
    setSecondDays(picker.second.days);
    setSecondLead(String(picker.second.lead ?? ""));
  }, [picker]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setProblem("");
    save(
      {
        template: choice,
        weekdays: days,
        new_name: fresh.name,
        new_start: fresh.start,
        new_end: fresh.end,
        // The leaders are a translator's only: for anybody else they are not sent, so they stay as they are.
        ...(picker.leads ? { team_lead: lead } : {}),
        second: second ? { template: second, weekdays: secondDays.length ? secondDays : days, team_lead: secondLead } : null,
      },
      {
        onSuccess: (answer) => push({ level: "success", title: answer.label || t("اتشال الشيفت", "The shift was taken off") }),
        onError: (error) => {
          const code = error instanceof ApiError ? error.code : "";
          const words = SHIFT_PROBLEMS[code];
          setProblem(words ? t(...words) : t("حصلت مشكلة، ماتحفظش.", "Something went wrong, nothing was saved."));
        },
      },
    );
  };

  return (
    <div className="card" data-card="picker">
      <div className="card__head">
        <Icon name="clock" />
        <h3>{t("الشيفت", "Shift")}</h3>
      </div>
      <form onSubmit={submit}>
        {picker.templates.map((template) => (
          <label className="kv" style={{ cursor: "pointer" }} key={template.id}>
            <span>
              <input type="radio" name="template" value={template.id} checked={choice === String(template.id)} onChange={() => setChoice(String(template.id))} />{" "}
              <b>{shiftName(template.label) || shiftHours(template.start, template.end, lang)}</b>
            </span>
            {shiftName(template.label) && <span>{shiftHours(template.start, template.end, lang)}</span>}
          </label>
        ))}
        <label className="kv" style={{ cursor: "pointer" }}>
          <span>
            <input type="radio" name="template" value="" checked={choice === ""} onChange={() => setChoice("")} /> {t("من غير شيفت", "No shift")}
          </span>
        </label>
        <label className="kv" style={{ cursor: "pointer" }}>
          <span>
            <input type="radio" name="template" value="new" checked={choice === "new"} onChange={() => setChoice("new")} /> <b>{t("شيفت جديد", "New shift")}</b>
          </span>
        </label>
        <div className="row row--tight" style={{ flexWrap: "wrap" }}>
          <input
            className="input"
            type="text"
            maxLength={60}
            style={{ flex: "1 1 9rem" }}
            placeholder={t("اسم الشيفت (اختياري)", "Shift name (optional)")}
            aria-label={t("اسم الشيفت", "Shift name")}
            value={fresh.name}
            onChange={(event) => setFresh({ ...fresh, name: event.target.value })}
          />
          <input className="input" type="time" dir="ltr" aria-label={t("من", "From")} style={{ flex: "0 1 7rem" }} value={fresh.start} onChange={(event) => setFresh({ ...fresh, start: event.target.value })} />
          <input className="input" type="time" dir="ltr" aria-label={t("إلى", "To")} style={{ flex: "0 1 7rem" }} value={fresh.end} onChange={(event) => setFresh({ ...fresh, end: event.target.value })} />
        </div>
        <p className="muted" style={{ fontSize: ".8rem" }}>
          {t(
            "لو النهاية قبل البداية (مثلًا 5 م لـ 1 ص) الشيفت بيعدّي نص الليل وبيتحسب على يوم بدايته. لو فيه شيفت بنفس المواعيد هيتستخدم هو.",
            "If the end is before the start (e.g. 5 PM to 1 AM) the shift crosses midnight and counts on the day it started. A shift with the same hours is reused.",
          )}
        </p>
        <div className="field">
          <label>{t("أيام الشغل", "Working days")}</label>
          <div className="row row--tight" style={{ flexWrap: "wrap" }}>
            {picker.days.map((day) => (
              <label className="chip" style={{ cursor: "pointer" }} key={day.num}>
                <input
                  type="checkbox"
                  checked={days.includes(day.num)}
                  onChange={(event) => setDays(event.target.checked ? [...days, day.num] : days.filter((item) => item !== day.num))}
                />
                <span>{lang === "ar" ? day.ar : day.en}</span>
              </label>
            ))}
          </div>
        </div>
        {picker.leads && (
          <div className="field">
            <label htmlFor="shift-lead">{t("تيم ليدر الشيفت ده", "This shift's team leader")}</label>
            <select id="shift-lead" className="input" value={lead} onChange={(event) => setLead(event.target.value)}>
              <option value="">{t("من غير تيم ليدر", "No team leader")}</option>
              {picker.leads.map((one) => (
                <option key={one.id} value={one.id}>
                  {one.name}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="field" data-part="second-shift">
          <label htmlFor="second-shift">{t("شيفت تاني في نفس اليوم", "A second shift the same day")}</label>
          <select id="second-shift" className="input" value={second} onChange={(event) => setSecond(event.target.value)}>
            <option value="">{t("مفيش شيفت تاني", "No second shift")}</option>
            {picker.templates.map((template) => (
              <option key={template.id} value={template.id}>
                {shiftTitle(template.label, template.start, template.end, lang)}
              </option>
            ))}
          </select>
        </div>
        {second && (
          <>
            <div className="field">
              <label>{t("أيام الشيفت التاني", "Second shift days")}</label>
              <div className="row row--tight" style={{ flexWrap: "wrap" }}>
                {picker.days.map((day) => (
                  <label className="chip" style={{ cursor: "pointer" }} key={day.num}>
                    <input
                      type="checkbox"
                      checked={(secondDays.length ? secondDays : days).includes(day.num)}
                      onChange={(event) => {
                        const now = secondDays.length ? secondDays : days;
                        setSecondDays(event.target.checked ? [...now, day.num] : now.filter((item) => item !== day.num));
                      }}
                    />
                    <span>{lang === "ar" ? day.ar : day.en}</span>
                  </label>
                ))}
              </div>
            </div>
            {picker.leads && (
              <div className="field">
                <label htmlFor="second-lead">{t("تيم ليدر الشيفت التاني", "Second shift team leader")}</label>
                <select id="second-lead" className="input" value={secondLead} onChange={(event) => setSecondLead(event.target.value)}>
                  <option value="">{t("نفس تيم ليدر الشيفت الأولاني", "Same as the first shift's")}</option>
                  {picker.leads.map((one) => (
                    <option key={one.id} value={one.id}>
                      {one.name}
                    </option>
                  ))}
                </select>
              </div>
            )}
            <p className="muted" style={{ fontSize: ".8rem" }}>
              {t(
                "المترجم بيظهر في فريق الليدرين، وتاسك بتتبعتله مباشرة بتروح لليدر الشيفت اللي هو فيه ساعتها. الحضور والانصراف لسه على الشيفت الأولاني بس.",
                "The translator shows in both leaders' teams, and a task sent to them directly goes to the leader of the shift they are on. Attendance is still kept on the first shift only.",
              )}
            </p>
          </>
        )}
        {picker.has_custom && (
          <p className="muted" style={{ fontSize: ".8rem" }}>
            {t("عنده جدول مخصص دلوقتي — الحفظ هيستبدله بالشيفت اللي اخترته.", "There is a custom schedule now - saving replaces it with the chosen shift.")}
          </p>
        )}
        <p className="muted" style={{ fontSize: ".8rem" }}>
          {t("الأيام اللي اتسجلت قبل كده بتفضل على الشيفت اللي اشتغل بيه. التوقيت بتوقيت مصر.", "Days already recorded keep the shift they were worked under. Times are Egypt time.")}
        </p>
        {problem && (
          <div className="note note--high" role="alert">
            <Icon name="alert" />
            <div>{problem}</div>
          </div>
        )}
        <button className="btn btn--primary btn--sm btn--block" type="submit" disabled={pending}>
          <Icon name="check" size="sm" />
          <span>{t("احفظ الشيفت", "Save shift")}</span>
        </button>
      </form>
    </div>
  );
}
