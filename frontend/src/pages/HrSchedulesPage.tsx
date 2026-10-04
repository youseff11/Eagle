import { useState, type FormEvent } from "react";
import { Navigate, useSearchParams } from "react-router";
import { formErrors } from "../api/adminActions";
import { useAddOverride, useAddRosterDay, useAddTemplate, useDeleteOverride, useDeleteRosterDay } from "../api/hrActions";
import { useHrSchedules } from "../api/queries";
import type { FormErrors, Labelled } from "../api/types";
import { Waiting, refusal } from "../components/accounts/shared";
import { DjangoForm, useFormEdits } from "../components/admin/DjangoForm";
import { useHrAllowed, useStamp } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";
import { minutesHm } from "../lib/payroll";

/**
 * A person's standing roster, the one-off days that override it, and what the rules say for the next fortnight once both are
 * applied. A day with no row is a day off. Three small forms live here: a day for the roster (switched on when it is added),
 * a one-off day, and a company shift of four boxes. Each is the classic form: it decides what is valid.
 */
export function HrSchedulesPage() {
  const { t, lang } = usePreferences();
  const stamp = useStamp();
  const { push } = useToasts();
  const { me, allowed } = useHrAllowed();
  const [params, setParams] = useSearchParams();
  const user = params.get("user") ?? "";
  const query = useHrSchedules(user, allowed);
  const data = query.data;
  const addDay = useAddRosterDay();
  const addOverride = useAddOverride();
  const addTemplate = useAddTemplate();
  const removeDay = useDeleteRosterDay();
  const removeOverride = useDeleteOverride();
  const dayEdits = useFormEdits(data?.shift_form);
  const overrideEdits = useFormEdits(data?.override_form);
  const templateEdits = useFormEdits(data?.template_form);
  const [dayErrors, setDayErrors] = useState<FormErrors>({});
  const [overrideErrors, setOverrideErrors] = useState<FormErrors>({});
  const [templateErrors, setTemplateErrors] = useState<FormErrors>({});
  const [failed, setFailed] = useState("");

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!data) return <Waiting failed={query.isError} />;
  const person = data.person;
  const words = (value: Labelled | { ar: string; en: string }) => (lang === "ar" ? value.ar : value.en);
  const hours = (start: Parameters<typeof stamp>[0], end: Parameters<typeof stamp>[0]) => `${stamp(start)} – ${stamp(end)}`;
  const problem = t("حصلت مشكلة، ماتسجلش.", "Something went wrong, nothing was recorded.");

  const send = (
    run: (options: { onSuccess: () => void; onError: (error: unknown) => void }) => void,
    setErrors: (errors: FormErrors) => void,
    reset: () => void,
  ) => {
    setErrors({});
    setFailed("");
    run({
      onSuccess: () => {
        reset();
        push({ level: "success", title: t("اتسجل", "Recorded") });
      },
      onError: (error) => {
        const found = formErrors(error);
        if (found) setErrors(found);
        else setFailed(refusal(error, problem));
      },
    });
  };
  const submitDay = (event: FormEvent) => {
    event.preventDefault();
    if (!person) return;
    send((options) => addDay.mutate({ user: person.id, values: dayEdits.edited }, options), setDayErrors, dayEdits.reset);
  };
  const submitOverride = (event: FormEvent) => {
    event.preventDefault();
    if (!person) return;
    send((options) => addOverride.mutate({ user: person.id, values: overrideEdits.edited }, options), setOverrideErrors, overrideEdits.reset);
  };
  const submitTemplate = (event: FormEvent) => {
    event.preventDefault();
    send((options) => addTemplate.mutate(templateEdits.edited, options), setTemplateErrors, templateEdits.reset);
  };
  const drop = (run: (options: { onError: (error: unknown) => void }) => void) =>
    run({ onError: (error) => push({ level: "danger", title: refusal(error, t("حصلت مشكلة.", "Something went wrong.")) }) });

  return (
    <>
      <div className="page-head">
        <h1>{t("جداول العمل", "Work schedules")}</h1>
        <div className="grow" />
        <select
          className="input"
          aria-label={t("الموظف", "Employee")}
          value={person?.id ?? ""}
          onChange={(event) => setParams(event.target.value ? { user: event.target.value } : {})}
        >
          {data.people.map((one) => (
            <option key={one.id} value={one.id}>
              {one.name}
            </option>
          ))}
        </select>
      </div>

      {person && (
        <div className="card card--flat" data-card="person">
          <div className="row row--tight">
            <span className="chip">{words(person.employment)}</span>
            {person.work_mode && <span className="chip">{words(person.work_mode)}</span>}
            <span className="chip mono">{person.schedule_kind}</span>
          </div>
        </div>
      )}

      <div className="grid grid--main">
        <div className="stack">
          <div className="card">
            <div className="card__head">
              <Icon name="calendar" />
              <h3>{t("الجدول الأسبوعي", "Weekly roster")}</h3>
              <div className="grow" />
              <span className="muted">{t("اليوم اللي مالوش سطر = أجازة", "A day with no row is a day off")}</span>
            </div>
            <div className="table-wrap">
              <table className="table" data-table="roster">
                <thead>
                  <tr>
                    <th>{t("اليوم", "Day")}</th>
                    <th>{t("الشيفت", "Shift")}</th>
                    <th>{t("الوقت", "Hours")}</th>
                    <th>{t("المطلوب", "Required")}</th>
                    <th>{t("النظام", "Mode")}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.shifts.map((row) => (
                    <tr key={row.id} data-roster={row.id}>
                      <td>
                        {words(row.weekday)}
                        {!row.is_active && <span className="badge badge--dead">{t("موقوف - مش بيتحسب", "Off - does not count")}</span>}
                      </td>
                      <td>{row.template ?? "—"}</td>
                      <td className="mono">
                        {hours(row.start, row.end)}
                        {row.crosses_midnight && <span className="badge badge--info">{t("لليوم التالي", "Overnight")}</span>}
                      </td>
                      <td className="mono">{minutesHm(row.minutes)}</td>
                      <td>{row.work_mode ? <span className="chip">{words(row.work_mode)}</span> : "—"}</td>
                      <td>
                        <button
                          className="btn btn--sm btn--ghost"
                          type="button"
                          aria-label={t("احذف", "Delete")}
                          disabled={removeDay.isPending}
                          onClick={() => drop((options) => removeDay.mutate(row.id, options))}
                        >
                          <Icon name="trash" size="sm" />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {data.shifts.length === 0 && (
                    <tr>
                      <td colSpan={6} className="empty">
                        {t("مفيش جدول للموظف ده لسه.", "No roster for this person yet.")}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card">
            <div className="card__head">
              <Icon name="pin" />
              <h3>{t("تعديلات يوم واحد", "One-off days")}</h3>
            </div>
            <div className="table-wrap">
              <table className="table" data-table="overrides">
                <thead>
                  <tr>
                    <th>{t("اليوم", "Date")}</th>
                    <th>{t("التعديل", "Change")}</th>
                    <th>{t("النظام", "Mode")}</th>
                    <th>{t("السبب", "Reason")}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.overrides.map((row) => (
                    <tr key={row.id} data-override={row.id}>
                      <td className="mono">{row.date}</td>
                      <td>{row.is_day_off ? <span className="badge badge--info">{t("أجازة", "Day off")}</span> : <span className="mono">{row.label}</span>}</td>
                      <td>{row.work_mode ? <span className="chip">{words(row.work_mode)}</span> : "—"}</td>
                      <td className="muted">{row.reason || "—"}</td>
                      <td>
                        <button
                          className="btn btn--sm btn--ghost"
                          type="button"
                          aria-label={t("احذف", "Delete")}
                          disabled={removeOverride.isPending}
                          onClick={() => drop((options) => removeOverride.mutate(row.id, options))}
                        >
                          <Icon name="trash" size="sm" />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {data.overrides.length === 0 && (
                    <tr>
                      <td colSpan={5} className="empty">
                        {t("مفيش تعديلات.", "Nothing overridden.")}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card">
            <div className="card__head">
              <Icon name="eye" />
              <h3>{t("الأسبوعين الجايين", "The next fortnight")}</h3>
              <div className="grow" />
              <span className="muted">{t("بعد تطبيق التعديلات", "After the overrides are applied")}</span>
            </div>
            <div className="table-wrap">
              <table className="table" data-table="preview">
                <thead>
                  <tr>
                    <th>{t("اليوم", "Date")}</th>
                    <th>{t("الشيفت", "Shift")}</th>
                    <th>{t("الوقت", "Hours")}</th>
                    <th>{t("النظام", "Mode")}</th>
                    <th>{t("المصدر", "From")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.preview.map((plan) => (
                    <tr key={plan.date} data-plan={plan.date}>
                      <td className="mono">{plan.date}</td>
                      <td>{plan.working ? plan.label : <span className="muted">{t("أجازة", "Off")}</span>}</td>
                      <td className="mono">{plan.working ? hours(plan.start, plan.end) : "—"}</td>
                      <td>{plan.mode ? <span className="chip">{words(plan.mode)}</span> : "—"}</td>
                      <td className="muted mono">{plan.source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="sticky-side">
          <div className="card">
            <div className="card__head">
              <Icon name="plus" />
              <h3>{t("ضيف يوم للجدول", "Add a roster day")}</h3>
            </div>
            <form onSubmit={submitDay}>
              <DjangoForm fields={data.shift_form} edits={dayEdits} errors={dayErrors} prefix="shift" />
              <button className="btn btn--primary btn--block" type="submit" disabled={!person || addDay.isPending || !dayEdits.dirty}>
                <Icon name="check" size="sm" />
                <span>{t("احفظ", "Save")}</span>
              </button>
            </form>
          </div>

          <div className="card">
            <div className="card__head">
              <Icon name="pin" />
              <h3>{t("عدّل يوم واحد", "Override one day")}</h3>
            </div>
            <form onSubmit={submitOverride}>
              <DjangoForm fields={data.override_form} edits={overrideEdits} errors={overrideErrors} prefix="override" />
              <button className="btn btn--block" type="submit" disabled={!person || addOverride.isPending || !overrideEdits.dirty}>
                <Icon name="check" size="sm" />
                <span>{t("احفظ", "Save")}</span>
              </button>
            </form>
          </div>

          <div className="card card--flat">
            <div className="card__head">
              <Icon name="layers" />
              <h3>{t("شيفتات الشركة", "Company shifts")}</h3>
            </div>
            {data.templates.map((one) => (
              <div className="kv" key={one.id} data-template={one.id}>
                <span>
                  {one.label} {!one.is_active && <span className="badge">{t("مقفول", "Closed")}</span>}
                </span>
                <b className="mono">
                  {stamp(one.start)}–{stamp(one.end)}
                </b>
              </div>
            ))}
            <form className="mt" onSubmit={submitTemplate}>
              <DjangoForm fields={data.template_form} edits={templateEdits} errors={templateErrors} prefix="template" />
              <button className="btn btn--sm btn--block" type="submit" disabled={addTemplate.isPending || !templateEdits.dirty}>
                <Icon name="plus" size="sm" />
                <span>{t("ضيف شيفت", "Add shift")}</span>
              </button>
            </form>
          </div>

          {failed && (
            <div className="note note--high" role="alert">
              <Icon name="alert" />
              <div>{failed}</div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
