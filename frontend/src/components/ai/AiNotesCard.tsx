import { useState } from "react";
import { ApiError } from "../../api/client";
import { useAiAccept, useAiRecheck } from "../../api/opsActions";
import { useTaskAiNotes } from "../../api/queries";
import type { AiNote, TaskAiNotes } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { taskProblem } from "../../lib/taskProblem";
import { Confirm } from "../Confirm";
import { Icon } from "../Icon";
import { useToasts } from "../Toasts";

const SEVERITY: Record<AiNote["severity"], [string, string]> = {
  high: ["مهم", "High"],
  medium: ["متوسط", "Medium"],
  low: ["بسيط", "Low"],
};

/**
 * One note, as the classic box draws it: how serious, what kind, where; the two texts side by side; what is wrong; what the source
 * means. With `accept` it carries a box the team leader ticks to accept the note (the ticked ones take stars off the translator); a
 * note accepted already says so, and has no box.
 */
export function Issue({ issue, index, accept }: { issue: AiNote; index: number; accept?: { checked: boolean; toggle: () => void } }) {
  const { t, lang } = usePreferences();
  return (
    <li className={`ai-issue ai-issue--${issue.severity}`} data-severity={issue.severity}>
      <div className="ai-issue__top">
        {accept && (
          <label className="ai-issue__accept">
            <input type="checkbox" checked={accept.checked} onChange={accept.toggle} aria-label={t(`اقبل الملاحظة ${index + 1}`, `Accept note ${index + 1}`)} />
            <span>{t("اقبلها", "Accept")}</span>
          </label>
        )}
        {issue.accepted && <span className="badge badge--dead ai-issue__done">{t("اتقبلت", "Accepted")}</span>}
        <span className="ai-issue__num mono">{index + 1}</span>
        <span className="ai-issue__sev">{t(...SEVERITY[issue.severity])}</span>
        {issue.category && <span className="ai-issue__cat">{lang === "en" ? issue.category.en : issue.category.ar}</span>}
        {issue.location && <span className="ai-issue__where">{issue.location}</span>}
      </div>
      {issue.compared && (
        <div className="ai-issue__pair">
          <div className="ai-issue__side">
            <div className="ai-issue__label">{t("الأصل", "Source")}</div>
            <div className="ai-issue__quote" dir="auto">
              {issue.source || "—"}
            </div>
          </div>
          <div className="ai-issue__side ai-issue__side--tr">
            <div className="ai-issue__label">{t("الترجمة", "Translation")}</div>
            <div className="ai-issue__quote" dir="auto">
              {issue.translation || <span className="muted">{t("(مش موجودة في الترجمة)", "(missing from the translation)")}</span>}
            </div>
          </div>
        </div>
      )}
      <div className="ai-issue__text">{lang === "en" ? issue.text.en : issue.text.ar}</div>
      {issue.meaning && (
        <div className="ai-issue__meaning">
          <strong>{t("المعنى في الأصل:", "The source means:")}</strong> <span dir="auto">{issue.meaning}</span>
        </div>
      )}
    </li>
  );
}

function Status({ check }: { check: NonNullable<TaskAiNotes["check"]> }) {
  const { t } = usePreferences();
  if (check.status === "issues") {
    return (
      <span className="badge badge--dead">
        <span className="mono">{check.count}</span> <span>{t("ملاحظة", "note(s)")}</span>
      </span>
    );
  }
  if (check.status === "clean") return <span className="badge badge--ok">{t("مفيش أخطاء واضحة", "Nothing obvious")}</span>;
  if (check.status === "running") return <span className="badge badge--wait">{t("شغال دلوقتي", "Running")}</span>;
  return <span className="badge badge--dead">{t("الفحص مخلصش", "Did not finish")}</span>;
}

/** The words of a refused accept: why nothing was taken. */
function acceptWords(failure: unknown, t: (ar: string, en: string) => string): string {
  if (failure instanceof ApiError) {
    if (failure.code === "already") return t("الملاحظات دي اتقبلت قبل كده.", "These notes were accepted already.");
    if (failure.code === "stale_check") return t("الفحص اتجدد وانت بتقرا. راجع الملاحظات الجديدة واختار تاني.", "The check was renewed while you were reading. Read the new notes and choose again.");
    if (failure.code === "no_translator") return t("مفيش مترجم ماسك التاسك دي.", "No translator holds this task.");
    if (failure.code === "nothing_accepted") return t("اختار ملاحظة واحدة على الأقل.", "Accept at least one note.");
    if (failure.status === 403) return t("مش مسموحلك.", "You may not do that.");
  }
  return t("ماتحفظش. جرّب تاني.", "Not saved. Try again.");
}

