import { useState } from "react";
import { Navigate, useSearchParams } from "react-router";
import { useDecideLeave } from "../api/leaveActions";
import { useHrLeave } from "../api/queries";
import { Waiting, refusal } from "../components/accounts/shared";
import { useHrAllowed, useStamp } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { LeaveStatusBadge, useLeaveWords } from "../components/leave/shared";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

const FILTERS = ["user", "status"] as const;

/**
 * The leave queue: what waits for a decision, and the record. What somebody can do to a row depends on where it is - the engine
 * says who may move a request along at which step, and a row's buttons are offered only to who may press them.
 */
export function HrLeavePage() {
  const { t } = usePreferences();
  const words = useLeaveWords();
  const stamp = useStamp();
  const { push } = useToasts();
  const { me, allowed } = useHrAllowed();
  const [params, setParams] = useSearchParams();
  const kept = new URLSearchParams();
  for (const name of FILTERS) {
    const value = params.get(name);
    if (value) kept.set(name, value);
  }
  const query = useHrLeave(kept.toString(), allowed);
  const decide = useDecideLeave();
  const [notes, setNotes] = useState<Record<number, string>>({});
  const data = query.data;

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!data) return <Waiting failed={query.isError} />;

  const set = (name: (typeof FILTERS)[number], value: string) => {
    const next = new URLSearchParams(kept);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next);
  };
  const act = (id: number, action: "approve" | "reject") =>
    decide.mutate(
      { id, action, note: action === "reject" ? (notes[id] ?? "") : "" },
      {
        onSuccess: () => setNotes((previous) => ({ ...previous, [id]: "" })),
        onError: (error) => push({ level: "danger", title: refusal(error, t("حصلت مشكلة.", "Something went wrong.")) }),
      },
    );
  const span = (row: { is_permission: boolean; start_date: string; end_date: string | null; days: number; start_time: Parameters<typeof stamp>[0]; end_time: Parameters<typeof stamp>[0] }) =>
    row.is_permission ? (
      <>
        <span className="mono">{row.start_date}</span> <span className="mono">{stamp(row.start_time)}–{stamp(row.end_time)}</span>
      </>
    ) : (
      <>
        <span className="mono">{row.start_date}</span> → <span className="mono">{row.end_date}</span>{" "}
        <span className="mono">
          ({row.days} {t("يوم", "days")})
        </span>
      </>
    );

  return (
    <>
      <div className="page-head">
        <h1>{t("طلبات الإجازة", "Leave requests")}</h1>
        <div className="grow" />
        <span className="chip mono" data-count="waiting">
          {data.waiting.length} <span>{t("مستني", "waiting")}</span>
        </span>
      </div>

      <div className="card">
        <div className="card__head">
          <Icon name="hand" />
          <h3>{t("مستني قرار", "Waiting")}</h3>
        </div>
        {data.waiting.map((row) => (
          <div className="card card--flat" key={row.id} data-waiting={row.id}>
            <div className="row row--between">
              <div>
                <b>{row.user.name}</b> <LeaveStatusBadge status={row.status} />
                <div className="muted">
                  {words(row.kind)} · {span(row)}
                </div>
                {row.reason && <div className="muted">{row.reason}</div>}
                {row.manager && (
                  <div className="muted" data-manager>
                    {t("مستني المدير:", "Waiting for the manager:")} {row.manager}
                  </div>
                )}
              </div>
              {row.can_decide && (
                <div className="row row--tight">
                  <button className="btn btn--ok btn--sm" type="button" disabled={decide.isPending} onClick={() => act(row.id, "approve")}>
                    <Icon name="check" size="sm" />
                    <span>{t("وافق", "Approve")}</span>
                  </button>
                  <input
                    className="input"
                    type="text"
                    aria-label={t("السبب", "Reason")}
                    placeholder={t("السبب", "Reason")}
                    maxLength={250}
                    value={notes[row.id] ?? ""}
                    onChange={(event) => setNotes((previous) => ({ ...previous, [row.id]: event.target.value }))}
                  />
                  <button className="btn btn--danger btn--sm" type="button" disabled={decide.isPending} onClick={() => act(row.id, "reject")}>
                    <Icon name="x" size="sm" />
                    <span>{t("ارفض", "Reject")}</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        ))}
        {data.waiting.length === 0 && <div className="empty">{t("مفيش طلبات مستنية.", "Nothing waiting.")}</div>}
      </div>

      <div className="card card--flat">
        <div className="picker">
          <div className="picker__row">
            <select className="input" aria-label={t("الموظف", "Employee")} value={kept.get("user") ?? ""} onChange={(event) => set("user", event.target.value)}>
              <option value="">{t("كل الموظفين", "Everyone")}</option>
              {data.options.people.map((one) => (
                <option key={one.id} value={one.id}>
                  {one.name}
                </option>
              ))}
            </select>
            <select className="input" aria-label={t("الحالة", "Status")} value={kept.get("status") ?? ""} onChange={(event) => set("status", event.target.value)}>
              <option value="">{t("كل الحالات", "All")}</option>
              {data.options.statuses.map((one) => (
                <option key={one.value} value={one.value}>
                  {words(one)}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card__head">
          <Icon name="history" />
          <h3>{t("السجل", "The record")}</h3>
        </div>
        <div className="table-wrap">
          <table className="table" data-table="record">
            <thead>
              <tr>
                <th>{t("الموظف", "Employee")}</th>
                <th>{t("النوع", "Kind")}</th>
                <th>{t("الأيام", "Dates")}</th>
                <th>{t("الحالة", "Status")}</th>
                <th>{t("مين قرر", "Decided by")}</th>
                <th>{t("اتكتبت", "Written")}</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <tr key={row.id} data-record={row.id}>
                  <td>{row.user.name}</td>
                  <td className="muted">{words(row.kind)}</td>
                  <td className="mono">
                    {row.start_date}
                    {row.end_date ? ` → ${row.end_date}` : ""}
                  </td>
                  <td>
                    <LeaveStatusBadge status={row.status} />
                  </td>
                  <td>{row.decided_by ?? "—"}</td>
                  <td className="mono muted">{row.applied ? <Icon name="check-circle" size="sm" /> : "—"}</td>
                </tr>
              ))}
              {data.rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="empty">
                    {t("مفيش سجلات.", "Nothing.")}
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
