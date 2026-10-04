import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useSearchParams } from "react-router";
import { formErrors } from "../api/adminActions";
import { useDeleteShift, useSaveShift } from "../api/hrActions";
import { useHrShifts } from "../api/queries";
import type { FormErrors } from "../api/types";
import { Waiting, refusal } from "../components/accounts/shared";
import { DjangoForm, useFormEdits } from "../components/admin/DjangoForm";
import { useHrAllowed, useStamp } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

/**
 * The company's shifts: add one, change its hours, close it, delete it. Changing a shift's hours moves everybody on it from
 * today; days already recorded keep the hours they were worked under. A shift people are on is closed, never deleted.
 */
export function HrShiftsPage() {
  const { t } = usePreferences();
  const stamp = useStamp();
  const { push } = useToasts();
  const { me, allowed } = useHrAllowed();
  const [params, setParams] = useSearchParams();
  const edit = params.get("edit") ?? "";
  const query = useHrShifts(edit, allowed);
  const save = useSaveShift();
  const remove = useDeleteShift();
  const data = query.data;
  const edits = useFormEdits(data?.form);
  const [errors, setErrors] = useState<FormErrors>({});
  const [problem, setProblem] = useState("");
  const editing = data?.editing ?? null;
  const { reset } = edits;
  // Another shift in the form is another form: what was typed for the last one is not carried over.
  useEffect(() => {
    reset();
    setErrors({});
    setProblem("");
  }, [editing, reset]);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!data) return <Waiting failed={query.isError} />;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    setProblem("");
    save.mutate(
      { id: editing, values: edits.edited },
      {
        onSuccess: () => {
          edits.reset();
          push({ level: "success", title: t("اتحفظ", "Saved") });
          if (editing !== null) setParams({});
        },
        onError: (error) => {
          const found = formErrors(error);
          if (found) setErrors(found);
          else setProblem(refusal(error, t("حصلت مشكلة، ماتحفظش.", "Something went wrong, nothing was saved.")));
        },
      },
    );
  };
  const drop = (id: number) =>
    remove.mutate(id, {
      onSuccess: () => push({ level: "success", title: t("اتمسح", "Deleted") }),
      onError: (error) => push({ level: "danger", title: refusal(error, t("حصلت مشكلة.", "Something went wrong.")) }),
    });

  return (
    <>
      <div className="page-head">
        <h1>{t("الشيفتات", "Shifts")}</h1>
      </div>

      <div className="note note--info">
        <Icon name="info" />
        <div>
          {t(
            "تعديل مواعيد شيفت بيتحرك معاه كل اللي عليه من النهارده. الأيام اللي اتسجلت قبل كده بتفضل على المواعيد اللي اشتغلوا بيها. الشيفت اللي عليه موظفين بيتقفل مش بيتمسح.",
            "Changing a shift's hours moves everybody on it from today. Days already recorded keep the hours they were worked under. A shift people are on is closed, not deleted.",
          )}
        </div>
      </div>

      <div className="grid grid--main">
        <div className="card">
          <div className="card__head">
            <Icon name="clock" />
            <h3>{t("شيفتات الشركة", "Company shifts")}</h3>
          </div>
          <div className="table-wrap">
            <table className="table" data-table="shifts">
              <thead>
                <tr>
                  <th>{t("الشيفت", "Shift")}</th>
                  <th>{t("المواعيد", "Hours")}</th>
                  <th>{t("المدة", "Length")}</th>
                  <th>{t("عليه", "On it")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.id} data-shift={row.id}>
                    <td>
                      <b>{row.label}</b>
                      {!row.is_active && <span className="badge">{t("مقفول", "Closed")}</span>}
                    </td>
                    <td className="mono">
                      {stamp(row.start)} – {stamp(row.end)}
                      {row.crosses_midnight && <span className="badge badge--info">{t("بيعدّي نص الليل", "Crosses midnight")}</span>}
                    </td>
                    <td className="mono">
                      {row.hours} <span className="muted">{t("ساعة", "h")}</span>
                    </td>
                    <td className="mono">
                      {row.people} <span className="muted">{t("موظف", "staff")}</span>
                      {row.overrides > 0 && (
                        <div className="muted">
                          {row.overrides} {t("تعديل يوم", "one-off days")}
                        </div>
                      )}
                      {row.vacancies > 0 && (
                        <div className="muted">
                          {row.vacancies} {t("وظيفة", "vacancies")}
                        </div>
                      )}
                    </td>
                    <td>
                      <div className="row row--tight">
                        <Link className="btn btn--sm btn--ghost" to={`/hr/shifts?edit=${row.id}`}>
                          <Icon name="pen" size="sm" />
                          <span>{t("عدّل", "Edit")}</span>
                        </Link>
                        {!row.in_use && (
                          <button className="btn btn--sm btn--ghost" type="button" aria-label={t("احذف", "Delete")} disabled={remove.isPending} onClick={() => drop(row.id)}>
                            <Icon name="trash" size="sm" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {data.rows.length === 0 && (
                  <tr>
                    <td colSpan={5} className="empty">
                      {t("مفيش شيفتات — ضيف أول شيفت من الجنب.", "No shifts yet - add the first one from the side.")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="sticky-side">
          <div className="card">
            <div className="card__head">
              <Icon name="pen" />
              <h3>{editing !== null ? t("تعديل شيفت", "Edit shift") : t("شيفت جديد", "New shift")}</h3>
              {editing !== null && (
                <>
                  <div className="grow" />
                  <Link className="btn btn--sm btn--ghost" to="/hr/shifts">
                    <Icon name="plus" size="sm" />
                    <span>{t("شيفت جديد", "New shift")}</span>
                  </Link>
                </>
              )}
            </div>
            <form onSubmit={submit}>
              <DjangoForm fields={data.form} edits={edits} errors={errors} prefix="shift" />
              <small className="muted">
                {t(
                  "لو النهاية قبل البداية (5 م لـ 1 ص) الشيفت بيعدّي نص الليل وبيتحسب على يوم بدايته.",
                  "If the end is before the start (5 PM to 1 AM) the shift crosses midnight and counts on the day it started.",
                )}
              </small>
              {problem && (
                <div className="note note--high" role="alert">
                  <Icon name="alert" />
                  <div>{problem}</div>
                </div>
              )}
              <button className="btn btn--primary btn--block mt" type="submit" disabled={save.isPending || !edits.dirty}>
                <Icon name="check" size="sm" />
                <span>{t("احفظ", "Save")}</span>
              </button>
            </form>
          </div>
        </div>
      </div>
    </>
  );
}
