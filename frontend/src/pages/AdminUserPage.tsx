import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router";
import {
  formErrors,
  useAddShift,
  useCreateUser,
  useDeleteShift,
  usePickShift,
  useSaveUser,
  useSyncAliases,
} from "../api/adminActions";
import { ApiError } from "../api/client";
import { useAdminUser, useAdminUserNew, useMe } from "../api/queries";
import type { AdminUser, FormErrors } from "../api/types";
import { DjangoForm, useFormEdits } from "../components/admin/DjangoForm";
import { Icon } from "../components/Icon";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

/** Why a shift choice was refused, in words (`shiftpick`'s codes). */
const SHIFT_PROBLEMS: Record<string, [string, string]> = {
  bad_new_shift: ["اكتب وقت بداية ونهاية الشيفت الجديد.", "Write a start and an end time for the new shift."],
  no_such_shift: ["الشيفت ده مش موجود.", "That shift does not exist."],
  no_days: ["اختار أيام الشغل.", "Pick the working days."],
};

function useLoading() {
  const { t } = usePreferences();
  return (error: boolean) =>
    error ? (
      <div className="card empty" role="alert">
        <Icon name="alert" size="xl" />
        <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
      </div>
    ) : (
      <div className="card empty">
        <Icon name="refresh" size="xl" />
        <span>{t("بيحمّل...", "Loading...")}</span>
      </div>
    );
}

/** The company's shifts to pick from, the working days, and a shift nobody has made yet. */
function ShiftPicker({ id, picker }: { id: number; picker: AdminUser["picker"] }) {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const pick = usePickShift(id);
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
    pick.mutate(
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
        <button className="btn btn--primary btn--sm btn--block" type="submit" disabled={pick.isPending}>
          <Icon name="check" size="sm" />
          <span>{t("احفظ الشيفت", "Save shift")}</span>
        </button>
      </form>
    </div>
  );
}

