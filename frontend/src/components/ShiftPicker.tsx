import { useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../api/client";
import type { ShiftPickerData } from "../api/types";
import { Icon } from "./Icon";
import { useToasts } from "./Toasts";
import { usePreferences } from "../i18n/Preferences";

/** Why a shift choice was refused, in words (`shiftpick`'s codes). */
const SHIFT_PROBLEMS: Record<string, [string, string]> = {
  bad_new_shift: ["اكتب وقت بداية ونهاية الشيفت الجديد.", "Write a start and an end time for the new shift."],
  no_such_shift: ["الشيفت ده مش موجود.", "That shift does not exist."],
  no_days: ["اختار أيام الشغل.", "Pick the working days."],
};

export interface ShiftChoice {
  template: string;
  weekdays: number[];
  new_name: string;
  new_start: string;
  new_end: string;
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

  useEffect(() => {
    setChoice(String(picker.current ?? ""));
    setDays(picker.days.filter((day) => day.checked).map((day) => day.num));
  }, [picker]);

  const time = (value: { ar: string; en: string } | null) => (value ? (lang === "ar" ? value.ar : value.en) : "");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setProblem("");
    save(
      { template: choice, weekdays: days, new_name: fresh.name, new_start: fresh.start, new_end: fresh.end },
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
              <b>{template.label}</b>
            </span>
            <span className="mono">
              {time(template.start)} – {time(template.end)}
            </span>
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
