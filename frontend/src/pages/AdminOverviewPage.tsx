import { useState } from "react";
import { Loading } from "../components/Loading";
import { Link, Navigate } from "react-router";
import { useCancelTask, useOverviewDeliver } from "../api/opsActions";
import { useAdminOverview, useMe } from "../api/queries";
import type { AdminOverview, Stamp } from "../api/types";
import { OriginBadge, StatusBadge } from "../components/Badges";
import { Confirm } from "../components/Confirm";
import { Icon } from "../components/Icon";
import { MailFiles } from "../components/MailFiles";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";
import { taskProblem } from "../lib/taskProblem";

const taskPath = (code: string) => `/tasks/${encodeURIComponent(code)}`;

function Counters({ counters }: { counters: AdminOverview["counters"] }) {
  const { t } = usePreferences();
  return (
    <div className="grid grid--4" style={{ marginBottom: 18 }}>
      <div className="kpi">
        <div className="kpi__value">{counters.new}</div>
        <div className="kpi__label">{t("تاسكات جديدة", "New tasks")}</div>
      </div>
      <div className="kpi kpi--warn">
        <div className="kpi__value">{counters.open}</div>
        <div className="kpi__label">{t("شغالة", "Open")}</div>
      </div>
      <div className="kpi kpi--ok">
        <div className="kpi__value">{counters.delivered}</div>
        <div className="kpi__label">{t("اتسلمت", "Delivered")}</div>
      </div>
      <div className="kpi">
        <div className="kpi__value">{counters.clients}</div>
        <div className="kpi__label">{t("عملاء", "Clients")}</div>
      </div>
    </div>
  );
}

/** Letters the rate rule keeps from the operation: the admin reads them here, with who sent them and which word held them. */
function Blocked({ rows }: { rows: AdminOverview["blocked"] }) {
  const { t, lang } = usePreferences();
  const when = (stamp: Stamp | null) => (stamp ? (lang === "ar" ? stamp.ar : stamp.en) : "");
  return (
    <div className="card">
      <div className="card__head">
        <Icon name="shield" />
        <h3>{t("رسايل محجوبة عن الأوبريشن", "Hidden from Operation")}</h3>
      </div>
      {/* Up to twenty letters: they scroll inside the card, so the page does not grow with them. */}
      <div className="overview-held" data-testid="held-letters">
        {rows.map((letter) => (
          <div className="msg-item is-blocked" key={letter.id} data-letter={letter.id}>
            <div className="msg-item__body">
              <div className="row row--between">
                <strong className="mono">{letter.code}</strong>
                <small className="mono">{when(letter.at)}</small>
              </div>
              <div className="msg-item__text">{letter.body}</div>
              <MailFiles files={letter.files} />
              <small className="muted mono">
                {letter.sender} · {letter.keyword}
              </small>
            </div>
          </div>
        ))}
        {rows.length === 0 && <div className="muted">{t("مفيش رسايل محجوبة.", "Nothing hidden.")}</div>}
      </div>
    </div>
  );
}

/**
 * «سلّم للعميل» beside a task awaiting delivery: after the «تأكيد», the admin takes it over and its final files go to the client
 * (`api_admin.deliver`). A refusal - no final file, no number or address - stays in the box, where it happened.
 */
function DeliverNow({ code }: { code: string }) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const deliver = useOverviewDeliver(code);
  const [asking, setAsking] = useState(false);
  const [problem, setProblem] = useState("");
  return (
    <>
      <button
        className="btn btn--ok btn--sm overview-act"
        type="button"
        onClick={() => {
          setProblem("");
          setAsking(true);
        }}
      >
        <Icon name="send" size="sm" />
        <span>{t("سلّم للعميل", "Deliver to client")}</span>
      </button>
      {asking && (
        <Confirm
          title={t(`تسلّم ${code} للعميل؟`, `Deliver ${code} to the client?`)}
          body={t(
            "هتستلم التاسك وتتبعت الملفات النهائية للعميل على قناته (ملف التيم ليدر المصحّح لو موجود، وإلا ملف المترجم). الإرسال مايترجعش.",
            "You take the task over and its final files go to the client on their channel (the leader's corrected file if there is one, else the translator's). Sending cannot be undone.",
          )}
          yes={t("سلّم للعميل", "Deliver to client")}
          icon="send"
          busy={deliver.isPending}
          problem={problem}
          onNo={() => setAsking(false)}
          onYes={() =>
            deliver.mutate(undefined, {
              onSuccess: () => {
                setAsking(false);
                push({ level: "success", title: t("تم التسليم", "Delivered") });
              },
              onError: (error) => setProblem(taskProblem(error, t)),
            })
          }
        />
      )}
    </>
  );
}

