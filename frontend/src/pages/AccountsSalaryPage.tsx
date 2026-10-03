import { useState, type FormEvent } from "react";
import { Link, Navigate, useParams } from "react-router";
import { useSaveSalary } from "../api/accountsActions";
import { formErrors } from "../api/adminActions";
import { ApiError } from "../api/client";
import { useAccountsSalary } from "../api/queries";
import type { FormErrors } from "../api/types";
import { Waiting, useMayRunTheMonth } from "../components/accounts/shared";
import { DjangoForm, useFormEdits } from "../components/admin/DjangoForm";
import { Icon } from "../components/Icon";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

/**
 * A person's salary history. It is append-only: a new salary is a new row, and a month already run keeps the salary it was
 * computed on. A person with no salary on record computes to zero.
 */
export function AccountsSalaryPage() {
  const { t } = usePreferences();
  const { push } = useToasts();
  const params = useParams();
  const id = Number(params.id);
  const { me, allowed } = useMayRunTheMonth();
  const query = useAccountsSalary(id, allowed);
  const save = useSaveSalary(id);
  const edits = useFormEdits(query.data?.form);
  const [errors, setErrors] = useState<FormErrors>({});
  const [failed, setFailed] = useState(false);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!Number.isInteger(id) || id <= 0 || (query.error instanceof ApiError && query.error.status === 404)) {
    return (
      <div className="card empty" role="alert">
        <span>{t("الصفحة دي مش موجودة.", "That page does not exist.")}</span>
      </div>
    );
  }
  const data = query.data;
  if (!data) return <Waiting failed={query.isError} />;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    setFailed(false);
    save.mutate(edits.edited, {
      onSuccess: () => {
        edits.reset();
        push({ level: "success", title: t("اتسجل", "Recorded") });
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
        <h1>{data.person.name}</h1>
        <div className="page-head__sub mono">{data.person.username}</div>
      </div>

      <div className="grid grid--main">
        <div>
          <div className="card">
            <div className="card__head">
              <Icon name="history" />
              <h3>{t("الرواتب", "Salaries")}</h3>
            </div>
            <div className="table-wrap">
              <table className="table" data-table="salaries">
                <thead>
                  <tr>
                    <th>{t("ساري من", "Effective from")}</th>
                    <th>{t("الراتب", "Salary")}</th>
                    <th>{t("ملاحظة", "Note")}</th>
                    <th>{t("سجّله", "Recorded by")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.records.map((row) => (
                    <tr key={row.id}>
                      <td className="mono">{row.effective_from}</td>
                      <td className="mono">{row.amount}</td>
                      <td className="muted">{row.note}</td>
                      <td className="muted">{row.by ?? "—"}</td>
                    </tr>
                  ))}
                  {data.records.length === 0 && (
                    <tr>
                      <td colSpan={4} className="empty">
                        {t("مفيش راتب مسجل — السطر هيطلع بصفر.", "No salary on record - the payroll line computes to zero.")}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card">
            <div className="card__head">
              <Icon name="calendar" />
              <h3>{t("الشهور المحسوبة", "Computed months")}</h3>
            </div>
            <div className="table-wrap">
              <table className="table" data-table="months">
                <thead>
                  <tr>
                    <th>{t("الشهر", "Month")}</th>
                    <th>{t("الأساسي", "Base")}</th>
                    <th>{t("كلمات", "Words")}</th>
                    <th>{t("الصافي", "Net")}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.lines.map((line) => (
                    <tr key={line.id}>
                      <td className="mono">{line.label}</td>
                      <td className="mono">{line.base_salary}</td>
                      <td className="mono">{line.words}</td>
                      <td className="mono">
                        <strong>{line.net}</strong>
                      </td>
                      <td>
                        {data.can.line && (
                          <Link className="btn btn--sm" to={`/accounts/lines/${line.id}`}>
                            {t("التفاصيل", "Detail")}
                          </Link>
                        )}
                      </td>
                    </tr>
                  ))}
                  {data.lines.length === 0 && (
                    <tr>
                      <td colSpan={5} className="empty">
                        {t("لسه مفيش شهور محسوبة.", "No months computed yet.")}
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
              <Icon name="plus" />
              <h3>{t("راتب جديد", "New salary")}</h3>
            </div>
            <form onSubmit={submit}>
              <DjangoForm fields={data.form} edits={edits} errors={errors} prefix="salary" />
              {failed && (
                <div className="note note--high" role="alert">
                  <Icon name="alert" />
                  <div>{t("حصلت مشكلة، ماتسجلش.", "Something went wrong, nothing was recorded.")}</div>
                </div>
              )}
              <button className="btn btn--primary btn--block" type="submit" disabled={save.isPending || !edits.dirty}>
                <Icon name="check" size="sm" />
                <span>{t("سجل", "Record")}</span>
              </button>
            </form>
          </div>
          <div className="note note--info">
            <Icon name="shield" />
            <div>{t("الراتب القديم مابيتمسحش. أي شهر بيتحسب بالراتب اللي كان ساري فيه.", "An old salary is never overwritten. Each month is computed on the salary that was in force then.")}</div>
          </div>
        </div>
      </div>
    </>
  );
}
