import { useState, type FormEvent, type ReactNode } from "react";
import { Navigate } from "react-router";
import { useDecideViolation, useProposeViolation } from "../api/accountsActions";
import { formErrors } from "../api/adminActions";
import { useAccountsViolations } from "../api/queries";
import type { AccountsViolation, FormErrors } from "../api/types";
import { Penalty, Waiting, refusal, useMayRunTheMonth } from "../components/accounts/shared";
import { DjangoForm, useFormEdits } from "../components/admin/DjangoForm";
import { Icon } from "../components/Icon";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

function Row({ row, children }: { row: AccountsViolation; children?: ReactNode }) {
  const { t, lang } = usePreferences();
  return (
    <tr data-violation={row.id}>
      <td>{row.user}</td>
      <td className="mono">{row.date}</td>
      <td>
        {lang === "ar" ? row.kind.ar : row.kind.en}
        {row.escalated && <span className="badge badge--dead">{t("تصعيد للمدير", "Escalated")}</span>}
      </td>
      {children}
    </tr>
  );
}

/**
 * Violations and deductions: what waits for a decision, what was decided, and the box that proposes one. A deduction is worth
 * nothing until a person approves it, and one that has been decided is not decided again from here.
 */
export function AccountsViolationsPage() {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const { me, allowed } = useMayRunTheMonth();
  const query = useAccountsViolations(allowed);
  const decide = useDecideViolation();
  const propose = useProposeViolation();
  const data = query.data;
  const edits = useFormEdits(data?.form);
  const [errors, setErrors] = useState<FormErrors>({});
  const [failed, setFailed] = useState(false);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!data) return <Waiting failed={query.isError} />;

  const act = (id: number, action: "approve" | "reject") =>
    decide.mutate({ id, action }, { onError: (error) => push({ level: "danger", title: refusal(error, t("حصلت مشكلة.", "Something went wrong.")) }) });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    setFailed(false);
    propose.mutate(edits.edited, {
      onSuccess: () => {
        edits.reset();
        push({ level: "success", title: t("اتسجلت - مستنية الاعتماد", "Recorded - waiting for approval") });
      },
      onError: (error) => {
        const found = formErrors(error);
        if (found) setErrors(found);
        else setFailed(true);
      },
    });
  };
  const defaults: [string, string, string, string][] = [
    ["quality_penalty_days", "خطأ ترجمة", "Translation error", "days"],
    ["unexcused_penalty_days", "غياب بدون إذن", "Unexcused absence", "days"],
    ["low_output_penalty_days", "انخفاض إنتاجية", "Low productivity", "days"],
    ["extra_leave_penalty_days", "إجازة زيادة", "Leave over balance", "days"],
    ["target_miss_penalty", "التارجت مااتحققش", "Missed target", ""],
  ];

  return (
    <>
      <div className="page-head">
        <h1>{t("المخالفات والخصومات", "Violations and deductions")}</h1>
        <div className="page-head__sub">{t("مفيش خصم بيتطبق قبل اعتماد المدير.", "No deduction applies before the manager approves it.")}</div>
      </div>

      <div className="grid grid--main">
        <div>
          <div className="card">
            <div className="card__head">
              <Icon name="timer" />
              <h3>{t("مستنية الاعتماد", "Awaiting approval")}</h3>
            </div>
            <div className="table-wrap">
              <table className="table" data-table="pending">
                <thead>
                  <tr>
                    <th>{t("المترجم", "Translator")}</th>
                    <th>{t("التاريخ", "Date")}</th>
                    <th>{t("النوع", "Kind")}</th>
                    <th>{t("التاسك", "Task")}</th>
                    <th>{t("السبب", "Reason")}</th>
                    <th>{t("الخصم", "Penalty")}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.pending.map((row) => (
                    <Row key={row.id} row={row}>
                      <td className="mono">{row.task ?? "—"}</td>
                      <td className="muted">{row.reason}</td>
                      <td className="mono">
                        <Penalty row={row} />
                      </td>
                      <td>
                        <div className="row row--tight">
                          <button className="btn btn--sm btn--ok" type="button" disabled={decide.isPending} onClick={() => act(row.id, "approve")}>
                            {t("اعتماد", "Approve")}
                          </button>
                          <button className="btn btn--sm btn--ghost" type="button" disabled={decide.isPending} onClick={() => act(row.id, "reject")}>
                            {t("رفض", "Reject")}
                          </button>
                        </div>
                      </td>
                    </Row>
                  ))}
                  {data.pending.length === 0 && (
                    <tr>
                      <td colSpan={7} className="empty">
                        {t("مفيش حاجة مستنية.", "Nothing waiting.")}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card">
            <div className="card__head">
              <Icon name="history" />
              <h3>{t("اتقرر فيها", "Decided")}</h3>
            </div>
            <div className="table-wrap">
              <table className="table" data-table="decided">
                <thead>
                  <tr>
                    <th>{t("المترجم", "Translator")}</th>
                    <th>{t("التاريخ", "Date")}</th>
                    <th>{t("النوع", "Kind")}</th>
                    <th>{t("الحالة", "State")}</th>
                    <th>{t("اعتمدها", "By")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.decided.map((row) => (
                    <Row key={row.id} row={row}>
                      <td>
                        {row.status === "approved" ? (
                          <span className="badge badge--dead">{t("مطبق", "Applied")}</span>
                        ) : (
                          <span className="badge badge--info">{t("مرفوض", "Rejected")}</span>
                        )}
                      </td>
                      <td className="muted">{row.decided_by ?? "—"}</td>
                    </Row>
                  ))}
                  {data.decided.length === 0 && (
                    <tr>
                      <td colSpan={5} className="empty">
                        {t("لسه مفيش.", "Nothing yet.")}
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
              <h3>{t("سجل مخالفة", "Record a violation")}</h3>
            </div>
            <form onSubmit={submit}>
              <DjangoForm fields={data.form} edits={edits} errors={errors} prefix="violation" />
              {failed && (
                <div className="note note--high" role="alert">
                  <Icon name="alert" />
                  <div>{t("حصلت مشكلة، ماتسجلتش.", "Something went wrong, nothing was recorded.")}</div>
                </div>
              )}
              <button className="btn btn--primary btn--block" type="submit" disabled={propose.isPending || !edits.dirty}>
                <Icon name="check" size="sm" />
                <span>{t("سجل", "Record")}</span>
              </button>
            </form>
          </div>

          <div className="card">
            <div className="card__head">
              <Icon name="list-checks" />
              <h3>{t("القيم الافتراضية", "Default penalties")}</h3>
            </div>
            {defaults.map(([key, ar, en, unit]) => (
              <div className="kv" key={key}>
                <span>{lang === "ar" ? ar : en}</span>
                <span className="mono">
                  {data.conf[key as keyof typeof data.conf]}
                  {unit && <span className="muted"> {t("يوم", "days")}</span>}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