/** The roster rows of typed times, and the box that adds one. */
function ShiftList({ id, data }: { id: number; data: AdminUser }) {
  const { t, lang } = usePreferences();
  const add = useAddShift(id);
  const remove = useDeleteShift(id);
  const [row, setRow] = useState({ weekday: String(data.picker.days[0]?.num ?? 0), start: "", end: "" });
  const [problem, setProblem] = useState("");
  const time = (value: { ar: string; en: string } | null) => (value ? (lang === "ar" ? value.ar : value.en) : "");

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
    <div className="card" data-card="shifts">
      <div className="card__head">
        <Icon name="calendar" />
        <h3>{t("الشيفتات", "Shifts")}</h3>
      </div>
      <p className="muted" style={{ fontSize: ".8rem" }}>
        {t("الحالة (نشط / أوفلاين) بتتحسب من الشيفتات دي.", "Presence (online / offline) is computed from these shifts.")}
      </p>
      <ul className="timeline">
        {data.shifts.map((shift) => (
          <li key={shift.id} data-shift={shift.id}>
            <span className="grow">{lang === "ar" ? shift.weekday.ar : shift.weekday.en}</span>
            <span className="mono">
              {time(shift.start)} → {time(shift.end)}
            </span>
            <button
              className="icon-btn"
              type="button"
              style={{ width: 28, height: 28 }}
              title={t("امسح الشيفت", "Delete the shift")}
              aria-label={t("امسح الشيفت", "Delete the shift")}
              disabled={remove.isPending}
              onClick={() => remove.mutate(shift.id)}
            >
              <Icon name="trash" size="sm" />
            </button>
          </li>
        ))}
        {data.shifts.length === 0 && <li className="muted">{t("مفيش شيفتات.", "No shifts.")}</li>}
      </ul>
      <form onSubmit={submit} className="mt">
        <div className="form-grid">
          <div className="field">
            <label htmlFor="shift-day">{t("اليوم", "Day")}</label>
            <select id="shift-day" className="input" value={row.weekday} onChange={(event) => setRow({ ...row, weekday: event.target.value })}>
              {data.picker.days.map((day) => (
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
      <a className="btn btn--sm btn--ghost btn--block mt" href={`/hr/schedules/?user=${data.user.id}`}>
        <Icon name="calendar" size="sm" />
        <span>{t("الجدول الكامل ونظام العمل", "Full schedule and work mode")}</span>
      </a>
    </div>
  );
}

/** One person's file: the form, the shift they are on, their roster rows and their rating penalties. */
export function AdminUserPage() {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const loading = useLoading();
  const params = useParams();
  const id = Number(params.id);
  const me = useMe();
  const allowed = me.data !== undefined && me.data.user.is_admin;
  const query = useAdminUser(id, allowed);
  const save = useSaveUser(id);
  const sync = useSyncAliases(id);
  const edits = useFormEdits(query.data?.form);
  const [errors, setErrors] = useState<FormErrors>({});
  const [failed, setFailed] = useState(false);

  // The address list is Google's: refreshed as the file opens (at most once a minute, the server decides), then read again.
  const asked = sync.mutate;
  useEffect(() => {
    if (allowed && Number.isInteger(id) && id > 0) asked();
  }, [allowed, id, asked]);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!Number.isInteger(id) || id <= 0) return <Navigate to="/admin/users" replace />;
  const data = query.data;
  if (!data) return loading(query.isError);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    setFailed(false);
    save.mutate(edits.edited, {
      onSuccess: () => {
        edits.reset();
        push({ level: "success", title: t("اتحفظ", "Saved") });
      },
      onError: (error) => {
        const found = formErrors(error);
        if (found) setErrors(found);
        else setFailed(true);
      },
    });
  };

  return (
    <>
      <div className="page-head">
        <h1>{data.user.name}</h1>
        <span className="chip">{lang === "ar" ? data.user.role.ar : data.user.role.en}</span>
        <div className="grow" />
        <Link className="btn btn--sm" to="/admin/users">
          {t("كل الموظفين", "All staff")}
        </Link>
      </div>

      <div className="grid grid--main">
        <div className="card">
          <form onSubmit={submit}>
            <DjangoForm fields={data.form} edits={edits} errors={errors} prefix="staff" />
            {failed && (
              <div className="note note--high" role="alert">
                <Icon name="alert" />
                <div>{t("حصلت مشكلة، ماتحفظش.", "Something went wrong, nothing was saved.")}</div>
              </div>
            )}
            <button className="btn btn--primary" type="submit" disabled={save.isPending || !edits.dirty}>
              <Icon name="check" size="sm" />
              <span>{t("حفظ", "Save")}</span>
            </button>
          </form>
        </div>

        <div className="sticky-side">
          <ShiftPicker id={id} picker={data.picker} />
          <ShiftList id={id} data={data} />
          <div className="card" data-card="penalties">
            <div className="card__head">
              <Icon name="star" />
              <h3>{t("خصومات التقييم", "Rating penalties")}</h3>
            </div>
            <ul className="timeline">
              {data.events.map((event, index) => (
                <li key={index}>
                  <span className="badge badge--dead mono">{event.delta}</span>
                  <span className="grow">{event.reason}</span>
                  <small className="muted mono">{event.at ? (lang === "ar" ? event.at.ar : event.at.en) : ""}</small>
                </li>
              ))}
              {data.events.length === 0 && <li className="muted">{t("مفيش خصومات.", "No penalties.")}</li>}
            </ul>
          </div>
        </div>
      </div>
    </>
  );
}

/** A new person. The password is typed here, goes in the one request that makes them, and is read back by nobody. */
export function AdminUserNewPage() {
  const { t } = usePreferences();
  const loading = useLoading();
  const navigate = useNavigate();
  const me = useMe();
  const allowed = me.data !== undefined && me.data.user.is_admin;
  const query = useAdminUserNew(allowed);
  const create = useCreateUser();
  const edits = useFormEdits(query.data?.form);
  const [errors, setErrors] = useState<FormErrors>({});
  const [failed, setFailed] = useState(false);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  const data = query.data;
  if (!data) return loading(query.isError);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    setFailed(false);
    create.mutate(edits.edited, {
      onSuccess: (answer) => navigate(`/admin/users/${answer.id}`),
      onError: (error) => {
        const found = formErrors(error);
        if (found) setErrors(found);
        else setFailed(true);
      },
    });
  };

  return (
    <>
      <div className="page-head">
        <h1>{t("موظف جديد", "New staff member")}</h1>
        <div className="grow" />
        <Link className="btn btn--sm" to="/admin/users">
          {t("كل الموظفين", "All staff")}
        </Link>
      </div>
      <div className="card">
        <form onSubmit={submit}>
          <DjangoForm fields={data.form} edits={edits} errors={errors} prefix="new" />
          {failed && (
            <div className="note note--high" role="alert">
              <Icon name="alert" />
              <div>{t("حصلت مشكلة، ماتعملش.", "Something went wrong, nobody was made.")}</div>
            </div>
          )}
          <button className="btn btn--primary" type="submit" disabled={create.isPending}>
            <Icon name="check" size="sm" />
            <span>{t("حفظ", "Save")}</span>
          </button>
        </form>
      </div>
    </>
  );
}
