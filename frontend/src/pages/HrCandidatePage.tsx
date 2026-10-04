import { Link, Navigate, useParams } from "react-router";
import { ApiError } from "../api/client";
import { useHrCandidate } from "../api/queries";
import { Waiting } from "../components/accounts/shared";
import { IdentityCard, InterviewCard, MessageCard, ProfileCard, StatusCard, TestCard } from "../components/hr/CandidateCards";
import { FileChip, useHrAllowed, useStamp } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { LeaveStatusBadge, useLeaveWords } from "../components/leave/shared";
import { usePreferences } from "../i18n/Preferences";

/**
 * The whole application on one page and everything HR can do to it. What the bot collected is shown as the candidate said it; the
 * company's name is kept from the candidate until HR reveals it, and a message goes only through the server's identity filter.
 */
export function HrCandidatePage() {
  const { t } = usePreferences();
  const words = useLeaveWords();
  const stamp = useStamp();
  const { me, allowed } = useHrAllowed();
  const code = useParams().code ?? "";
  const query = useHrCandidate(code, allowed);
  const data = query.data;

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

  return (
    <>
      <div className="page-head">
        <h1>{who.name}</h1>
        <span className="mono muted">{who.code}</span>
        <LeaveStatusBadge status={who.status} />
        {who.identity.revealed ? (
          <span className="badge badge--info" data-badge="revealed">
            {t("يعرف اسم الشركة", "Knows who we are")}
          </span>
        ) : (
          <span className="badge" data-badge="anonymous">
            {t("مجهول الجهة", "Anonymous")}
          </span>
        )}
        <div className="grow" />
        {data.can.hire && !who.hired_user && (
          <Link className="btn btn--primary btn--sm" to={`/hr/candidates/${who.code}/hire`}>
            <Icon name="user-check" size="sm" />
            <span>{t("حوّله لموظف", "Make an employee")}</span>
          </Link>
        )}
        {who.hired_user && (
          <Link className="btn btn--sm" to={`/hr/employees/${who.hired_user}`}>
            <Icon name="user" size="sm" />
            <span>{t("ملف الموظف", "Employee file")}</span>
          </Link>
        )}
      </div>

      {!data.privacy_armed && (
        <div className="note note--high" data-note="privacy">
          <Icon name="alert" />
          <div>
            {t(
              "قاعدة إخفاء الهوية مش مفعّلة — أي رسالة تبعتها ممكن تكشف اسم الشركة.",
              "The identity rule is not armed, so anything you send could reveal the company.",
            )}{" "}
            <Link to="/hr/recruitment/settings">{t("إعدادات التوظيف", "Recruitment settings")}</Link>
          </div>
        </div>
      )}

      <div className="grid grid--main">
        <div className="stack">
          <div className="card" data-card="answers">
            <div className="card__head">
              <Icon name="message" />
              <h3>{t("إجابات المرشح", "What the candidate answered")}</h3>
              <div className="grow" />
              {who.vacancy_code && (
                <Link className="chip mono" to={`/hr/vacancies/${who.vacancy_code}`}>
                  {who.vacancy_code}
                </Link>
              )}
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("السؤال", "Question")}</th>
                    <th>{t("الإجابة", "Answer")}</th>
                    <th>{t("الوقت", "At")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.answers.map((row, index) => (
                    <tr key={index}>
                      <td>{row.question}</td>
                      <td>
                        {row.value || "—"} {row.file && <FileChip file={row.file} />}
                      </td>
                      <td className="mono muted">{stamp(row.at)}</td>
                    </tr>
                  ))}
                  {data.answers.length === 0 && (
                    <tr>
                      <td colSpan={3} className="empty">
                        {t("المرشح ده اتسجل بالإيد — مفيش إجابات بوت.", "Entered by hand: there are no bot answers.")}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card" data-card="interviews">
            <div className="card__head">
              <Icon name="calendar" />
              <h3>{t("المقابلات", "Interviews")}</h3>
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("الموعد", "When")}</th>
                    <th>{t("النوع", "Type")}</th>
                    <th>{t("المُقابِل", "Interviewer")}</th>
                    <th>{t("الدرجة", "Score")}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.interviews.map((row) => (
                    <tr key={row.id} data-interview={row.id}>
                      <td className="mono">{stamp(row.at)}</td>
                      <td className="muted">{words(row.kind)}</td>
                      <td>{row.interviewer ?? "—"}</td>
                      <td className="mono">
                        {row.evaluated ? (
                          <>
                            {row.total} / {row.max}
                          </>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td>
                        <Link className="btn btn--sm btn--ghost" to={`/hr/interviews/${row.id}`}>
                          <Icon name="star" size="sm" />
                          <span>{t("قيّم", "Score")}</span>
                        </Link>
                      </td>
                    </tr>
                  ))}
                  {data.interviews.length === 0 && (
                    <tr>
                      <td colSpan={5} className="empty">
                        {t("مفيش مقابلات.", "No interviews.")}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card" data-card="tests">
            <div className="card__head">
              <Icon name="file" />
              <h3>{t("الاختبارات", "Tests")}</h3>
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("الاختبار", "Test")}</th>
                    <th>{t("المراجع", "Reviewer")}</th>
                    <th>{t("التسليم", "Submitted")}</th>
                    <th>{t("الدرجة", "Score")}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.tests.map((row) => (
                    <tr key={row.id} data-test={row.id}>
                      <td>
                        {row.title || "—"} {row.assignment && <FileChip file={row.assignment} />}
                        {row.overdue && <span className="badge badge--dead">{t("فات الموعد", "Overdue")}</span>}
                      </td>
                      <td>{row.reviewer ?? "—"}</td>
                      <td className="mono muted">{stamp(row.submitted_at)}</td>
                      <td className="mono">
                        {row.marked ? (
                          <>
                            {row.total} / {row.max}
                          </>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td>
                        {data.can.mark && (
                          <Link className="btn btn--sm btn--ghost" to={`/reviewer/tests/${row.id}`}>
                            <Icon name="check-circle" size="sm" />
                            <span>{t("صحّح", "Mark")}</span>
                          </Link>
                        )}
                      </td>
                    </tr>
                  ))}
                  {data.tests.length === 0 && (
                    <tr>
                      <td colSpan={5} className="empty">
                        {t("مفيش اختبارات.", "No tests.")}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="sticky-side">
          <StatusCard data={data} key={`status-${who.status.value}`} />
          <IdentityCard data={data} />
          <MessageCard data={data} />
          <InterviewCard data={data} />
          <TestCard data={data} />
          <ProfileCard data={data} />
        </div>
      </div>
    </>
  );
}
