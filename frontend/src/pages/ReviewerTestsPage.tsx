import { Link, Navigate } from "react-router";
import { useReviewerQueue } from "../api/queries";
import type { ReviewerRow } from "../api/types";
import { Waiting } from "../components/accounts/shared";
import { useReviewerAllowed, useStamp } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { usePreferences } from "../i18n/Preferences";

/**
 * The reviewer's own queue: tests, and nothing else (section 24). A candidate is a code here and never a person: the name, the
 * phone, the salary they asked for and the vacancy are not a reviewer's business.
 */
export function ReviewerTestsPage() {
  const { t } = usePreferences();
  const stamp = useStamp();
  const { me, allowed } = useReviewerAllowed();
  const query = useReviewerQueue(allowed);
  const data = query.data;

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!data) return <Waiting failed={query.isError} />;

  const table = (rows: ReviewerRow[], done: boolean, empty: string) => (
    <div className="table-wrap">
      <table className="table" data-table={done ? "done" : "pending"}>
        <thead>
          <tr>
            <th>{t("المرشح", "Candidate")}</th>
            <th>{t("الاختبار", "Test")}</th>
            <th>{t("القسم", "Department")}</th>
            <th>{done ? t("الدرجة", "Score") : t("التسليم", "Submitted")}</th>
            <th>{done ? t("الوقت", "When") : ""}</th>
            {!done && <th />}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} data-test={row.id}>
              <td className="mono">{row.candidate}</td>
              <td>
                {row.title || "—"} {row.overdue && <span className="badge badge--dead">{t("فات الموعد", "Overdue")}</span>}
              </td>
              <td className="muted">{row.department ?? "—"}</td>
              <td className="mono">
                {done ? (
                  <>
                    {row.total} / {row.max}
                  </>
                ) : row.submitted ? (
                  stamp(row.submitted_at)
                ) : (
                  <span className="muted">{t("لسه", "not yet")}</span>
                )}
              </td>
              <td className="mono muted">{done ? stamp(row.marked_at) : ""}</td>
              {!done && (
                <td>
                  <Link className="btn btn--sm btn--primary" to={`/reviewer/tests/${row.id}`}>
                    <Icon name="pen" size="sm" />
                    <span>{t("صحّح", "Mark")}</span>
                  </Link>
                </td>
              )}
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={done ? 5 : 6} className="empty">
                {empty}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );

  return (
    <>
      <div className="page-head">
        <h1>{t("اختبارات المرشحين", "Candidate tests")}</h1>
      </div>
      <div className="card" data-card="pending">
        <div className="card__head">
          <Icon name="check-circle" />
          <h3>{t("مستنية تصحيح", "Waiting to be marked")}</h3>
        </div>
        {table(data.pending, false, t("مفيش اختبارات مستنية.", "Nothing waiting."))}
      </div>
      <div className="card" data-card="done">
        <div className="card__head">
          <Icon name="history" />
          <h3>{t("اتصححت", "Marked")}</h3>
        </div>
        {table(data.done, true, t("لسه مفيش.", "Nothing yet."))}
      </div>
    </>
  );
}
