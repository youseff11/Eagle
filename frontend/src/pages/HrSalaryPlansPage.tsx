import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useSearchParams } from "react-router";
import { formErrors } from "../api/adminActions";
import { useSavePlan } from "../api/hrActions";
import { useHrSalaryPlans, useMe } from "../api/queries";
import type { FormErrors } from "../api/types";
import { Waiting, refusal } from "../components/accounts/shared";
import { DjangoForm, useFormEdits } from "../components/admin/DjangoForm";
import { Icon } from "../components/Icon";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

/**
 * The pay plans: one person's rules where they differ from the company's. Every number is optional, and a blank one falls back
 * to the company's, so somebody on no plan is priced exactly as before. They move money, so they are the owner's alone.
 */
export function HrSalaryPlansPage() {
  const { t } = usePreferences();
  const { push } = useToasts();
  const me = useMe();
  const allowed = me.data?.user.is_admin === true;
  const [params, setParams] = useSearchParams();
  const edit = params.get("edit") ?? "";
  const query = useHrSalaryPlans(edit, allowed);
  const save = useSavePlan();
  const data = query.data;
  const edits = useFormEdits(data?.form);
  const [errors, setErrors] = useState<FormErrors>({});
  const [problem, setProblem] = useState("");
  const editing = data?.editing ?? null;
  const { reset } = edits;
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
          push({ level: "success", title: t("اتحفظت", "Saved") });
          if (editing !== null) setParams({});
        },
        onError: (error) => {
          const found = formErrors(error);
          if (found) setErrors(found);
          else setProblem(refusal(error, t("حصلت مشكلة، ماتحفظتش.", "Something went wrong, nothing was saved.")));
        },
      },
    );
  };

  return (
    <>
      <div className="page-head">
        <h1>{t("خطط الرواتب", "Salary plans")}</h1>
      </div>

      <div className="note note--info">
        <Icon name="info" />
        <div>
          {t("كل رقم في الخطة اختياري — اللي تسيبه فاضي بيرجع لقاعدة الشركة.", "Every number on a plan is optional. A blank one falls back to the company rule, and somebody with no plan is priced exactly as before.")}{" "}
          <span data-unassigned>
            {t(`و${data.unassigned} مترجم دلوقتي على قواعد الشركة.`, `${data.unassigned} translators are on the company rules right now.`)}
          </span>
        </div>
      </div>

      <div className="grid grid--main">
        <div className="card">
          <div className="card__head">
            <Icon name="sliders" />
            <h3>{t("الخطط", "Plans")}</h3>
          </div>
          <div className="table-wrap">
            <table className="table" data-table="plans">
              <thead>
                <tr>
                  <th>{t("الخطة", "Plan")}</th>
                  <th>{t("بتغيّر إيه", "Overrides")}</th>
                  <th>{t("بونص الكلمات", "Extra words")}</th>
                  <th>{t("بدل ثابت", "Allowance")}</th>
                  <th>{t("عليها", "Members")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.id} data-plan={row.id}>
                    <td>
                      {row.name} {!row.is_active && <span className="badge">{t("مقفولة", "Closed")}</span>}
                      {row.note && <div className="muted">{row.note}</div>}
                    </td>
                    <td className="muted mono">{row.overrides.length ? row.overrides.join(" · ") : "—"}</td>
                    <td className="mono">
                      {row.extra_word_rate !== null ? (
                        <>
                          {row.extra_word_rate} <span className="muted">/ {t("كلمة", "word")}</span>
                        </>
                      ) : (
                        <span className="muted">{t("شرائح الشركة", "company bands")}</span>
                      )}
                    </td>
                    <td className="mono">{row.fixed_allowance}</td>
                    <td className="mono">{row.members}</td>
                    <td>
                      <Link className="btn btn--sm btn--ghost" to={`/hr/salary-plans?edit=${row.id}`}>
                        <Icon name="pen" size="sm" />
                        <span>{t("عدّل", "Edit")}</span>
                      </Link>
                    </td>
                  </tr>
                ))}
                {data.rows.length === 0 && (
                  <tr>
                    <td colSpan={6} className="empty">
                      {t("مفيش خطط — الكل على قواعد الشركة.", "No plans: everybody is on the company rules.")}
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
              <h3>{editing !== null ? t("تعديل خطة", "Edit plan") : t("خطة جديدة", "New plan")}</h3>
              {editing !== null && (
                <>
                  <div className="grow" />
                  <Link className="btn btn--sm btn--ghost" to="/hr/salary-plans">
                    <Icon name="plus" size="sm" />
                    <span>{t("خطة جديدة", "New plan")}</span>
                  </Link>
                </>
              )}
            </div>
            <form onSubmit={submit}>
              <DjangoForm fields={data.form} edits={edits} errors={errors} prefix="plan" />
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
