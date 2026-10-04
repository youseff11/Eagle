import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router";
import { formErrors } from "../api/adminActions";
import { ApiError } from "../api/client";
import { useHire } from "../api/hrActions";
import { useHrHire } from "../api/queries";
import type { FormErrors } from "../api/types";
import { Waiting, refusal } from "../components/accounts/shared";
import { DjangoForm, useFormEdits } from "../components/admin/DjangoForm";
import { FileChip, useHrAllowed } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { LeaveStatusBadge } from "../components/leave/shared";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

/**
 * An approved candidate becomes an employee, once. Nothing is retyped: what the bot collected carries across, and this form is
 * only the contract side. The password typed here goes to the server and comes back nowhere; leave it empty and the account is locked
 * until one is set. The roles on offer are the ones the server lets this person hand out.
 */
export function HrHirePage() {
  const { t } = usePreferences();
  const { push } = useToasts();
  const navigate = useNavigate();
  const { me, allowed } = useHrAllowed();
  const code = useParams().code ?? "";
  const query = useHrHire(code, allowed);
  const hire = useHire(code);
  const data = query.data;
  const edits = useFormEdits(data?.form);
  const [errors, setErrors] = useState<FormErrors>({});
  const [problem, setProblem] = useState("");

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (query.error instanceof ApiError && query.error.status === 404) {
    return (
      <div className="card empty" role="alert">
        <span>{t("الصفحة دي مش موجودة.", "That page does not exist.")}</span>
      </div>
    );
  }
  if (!data) return <Waiting failed={query.isError} />;
  const who = data.candidate;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    setProblem("");
    hire.mutate(edits.edited, {
      onSuccess: (answer) => {
        edits.reset();
        push({ level: "success", title: t(`اتعيّن: ${answer.username}`, `Hired: ${answer.username}`) });
        navigate(`/hr/employees/${answer.id}`);
      },
      onError: (error) => {
        const found = formErrors(error);
        if (found) setErrors(found);
        else setProblem(refusal(error, t("التعيين ماتمش.", "The hire did not happen.")));
      },
    });
  };

  return (
    <>
      <div className="page-head">
        <h1>{who.name}</h1>
        <span className="mono muted">{who.code}</span>
        <LeaveStatusBadge status={who.status} />
      </div>

      <div className="grid grid--main">
        {data.hireable ? (
          <div className="card" data-card="contract">
            <div className="card__head">
              <Icon name="user-check" />
              <h3>{t("بيانات التعاقد", "Contract details")}</h3>
            </div>
            <div className="note note--info">
              <Icon name="info" />
              <div>
                {t(
                  "البيانات اللي البوت جمعها بتتنقل زي ما هي — اللي هنا هو بيانات التعاقد بس.",
                  "Everything the bot collected carries over. All this form needs is the contract side.",
                )}
              </div>
            </div>
            <form onSubmit={submit} autoComplete="off">
              <DjangoForm fields={data.form} edits={edits} errors={errors} prefix="hire" />
              {!data.form.some((one) => one.name === "salary") && (
                <div className="note note--info mt" data-note="salary-later">
                  <Icon name="info" />
                  <div>
                    {t(
                      "الراتب الأساسي بيحدده المالك. بعد التعيين اطلبه من «طلبات تغيير الراتب».",
                      "The owner sets the starting salary. After the hire, ask for it on the salary requests page.",
                    )}{" "}
                    <Link to="/hr/salary-requests">{t("طلبات تغيير الراتب", "Salary requests")}</Link>
                  </div>
                </div>
              )}
              {problem && (
                <div className="note note--high" role="alert">
                  <Icon name="alert" />
                  <div>{problem}</div>
                </div>
              )}
              <button className="btn btn--primary btn--block mt" type="submit" disabled={hire.isPending}>
                <Icon name="check" size="sm" />
                <span>{t("عيّنه", "Hire")}</span>
              </button>
            </form>
          </div>
        ) : (
          <div className="card" data-card="not-hireable">
            <div className="note note--warn" role="alert">
              <Icon name="alert" />
              <div>
                {who.hired_user
                  ? t("المرشح ده اتعيّن بالفعل.", "This candidate has already been hired.")
                  : t("لازم المالك يوافق الأول — التعيين مابيحصلش قبل كده.", "The owner has to approve first. Nobody is hired before that.")}{" "}
                <Link to={`/hr/candidates/${who.code}`}>{t("ارجع للمرشح", "Back to the candidate")}</Link>
                {who.hired_user && (
                  <>
                    {" · "}
                    <Link to={`/hr/employees/${who.hired_user}`}>{t("ملف الموظف", "Employee file")}</Link>
                  </>
                )}
              </div>
            </div>
          </div>
        )}

        <div className="sticky-side">
          <div className="card card--flat" data-card="carries">
            <div className="card__head">
              <Icon name="contact" />
              <h3>{t("اللي هيتنقل", "What carries over")}</h3>
            </div>
            <div className="kv">
              <span>{t("الاسم", "Name")}</span>
              <b>{who.name || "—"}</b>
            </div>
            <div className="kv">
              <span>{t("الموبايل", "Phone")}</span>
              <b className="mono" dir="ltr">
                {who.phone || "—"}
              </b>
            </div>
            <div className="kv">
              <span>{t("الإيميل", "E-mail")}</span>
              <b className="mono" dir="ltr">
                {who.email || "—"}
              </b>
            </div>
            <div className="kv">
              <span>{t("اللغات", "Languages")}</span>
              <b>{who.languages || "—"}</b>
            </div>
            <div className="kv">
              <span>{t("القسم", "Department")}</span>
              <b>{who.department ?? "—"}</b>
            </div>
            <div className="kv">
              <span>{t("الشيفت", "Shift")}</span>
              <b className="mono">{who.shift || "—"}</b>
            </div>
            <div className="kv">
              <span>{t("الـCV", "CV")}</span>
              <b>{who.cv ? <FileChip file={who.cv} /> : "—"}</b>
            </div>
          </div>
          <div className="note note--warn" data-note="probation">
            <Icon name="alert" />
            <div>
              {t(
                `هيبدأ تحت الاختبار ${data.probation_days} يوم. متنساش تضيفله جدول من صفحة جداول العمل، وإلا الحضور مش هيلاقي حاجة يقيس عليها.`,
                `They start on probation for ${data.probation_days} days. Give them a roster on the schedules page or attendance has nothing to measure.`,
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
