import { useState } from "react";
import { Link } from "react-router";
import { useDecidePenalty } from "../../api/hrActions";
import { ApiError } from "../../api/client";
import type { HrPenalty } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { Icon } from "../Icon";
import { LeaveStatusBadge } from "../leave/shared";
import { useToasts } from "../Toasts";

/** What a refused decision says, in words: it was decided already, it is the person's own, or they may not. */
function refusalWords(failure: unknown, t: (ar: string, en: string) => string): string {
  if (failure instanceof ApiError) {
    if (failure.code === "decided") return t("اتقرر في الخصم ده قبل كده.", "This penalty was already decided.");
    if (failure.code === "own_record") return t("مينفعش تقرر في خصم بتاعك.", "You cannot decide your own penalty.");
    if (failure.status === 403) return t("مش مسموحلك.", "You may not do that.");
  }
  return t("ماتحفظش. جرّب تاني.", "Not saved. Try again.");
}

/**
 * One penalty: how many stars, why, on which task, and what was done with it. While it waits and the reader may decide, the two
 * buttons: apply it (the stars stay off) or forgive it (they are given back to the person, who is told). A penalty is decided once.
 */
export function PenaltyRow({
  row,
  canDecide,
  canChange = false,
  showPerson,
}: {
  row: HrPenalty;
  canDecide: boolean;
  /** The admin: what was decided can be turned round - forgive what stands, apply again what was forgiven. */
  canChange?: boolean;
  showPerson: boolean;
}) {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const decide = useDecidePenalty();
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState("");
  const waiting = row.decision.value === "pending";
  // What is there already is not offered again: a decided penalty gets the one button that changes it.
  const turn = !waiting && canChange ? (row.decision.value === "confirmed" ? "forgive" : "confirm") : null;

  const send = (action: "confirm" | "forgive") => {
    setProblem("");
    decide.mutate(
      { id: row.id, action, note: note.trim() },
      {
        onSuccess: () => {
          setNote("");
          push({ level: "success", title: action === "forgive" ? t("اتسامح ورجعت النجوم", "Forgiven, the stars are back") : t("الخصم اتطبق", "Penalty applied") });
        },
        onError: (failure) => setProblem(refusalWords(failure, t)),
      },
    );
  };

  return (
    <li className="penalty" data-penalty={row.id} data-decision={row.decision.value}>
      <div className="row row--tight">
        <span className={`badge ${row.decision.value === "forgiven" ? "badge--ok" : "badge--dead"} mono`} title={t("نجوم اتخصمت", "Stars taken off")}>
          -{row.amount}
        </span>
        {showPerson && <Link to={`/hr/employees/${row.user.id}`}>{row.user.name}</Link>}
        <span className="grow">{lang === "en" ? row.reason.en || row.reason.ar : row.reason.ar}</span>
        {row.task && <span className="chip chip--sm mono">{row.task}</span>}
        <small className="muted mono">{row.at ? (lang === "en" ? row.at.en : row.at.ar) : ""}</small>
        <LeaveStatusBadge status={row.decision} />
      </div>
      {!waiting && (row.decided_by || row.note) && (
        <small className="muted">
          {row.decided_by}
          {row.note ? ` - ${row.note}` : ""}
        </small>
      )}
      {waiting && canDecide && (
        <div className="row row--tight penalty__actions">
          <input
            className="input"
            type="text"
            maxLength={200}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder={t("ملاحظة (اختياري)", "Note (optional)")}
            aria-label={t("ملاحظة", "Note")}
          />
          <button className="btn btn--sm btn--danger" type="button" disabled={decide.isPending} onClick={() => send("confirm")}>
            <Icon name="check" size="sm" />
            <span>{t("طبّق الخصم", "Apply it")}</span>
          </button>
          <button className="btn btn--sm" type="button" disabled={decide.isPending} onClick={() => send("forgive")}>
            <Icon name="refresh" size="sm" />
            <span>{t("سامحه وارجّع النجوم", "Forgive and give the stars back")}</span>
          </button>
        </div>
      )}
      {turn && (
        <div className="row row--tight penalty__actions">
          <input
            className="input"
            type="text"
            maxLength={200}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder={t("ملاحظة (اختياري)", "Note (optional)")}
            aria-label={t("ملاحظة", "Note")}
          />
          <button className={`btn btn--sm${turn === "confirm" ? " btn--danger" : ""}`} type="button" data-turn={turn} disabled={decide.isPending} onClick={() => send(turn)}>
            <Icon name={turn === "confirm" ? "check" : "refresh"} size="sm" />
            <span>{turn === "confirm" ? t("طبّق الخصم تاني", "Apply it again") : t("سامحه وارجّع النجوم", "Forgive and give the stars back")}</span>
          </button>
        </div>
      )}
      {problem && (
        <div className="note note--high" role="alert">
          <Icon name="alert" />
          <div>{problem}</div>
        </div>
      )}
    </li>
  );
}

/** What took stars off one person, newest first, on their file: for HR and the admin. */
export function PenaltiesCard({ rows, canDecide, canChange = false }: { rows: HrPenalty[]; canDecide: boolean; canChange?: boolean }) {
  const { t } = usePreferences();
  return (
    <div className="card" data-card="penalties">
      <div className="card__head">
        <Icon name="star" />
        <h3>{t("خصومات التقييم", "Rating penalties")}</h3>
      </div>
      <ul className="timeline">
        {rows.map((row) => (
          <PenaltyRow key={row.id} row={row} canDecide={canDecide} canChange={canChange} showPerson={false} />
        ))}
        {rows.length === 0 && <li className="muted">{t("مفيش خصومات.", "No penalties.")}</li>}
      </ul>
    </div>
  );
}

/** Every penalty still waiting, over the register: the one place HR and the admin see who lost stars and decide. */
export function PenaltyQueue({ rows, waiting, canDecide }: { rows: HrPenalty[]; waiting: number; canDecide: boolean }) {
  const { t } = usePreferences();
  if (waiting === 0) return null;
  return (
    <div className="card" data-card="penalty-queue">
      <div className="card__head">
        <Icon name="star" />
        <h3>{t("خصومات نجوم مستنية قرار", "Star penalties waiting for a decision")}</h3>
        <span className="chip chip--sm mono">{waiting}</span>
      </div>
      <p className="muted">
        {t(
          "النجوم اتخصمت فعلًا. طبّق الخصم يفضل زي ما هو، أو سامحه ويرجّعوا للموظف.",
          "The stars are already off. Apply the penalty to keep it, or forgive it and they go back to the person.",
        )}
      </p>
      <ul className="timeline">
        {rows.map((row) => (
          <PenaltyRow key={row.id} row={row} canDecide={canDecide} showPerson />
        ))}
      </ul>
    </div>
  );
}