/** «الغِ التاسك» beside a late task: the task page's own door (`task_action` cancel), after the «تأكيد». */
function CancelLate({ code }: { code: string }) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const cancel = useCancelTask(code);
  const [asking, setAsking] = useState(false);
  const [problem, setProblem] = useState("");
  return (
    <>
      <button
        className="btn btn--danger btn--sm overview-act"
        type="button"
        onClick={() => {
          setProblem("");
          setAsking(true);
        }}
      >
        <Icon name="x" size="sm" />
        <span>{t("الغِ التاسك", "Cancel task")}</span>
      </button>
      {asking && (
        <Confirm
          title={t(`إلغاء ${code}؟`, `Cancel ${code}?`)}
          yes={t("ألغي التاسك", "Cancel the task")}
          danger
          busy={cancel.isPending}
          problem={problem}
          onNo={() => setAsking(false)}
          onYes={() =>
            cancel.mutate(undefined, {
              onSuccess: () => {
                setAsking(false);
                push({ level: "warning", title: t("التاسك اتلغت", "Task cancelled") });
              },
              onError: (error) => setProblem(taskProblem(error, t)),
            })
          }
        />
      )}
    </>
  );
}

/**
 * The admin's board: the four numbers, the letters held back from the operation, the hand-offs waiting for an answer,
 * the tasks past their date and the newest ones. Two things are done from here: a task awaiting delivery is sent to the client
 * («سلّم للعميل»), and a late task is cancelled («الغِ التاسك»); everything else, on the pages these link to.
 */
export function AdminOverviewPage() {
  const { t, lang } = usePreferences();
  const me = useMe();
  // The same person the server lets in (`api_role_required`: the admin).
  const allowed = me.data !== undefined && me.data.user.is_admin;
  const query = useAdminOverview(allowed);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  const data = query.data;
  const when = (stamp: Stamp | null) => (stamp ? (lang === "ar" ? stamp.ar : stamp.en) : "");

  return (
    <>
      <div className="page-head">
        <h1>{t("نظرة عامة", "Overview")}</h1>
      </div>

      {data && <Counters counters={data.counters} />}

      {data ? (
        <div className="grid grid--2">
          <Blocked rows={data.blocked} />

          <div>
            <div className="card">
              <div className="card__head">
                <Icon name="timer" />
                <h3>{t("تأكيدات مستنية", "Pending confirmations")}</h3>
              </div>
              <ul className="timeline">
                {data.pending.map((row) => (
                  <li key={row.id}>
                    <Link className="mono" to={taskPath(row.task)}>
                      {row.task}
                    </Link>
                    <span className="grow">{row.assignee}</span>
                    <span className="badge badge--wait mono">{row.seconds_left}s</span>
                  </li>
                ))}
                {data.pending.length === 0 && <li className="muted">{t("مفيش.", "None.")}</li>}
              </ul>
            </div>

            <div className="card">
              <div className="card__head">
                <Icon name="alert" />
                <h3>{t("تاسكات عدّت الديدلاين", "Late tasks")}</h3>
              </div>
              <ul className="timeline">
                {data.late.map((row) => (
                  <li key={row.code}>
                    <Link className="mono" to={taskPath(row.code)}>
                      {row.code}
                    </Link>
                    <span className="grow">{row.translator ?? "—"}</span>
                    <span className="badge badge--dead mono">{when(row.deadline)}</span>
                    <CancelLate code={row.code} />
                  </li>
                ))}
                {data.late.length === 0 && <li className="muted">{t("كله في ميعاده.", "All on time.")}</li>}
              </ul>
            </div>

            <div className="card">
              <div className="card__head">
                <Icon name="layers" />
                <h3>{t("آخر التاسكات", "Latest tasks")}</h3>
              </div>
              <ul className="timeline">
                {data.recent.map((row) => (
                  <li key={row.code}>
                    <Link className="mono" to={taskPath(row.code)}>
                      {row.code}
                    </Link>
                    <span className="grow">
                      {row.title} <OriginBadge origin={row.origin} />
                    </span>
                    <StatusBadge status={row.status} />
                    {row.status.value === "reviewed" && <DeliverNow code={row.code} />}
                  </li>
                ))}
                {data.recent.length === 0 && <li className="muted">{t("مفيش.", "None.")}</li>}
              </ul>
            </div>
          </div>
        </div>
      ) : query.isError ? (
        <div className="card empty" role="alert">
          <Icon name="alert" size="xl" />
          <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
        </div>
      ) : (
        <Loading className="card empty" />
      )}
    </>
  );
}
