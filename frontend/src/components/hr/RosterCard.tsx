import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { formErrors, useAddShift, useDeleteShift } from "../../api/adminActions";
import type { HrRosterRow, ShiftPickerData } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { Icon } from "../Icon";
import { useLeaveWords } from "../leave/shared";
import { useStamp } from "./shared";

/** The weekdays a typed row may name, in the order the picker gives them. */
type Days = ShiftPickerData["days"];

/** The box that adds one roster row of typed times. The admin's: the same rule as the classic box (`shiftpick.typed_shift_form`). */
function TypedShift({ id, days }: { id: number; days: Days }) {
  const { t, lang } = usePreferences();
  const add = useAddShift(id);
  const [row, setRow] = useState({ weekday: String(days[0]?.num ?? 0), start: "", end: "" });
  const [problem, setProblem] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setProblem("");
    add.mutate(
      { weekday: Number(row.weekday), start_time: row.start, end_time: row.end },
      {
        onSuccess: () => setRow({ ...row, start: "", end: "" }),
        onError: (error) => {
          const errors = formErrors(error);
          const first = errors ? Object.values(errors).flat()[0] : "";
          setProblem(first || t("اكتب وقت البداية والنهاية.", "Write the start and the end."));
        },
      },
    );
  };

  return (
    <form onSubmit={submit} className="mt" data-form="typed-shift">
      <div className="form-grid">
        <div className="field">
          <label htmlFor="shift-day">{t("اليوم", "Day")}</label>
          <select id="shift-day" className="input" value={row.weekday} onChange={(event) => setRow({ ...row, weekday: event.target.value })}>
            {days.map((day) => (
              <option key={day.num} value={day.num}>
                {lang === "ar" ? day.ar : day.en}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="shift-from">{t("من", "From")}</label>
          <input id="shift-from" className="input" type="time" dir="ltr" value={row.start} onChange={(event) => setRow({ ...row, start: event.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="shift-to">{t("إلى", "To")}</label>
          <input id="shift-to" className="input" type="time" dir="ltr" value={row.end} onChange={(event) => setRow({ ...row, end: event.target.value })} />
        </div>
      </div>
      {problem && (
        <div className="note note--high" role="alert">
          <Icon name="alert" />
          <div>{problem}</div>
        </div>
      )}
      <button className="btn btn--sm btn--block" type="submit" disabled={add.isPending}>
        <Icon name="plus" size="sm" />
        <span>{t("ضيف شيفت", "Add shift")}</span>
      </button>
    </form>
  );
}

/**
 * A person's roster: the rows of typed times. HR reads it and goes to the schedules to change it; the admin also takes a row off and
 * adds one here (`editable`), which is the one place that does both, so the file has one roster and not two.
 */
export function RosterCard({ id, rows, days, editable }: { id: number; rows: HrRosterRow[]; days: Days | null; editable: boolean }) {
  const { t } = usePreferences();
  const words = useLeaveWords();
  const stamp = useStamp();
  const remove = useDeleteShift(id);

  return (
    <div className="card" data-card="roster">
      <div className="card__head">
        <Icon name="calendar" />
        <h3>{t("الجدول", "Roster")}</h3>
      </div>
      {editable && (
        <p className="muted" style={{ fontSize: ".8rem" }}>
          {t("الحالة (نشط / أوفلاين) بتتحسب من الشيفتات دي.", "Presence (online / offline) is computed from these shifts.")}
        </p>
      )}
      {rows.map((row) => (
        <div className="kv" key={row.id} data-shift={row.id}>
          <span>{words(row.weekday)}</span>
          <b className="mono">
            {stamp(row.start)}–{stamp(row.end)}
          </b>
          {editable && (
            <button
              className="icon-btn"
              type="button"
              style={{ width: 28, height: 28 }}
              title={t("امسح الشيفت", "Delete the shift")}
              aria-label={t("امسح الشيفت", "Delete the shift")}
              disabled={remove.isPending}
              onClick={() => remove.mutate(row.id)}
            >
              <Icon name="trash" size="sm" />
            </button>
          )}
        </div>
      ))}
      {rows.length === 0 && <div className="muted">{t("مفيش جدول لسه.", "No roster yet.")}</div>}
      {editable && days && <TypedShift id={id} days={days} />}
      <Link className="btn btn--sm btn--block mt" to={`/hr/schedules?user=${id}`}>
        <Icon name="pen" size="sm" />
        <span>{t("عدّل الجدول", "Edit the roster")}</span>
      </Link>
    </div>
  );
}
