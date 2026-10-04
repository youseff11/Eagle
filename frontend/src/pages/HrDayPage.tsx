import { useState, type FormEvent } from "react";
import { Link, Navigate, useParams } from "react-router";
import { formErrors } from "../api/adminActions";
import { ApiError } from "../api/client";
import { useClearHrDay, useSaveHrDay } from "../api/hrActions";
import { useHrDay } from "../api/queries";
import type { FormErrors } from "../api/types";
import { Waiting, refusal } from "../components/accounts/shared";
import { DjangoForm, useFormEdits } from "../components/admin/DjangoForm";
import { StatusBadge, useHrAllowed, useStamp } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";
import { minutesHm } from "../lib/payroll";

/**
 * One day of one person: the punches exactly as they arrived (never edited), the trail of every correction, the schedule as it
 * stood when the day happened, and the form that corrects the day. A correction without a reason is not saved - the reason is
 * what makes the figure evidence - and only the boxes that were changed are sent.
 */
export function HrDayPage() {
  const { t } = usePreferences();
  const stamp = useStamp();
  const { push } = useToasts();
  const { me, allowed } = useHrAllowed();
  const params = useParams();
  const id = Number(params.id);
  const query = useHrDay(id, allowed);
  const save = useSaveHrDay(id);
  const clear = useClearHrDay(id);
  const data = query.data;
  const edits = useFormEdits(data?.form);
  const [errors, setErrors] = useState<FormErrors>({});
  const [problem, setProblem] = useState("");
  const [review, setReview] = useState("");

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!Number.isInteger(id) || id <= 0 || (query.error instanceof ApiError && query.error.status === 404)) {
    return (
      <div className="card empty" role="alert">
        <span>{t("الصفحة دي مش موجودة.", "That page does not exist.")}</span>
      </div>
    );
  }
  if (!data) return <Waiting failed={query.isError} />;
  const { day } = data;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    setProblem("");
    save.mutate(edits.edited, {
      onSuccess: (answer) => {
        edits.reset();
        push({
          level: "success",
          title: answer.written.length ? t(`${answer.written.length} تعديل`, `${answer.written.length} changed`) : t("مفيش حاجة اتغيرت", "Nothing changed"),
        });
      },
      onError: (error) => {
        const found = formErrors(error);
        if (found) setErrors(found);
        else setProblem(refusal(error, t("حصلت مشكلة، التعديل ماتسجلش.", "Something went wrong, the correction was not recorded.")));
      },
    });
  };
  const markReviewed = (event: FormEvent) => {
    event.preventDefault();
    clear.mutate(review, {
      onSuccess: () => {
        setReview("");
        push({ level: "success", title: t("اتراجع", "Reviewed") });
      },
      onError: (error) => push({ level: "danger", title: refusal(error, t("حصلت مشكلة.", "Something went wrong.")) }),
    });
  };
  const eventWords = (kind: { ar: string; en: string }) => t(kind.ar, kind.en);

  return (
    <>
      <div className="page-head">
        <h1>
          {day.user.name} <span className="mono muted">{day.date}</span>
        </h1>
        <StatusBadge status={day.status} />
        <div className="grow" />
        <Link className="btn btn--sm btn--ghost" to={`/hr/attendance?date=${day.date}`}>
          <Icon name="arrow-right" size="sm" />
          <span>{t("لوحة الحضور", "Attendance board")}</span>
        </Link>
        {day.needs_review && (
          <form className="row row--tight" onSubmit={markReviewed}>
            <input
              className="input"
              type="text"
              aria-label={t("ملاحظة المراجعة", "Review note")}
              placeholder={t("ملاحظة المراجعة", "Review note")}
              maxLength={250}
              value={review}
              onChange={(event) => setReview(event.target.value)}
            />
            <button className="btn btn--ok btn--sm" type="submit" disabled={clear.isPending}>
              <Icon name="check" size="sm" />
              <span>{t("راجعته", "Reviewed")}</span>
            </button>
          </form>
        )}
      </div>

      {day.needs_review && (
        <div className="note note--warn" data-note="flagged">
          <Icon name="alert" />
          <div>
            <strong>{t("متعلّم للمراجعة", "Flagged for review")}</strong> <span className="mono">{day.review_reason}</span>
          </div>
        </div>
      )}

      <div className="grid grid--main">
        <div className="stack">
          <div className="card">
            <div className="card__head">
              <Icon name="history" />
              <h3>{t("التسجيلات", "The punches")}</h3>
              <div className="grow" />
              <span className="muted">{t("مبتتعدلش — بتتكتب وخلاص", "Append-only: never edited")}</span>
            </div>
            <div className="table-wrap">
              <table className="table" data-table="events">
                <thead>
                  <tr>
                    <th>{t("الحدث", "Event")}</th>
                    <th>{t("الوقت", "Time")}</th>
                    <th>{t("الموقع", "Location")}</th>
                    <th>{t("الجهاز", "Device")}</th>
                    <th>IP</th>
                  </tr>
                </thead>
                <tbody>
                  {data.events.map((event, index) => (
                    <tr key={index}>
                      <td>
                        <span className="badge">{eventWords(event.kind)}</span>
                      </td>
                      <td className="mono">{stamp(event.at)}</td>
                      <td className="mono">
                        {event.within_geofence === null ? (
                          <span className="muted">{t("مااتفحصش", "Not checked")}</span>
                        ) : event.within_geofence ? (
                          <span className="badge badge--ok">
                            {event.distance_m}
                            {t("م", "m")} · {event.office}
                          </span>
                        ) : (
                          <span className="badge badge--dead">
                            {event.distance_m}
                            {t("م", "m")} · {t("بره النطاق", "Off site")}
                          </span>
                        )}
                        {event.accuracy_m ? (
                          <span className="muted">
                            {" "}
                            ±{event.accuracy_m}
                            {t("م", "m")}
                          </span>
                        ) : null}
                      </td>
                      <td className="mono muted">{event.device || "—"}</td>
                      <td className="mono muted">{event.ip || "—"}</td>
                    </tr>
                  ))}
                  {data.events.length === 0 && (
                    <tr>
                      <td colSpan={5} className="empty">
                        {t("اليوم ده متكتب بالإيد — مفيش تسجيلات.", "This day was entered by hand - there are no punches.")}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card">
            <div className="card__head">
              <Icon name="shield" />
              <h3>{t("سجل التعديلات", "Audit trail")}</h3>
            </div>
            <div className="table-wrap">
              <table className="table" data-table="edits">
                <thead>
                  <tr>
                    <th>{t("مين", "Who")}</th>
                    <th>{t("الحقل", "Field")}</th>
                    <th>{t("قبل", "Before")}</th>
                    <th>{t("بعد", "After")}</th>
                    <th>{t("السبب", "Reason")}</th>
                    <th>{t("الوقت", "When")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.edits.map((edit, index) => (
                    <tr key={index}>
                      <td>{edit.actor ?? "—"}</td>
                      <td className="mono">{edit.field}</td>
                      <td className="mono muted">{edit.old || "—"}</td>
                      <td className="mono">{edit.new || "—"}</td>
                      <td>{edit.reason}</td>
                      <td className="mono muted">{stamp(edit.at)}</td>
                    </tr>
                  ))}
                  {data.edits.length === 0 && (
                    <tr>
                      <td colSpan={6} className="empty">
                        {t("اليوم ده مااتعدلش.", "This day has never been changed.")}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="sticky-side">
          <div className="card">
            <div className="card__head">
              <Icon name="pen" />
              <h3>{t("عدّل اليوم", "Correct the day")}</h3>
            </div>
            <form onSubmit={submit}>
              <DjangoForm fields={data.form} edits={edits} errors={errors} prefix="day" />
              {problem && (
                <div className="note note--high" role="alert">
                  <Icon name="alert" />
                  <div>{problem}</div>
                </div>
              )}
              <button className="btn btn--primary btn--block" type="submit" disabled={save.isPending || !edits.dirty}>
                <Icon name="check" size="sm" />
                <span>{t("احفظ", "Save")}</span>
              </button>
            </form>
          </div>

          <div className="card card--flat">
            <div className="card__head">
              <Icon name="clock" />
              <h3>{t("الجدول المجمّد", "The frozen schedule")}</h3>
            </div>
            <div className="kv">
              <span>{t("الشيفت", "Shift")}</span>
              <b className="mono">{day.schedule || "—"}</b>
            </div>
            <div className="kv">
              <span>{t("من", "From")}</span>
              <b className="mono">{stamp(day.scheduled_start)}</b>
            </div>
            <div className="kv">
              <span>{t("إلى", "To")}</span>
              <b className="mono">{stamp(day.scheduled_end)}</b>
            </div>
            <div className="kv">
              <span>{t("المطلوب", "Required")}</span>
              <b className="mono">{minutesHm(day.scheduled_minutes)}</b>
            </div>
            <div className="kv">
              <span>{t("فترة السماح", "Grace")}</span>
              <b className="mono">
                {day.grace_minutes}
                {t("د", "m")}
              </b>
            </div>
            <div className="kv">
              <span>{t("اتحسب", "Worked")}</span>
              <b className="mono">{minutesHm(day.work_minutes)}</b>
            </div>
            <div className="kv">
              <span>{t("اكسترا تايم من", "Extra time from")}</span>
              <b className="mono">{stamp(day.extra_started_at)}</b>
            </div>
            <div className="kv">
              <span>{t("أوفرتايم", "Overtime")}</span>
              <b className="mono">{minutesHm(day.overtime_minutes)}</b>
            </div>
            {day.checkout_missed && (
              <div className="note note--warn mt" data-note="missed">
                <Icon name="alert" />
                <div>
                  {t(
                    "اليوم ده اتلغى لأن الانصراف متسجلش في الميعاد. لو فيه عذر، رجّع الحالة «حاضر» واكتب ميعاد الانصراف والسبب.",
                    "This day was voided: no check-out in time. If there is a reason, set it back to Present with the check-out time and a reason.",
                  )}
                </div>
              </div>
            )}
            <small className="muted">
              {t(
                "دي نسخة الجدول وقت ما اليوم حصل. تغيير الجدول دلوقتي مش بيلمسها.",
                "This is the schedule as it stood when the day happened. Changing the roster now does not touch it.",
              )}
            </small>
          </div>
        </div>
      </div>
    </>
  );
}