/**
 * One check. On a task shared between translators there is one for each of them: `translator` says whose work it is about, and only the
 * first box carries the button that asks for the checks again (it asks for all of them).
 */
function Box({ code, notes, translator = null, first = true }: { code: string; notes: TaskAiNotes; translator?: string | null; first?: boolean }) {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const recheck = useAiRecheck(code);
  const accept = useAiAccept(code);
  const [problem, setProblem] = useState("");
  const [picked, setPicked] = useState<number[]>([]);
  // What is about to be accepted, held until the leader says yes to the cost: the ids, or everything that is left.
  const [asking, setAsking] = useState<{ issues: number[] } | { all: true } | null>(null);
  const [refused, setRefused] = useState("");
  const { check } = notes;
  const toggle = (id: number) => setPicked((now) => (now.includes(id) ? now.filter((one) => one !== id) : [...now, id]));
  // No check has run yet (or an answer that is not one): nothing to say.
  if (!check) return null;
  // Only the notes still to accept: an accepted one costs once and has no box.
  const open = notes.issues.flatMap((issue) => (issue.id === null || issue.accepted ? [] : [issue.id]));
  const count = asking === null ? 0 : "all" in asking ? open.length : asking.issues.length;
  const stars = (Number(notes.accept_cost.each) * count).toLocaleString("en", { maximumFractionDigits: 3 });
  const send = () => {
    if (asking === null) return;
    setRefused("");
    accept.mutate({ ...asking, check: check.id }, {
      onSuccess: (answer) => {
        setPicked([]);
        setAsking(null);
        push({ level: "info", title: t(`اتقبلت ${count} ملاحظة واتخصم ${Number(answer.taken).toLocaleString("en", { maximumFractionDigits: 3 })} نجمة.`, `${count} note(s) accepted, ${Number(answer.taken).toLocaleString("en", { maximumFractionDigits: 3 })} star(s) taken off.`) });
      },
      onError: (failure) => setRefused(acceptWords(failure, t)),
    });
  };

  const again = () => {
    setProblem("");
    recheck.mutate(undefined, {
      onSuccess: () => push({ level: "info", title: t("الفحص بدأ. الملاحظات هتظهر هنا أول ما يخلص.", "The check has started. The notes appear here when it is done.") }),
      onError: (failure) => setProblem(failureWords(failure, t)),
    });
  };

  return (
    <div className={`card ai-notes ai-notes--${check.status}`} id={first ? "aiNotes" : undefined} data-ai-translator={translator ?? undefined}>
      <div className="card__head">
        <Icon name="sparkles" />
        <h2>{translator ? t(`ملاحظات الـ AI على ترجمة ${translator}`, `AI notes on ${translator}'s translation`) : t("ملاحظات الـ AI على الترجمة", "AI notes on the translation")}</h2>
        <div className="grow" />
        <Status check={check} />
        <span className="muted mono ai-notes__when">
          {check.at ? (lang === "en" ? check.at.en : check.at.ar) : ""}
          {check.automatic ? ` · ${t("تلقائي", "automatic")}` : ""}
        </span>
        {notes.can_recheck && first && (
          <button className="btn btn--sm" type="button" disabled={recheck.isPending} onClick={again}>
            <Icon name="refresh" size="sm" />
            <span>{t("أعد الفحص", "Check again")}</span>
          </button>
        )}
      </div>

      {problem && (
        <div className="note note--high" role="alert">
          <Icon name="alert" />
          <div>{problem}</div>
        </div>
      )}

      {check.old && (
        <div className="note note--warn">
          <Icon name="info" />
          <div>
            {t(
              "الملاحظات دي من الفحص القديم، من غير مقارنة الأصل بالترجمة. دوس «أعد الفحص» عشان تطلع بالشكل الجديد.",
              "These notes are from the old check, without the source-to-translation comparison. Press Check again for the new one.",
            )}
          </div>
        </div>
      )}

      {check.status === "running" ? (
        <div className="note note--info">
          <Icon name="timer" />
          <div>{t("الـ AI بيقرا الملفات دلوقتي. الصفحة هتتحدث لوحدها أول ما يخلص.", "The AI is reading the files now. This page updates itself when it is done.")}</div>
        </div>
      ) : check.status === "error" ? (
        <div className="note note--high">
          <Icon name="alert" />
          <div>
            <strong>{t("الفحص مخلصش — راجعها بنفسك.", "The check did not finish - review it yourself.")}</strong>
            <div className="muted mono ai-notes__error">{check.error}</div>
          </div>
        </div>
      ) : (
        <>
          {check.summary && (
            <p className="ai-notes__summary" style={{ whiteSpace: "pre-line" }}>
              {check.summary}
            </p>
          )}
          {notes.can_accept && open.length > 0 && (
            <div className="ai-notes__accept row row--tight" data-ai-accept>
              <span className="muted">
                {t(
                  `اقبل الملاحظات اللي صح. كل ملاحظة بتتقبل بتخصم ${notes.accept_cost.each} نجمة من تقييم المترجم${notes.accept_cost.translator ? ` (${notes.accept_cost.translator})` : ""}.`,
                  `Accept the notes that are right. Each accepted note takes ${notes.accept_cost.each} star(s) off the translator's rating${notes.accept_cost.translator ? ` (${notes.accept_cost.translator})` : ""}.`,
                )}
              </span>
              <div className="grow" />
              <button className="btn btn--sm" type="button" onClick={() => setPicked(picked.length === open.length ? [] : open)}>
                {picked.length === open.length ? t("إلغاء الكل", "Clear all") : t("اختار الكل", "Select all")}
              </button>
              <button className="btn btn--sm btn--danger" type="button" disabled={picked.length === 0 || accept.isPending} onClick={() => setAsking({ issues: picked })}>
                <span>{t(`اقبل المحدد (${picked.length})`, `Accept the selected (${picked.length})`)}</span>
              </button>
              <button className="btn btn--sm" type="button" disabled={accept.isPending} onClick={() => setAsking({ all: true })}>
                <span>{t("اقبل الكل", "Accept all")}</span>
              </button>
            </div>
          )}
          {notes.issues.length > 0 ? (
            <ol className="ai-issues">
              {notes.issues.map((issue, index) => (
                <Issue
                  key={index}
                  issue={issue}
                  index={index}
                  accept={
                    notes.can_accept && issue.id !== null && !issue.accepted
                      ? { checked: picked.includes(issue.id), toggle: () => toggle(issue.id as number) }
                      : undefined
                  }
                />
              ))}
            </ol>
          ) : (
            check.status === "clean" && (
              <div className="note note--ok">
                <Icon name="check-circle" />
                <div>{t("الـ AI مالقاش أخطاء واضحة. المراجعة البشرية لسه مطلوبة.", "The AI found nothing obvious. Your own review still stands.")}</div>
              </div>
            )
          )}
          <p className="muted ai-notes__foot">
            {t(
              "دي اقتراحات بس، والقرار للتيم ليدر. الـ AI مابيعدّلش الترجمة، والخصم اللي بيتعمل بيراجعه الـ HR والأدمن.",
              "Suggestions only; the team leader decides. The AI never edits the translation, and HR and the admin review any deduction.",
            )}
          </p>
        </>
      )}
      {asking !== null && (
        <Confirm
          title={t("تقبل الملاحظات دي؟", "Accept these notes?")}
          body={t(
            `هيتخصم ${stars} نجمة من تقييم ${notes.accept_cost.translator ?? "المترجم"} (${count} ملاحظة). الـ HR والأدمن هيشوفوا الخصم ويقدروا يسامحوه.`,
            `${stars} star(s) will be taken off ${notes.accept_cost.translator ?? "the translator"}'s rating (${count} note(s)). HR and the admin will see it and may forgive it.`,
          )}
          yes={t("اقبل واخصم", "Accept and deduct")}
          danger
          busy={accept.isPending}
          problem={refused}
          onYes={send}
          onNo={() => {
            setAsking(null);
            setRefused("");
          }}
        />
      )}
    </div>
  );
}

/** The refusal of «أعد الفحص» in its own words (a sentence from the server), or in the person's. */
function failureWords(failure: unknown, t: (ar: string, en: string) => string): string {
  if (failure instanceof ApiError && failure.status === 403) return t("مش مسموحلك.", "You may not do that.");
  return taskProblem(failure, t);
}

/**
 * The AI's notes on a translation, open at the top of a task page: for the admin and the task's own team leader, who
 * decide what to do with them. Suggestions only. A task that has had no check says nothing; a check that is running says so
 * and the box follows it. Nobody else is asked for it: the door refuses and writes the refusal to the audit log.
 */
export function AiNotesCard({ code, enabled = true }: { code: string; enabled?: boolean }) {
  const query = useTaskAiNotes(code, enabled);
  if (!query.data) return null;
  const { checks, ...top } = query.data;
  if (!checks || checks.length < 2) return <Box code={code} notes={query.data} />;
  return (
    <>
      {checks.map((view, index) => (
        <Box key={view.translator?.id ?? `none-${index}`} code={code} notes={{ ...top, ...view }} translator={view.translator?.name ?? null} first={index === 0} />
      ))}
    </>
  );
}
