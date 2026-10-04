import { useState } from "react";
import { Link, Navigate } from "react-router";
import { useDecideHire } from "../api/hrActions";
import { useHrApprovals } from "../api/queries";
import type { HrScore } from "../api/types";
import { Waiting, refusal } from "../components/accounts/shared";
import { FileChip, useOwnerAllowed, useStamp } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { LeaveStatusBadge } from "../components/leave/shared";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

const score = (value: HrScore) => (value ? `${value.total} / ${value.max}` : "—");

/**
 * The owner's queue. Hiring never happens by itself, whatever the scores say: this page is the only place it is decided, and
 * it is the owner's alone. A rejection takes a reason; an approval is one click and goes on to HR, who makes the employee.
 */
export function HrApprovalsPage() {
  const { t } = usePreferences();
  const stamp = useStamp();
  const { push } = useToasts();
  const { me, allowed } = useOwnerAllowed();
  const query = useHrApprovals(allowed);
  const decide = useDecideHire();
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const data = query.data;

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!data) return <Waiting failed={query.isError} />;

  const act = (code: string, action: "approve" | "reject") =>
    decide.mutate(
      { code, action, reason: action === "reject" ? (reasons[code] ?? "").trim() : "" },
      {
        onSuccess: () => push({ level: "success", title: t("اتسجل القرار", "The decision was recorded") }),
        onError: (error) => push({ level: "danger", title: refusal(error, t("القرار ماتسجلش.", "The decision was not recorded.")) }),
      },
    );

  return (
    <>
      <div className="page-head">
        <h1>{t("موافقات التعيين", "Hiring approvals")}</h1>
      </div>

      <div className="note note--info">
        <Icon name="shield" />
        <div>
          {t(
            "التعيين مابيحصلش تلقائي مهما كانت الدرجات — ده المكان الوحيد اللي بيتقرر فيه.",
            "Hiring never happens automatically, whatever the scores say. This page is the only place it is decided.",
          )}
        </div>
      </div>

      <div className="card" data-card="waiting">
        <div className="card__head">
          <Icon name="user-check" />
          <h3>{t("مستني قرارك", "Waiting for you")}</h3>
        </div>
        {data.waiting.map((row) => (
          <div className="card card--flat" key={row.code} data-waiting={row.code}>
            <div className="row row--between">
              <div>
                <b>
                  <Link to={`/hr/candidates/${row.code}`}>{row.name}</Link>
                </b>{" "}
                <span className="mono muted">{row.code}</span>
                <div className="muted">
                  {row.vacancy ?? "—"} · {row.department ?? "—"}
                </div>
              </div>
              <div className="row row--tight">
                <button className="btn btn--ok btn--sm" type="button" disabled={decide.isPending} onClick={() => act(row.code, "approve")}>
                  <Icon name="check" size="sm" />
                  <span>{t("وافق على التعيين", "Approve")}</span>
                </button>
                <input
                  className="input"
                  type="text"
                  aria-label={t("سبب الرفض", "Reason for rejecting")}
                  placeholder={t("سبب الرفض", "Reason for rejecting")}
                  maxLength={250}
                  value={reasons[row.code] ?? ""}
                  onChange={(event) => setReasons((previous) => ({ ...previous, [row.code]: event.target.value }))}
                />
                <button className="btn btn--danger btn--sm" type="button" disabled={decide.isPending} onClick={() => act(row.code, "reject")}>
                  <Icon name="x" size="sm" />
                  <span>{t("ارفض", "Reject")}</span>
                </button>
              </div>
            </div>
            <div className="grid grid--4 mt">
              <div className="kv">
                <span>{t("درجة المقابلة", "Interview")}</span>
                <b className="mono" data-score="interview">
                  {score(row.interview_score)}
                </b>
              </div>
              <div className="kv">
                <span>{t("درجة الاختبار", "Test")}</span>
                <b className="mono" data-score="test">
                  {score(row.test_score)}
                </b>
              </div>
              <div className="kv">
                <span>{t("الراتب المتوقع", "Expected salary")}</span>
                <b className="mono">{row.expected_salary || "—"}</b>
              </div>
              <div className="kv">
                <span>{t("الـCV", "CV")}</span>
                <b>{row.cv ? <FileChip file={row.cv} /> : "—"}</b>
              </div>
            </div>
            {row.hr_recommendation && (
              <div className="note note--info mt">
                <Icon name="info" />
                <div>
                  <b>{t("توصية HR:", "HR recommendation:")}</b> {row.hr_recommendation}
                </div>
              </div>
            )}
            {row.hr_notes && <p className="muted">{row.hr_notes}</p>}
          </div>
        ))}
        {data.waiting.length === 0 && <div className="empty">{t("مفيش حاجة مستنية.", "Nothing waiting.")}</div>}
      </div>

      <div className="card" data-card="decided">
        <div className="card__head">
          <Icon name="history" />
          <h3>{t("اتقرر فيها", "Decided")}</h3>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>{t("المرشح", "Candidate")}</th>
                <th>{t("الوظيفة", "Vacancy")}</th>
                <th>{t("الحالة", "Status")}</th>
                <th>{t("القرار", "Decided")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.decided.map((row) => (
                <tr key={row.code} data-decided={row.code}>
                  <td>
                    <Link to={`/hr/candidates/${row.code}`}>{row.name}</Link>
                  </td>
                  <td className="muted">{row.vacancy ?? "—"}</td>
                  <td>
                    <LeaveStatusBadge status={row.status} />
                  </td>
                  <td className="mono muted">{stamp(row.decided_at)}</td>
                  <td>
                    {row.can_hire && (
                      <Link className="btn btn--sm btn--primary" to={`/hr/candidates/${row.code}/hire`}>
                        <Icon name="user-check" size="sm" />
                        <span>{t("حوّله لموظف", "Hire")}</span>
                      </Link>
                    )}
                  </td>
                </tr>
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
    </>
  );
}
