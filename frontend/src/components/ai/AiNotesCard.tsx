import { useState } from "react";
import { ApiError } from "../../api/client";
import { useAiRecheck, useAiRevise } from "../../api/opsActions";
import { useTaskAiNotes } from "../../api/queries";
import type { AiNote, AiRevision, TaskAiNotes } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { taskProblem } from "../../lib/taskProblem";
import { Icon } from "../Icon";
import { useToasts } from "../Toasts";

const SEVERITY: Record<AiNote["severity"], [string, string]> = {
  high: ["مهم", "High"],
  medium: ["متوسط", "Medium"],
  low: ["بسيط", "Low"],
};

/**
 * One note, as the classic box draws it: how serious, what kind, where; the two texts side by side; what is wrong; what the source
 * means. With `accept` it carries a box the team leader ticks to accept the note (a corrected copy is made from the ticked ones).
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

/** The corrected copies: running, failed, or ready to open. */
function Revisions({ rows }: { rows: AiRevision[] }) {
  const { t, lang } = usePreferences();
  if (rows.length === 0) return null;
  return (
    <div className="ai-revisions" data-ai-revisions>
      <h3>{t("الملفات المصحّحة", "Corrected files")}</h3>
      <ul className="timeline">
        {rows.map((row) => (
          <li key={row.id} data-revision={row.id} data-status={row.status}>
            <span className="chip chip--sm mono">{row.accepted.length}</span>
            <span className="grow">
              {row.status === "running" && t("بيتعمل دلوقتي...", "Being made now...")}
              {row.status === "error" && (
                <>
                  {t("الملف مااتعملش.", "The file was not made.")} <span className="muted mono">{row.error}</span>
                </>
              )}
              {row.status === "done" && row.file && (
                <a href={row.file.url} download>
                  {row.file.name}
                </a>
              )}
            </span>
            <small className="muted mono">{row.at ? (lang === "en" ? row.at.en : row.at.ar) : ""}</small>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The words of a refused «اعمل ملف»: why it was not started. */
function reviseWords(failure: unknown, t: (ar: string, en: string) => string): string {
  if (failure instanceof ApiError) {
    if (failure.code === "running") return t("فيه ملف بيتعمل دلوقتي. استنى لحد ما يخلص.", "A file is being made now. Wait for it to finish.");
    if (failure.code === "stale_check") return t("الفحص اتجدد وانت بتقرا. راجع الملاحظات الجديدة واختار تاني.", "The check was renewed while you were reading. Read the new notes and choose again.");
    if (failure.code === "limit") return t("اتعمل ملفات كتير للفحص ده. اطلب فحص جديد.", "Too many files were made for this check. Ask for a new check.");
    if (failure.code === "off") return t("فحص الـ AI متوقف من الإعدادات.", "The AI check is switched off in the settings.");
    if (failure.code === "nothing_accepted") return t("اختار ملاحظة واحدة على الأقل.", "Accept at least one note.");
    if (failure.status === 403) return t("مش مسموحلك.", "You may not do that.");
  }
  return t("ماتحفظش. جرّب تاني.", "Not saved. Try again.");
}

function Box({ code, notes }: { code: string; notes: TaskAiNotes }) {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const recheck = useAiRecheck(code);
  const revise = useAiRevise(code);
  const [problem, setProblem] = useState("");
  const [picked, setPicked] = useState<number[]>([]);
  const { check } = notes;
  const toggle = (id: number) => setPicked((now) => (now.includes(id) ? now.filter((one) => one !== id) : [...now, id]));
  const make = (body: { issues: number[] } | { all: true }) => {
    setProblem("");
    revise.mutate({ ...body, check: check?.id ?? 0 }, {
      onSuccess: () => {
        setPicked([]);
        push({ level: "info", title: t("بنعمل الملف. هيظهر هنا أول ما يخلص.", "The file is being made. It appears here when it is done.") });
      },
      onError: (failure) => setProblem(reviseWords(failure, t)),
    });
  };
  // No check has run yet (or an answer that is not one): nothing to say.
  if (!check) return null;
  const ids = notes.issues.flatMap((issue) => (issue.id === null ? [] : [issue.id]));

  const again = () => {
    setProblem("");
    recheck.mutate(undefined, {
      onSuccess: () => push({ level: "info", title: t("الفحص بدأ. الملاحظات هتظهر هنا أول ما يخلص.", "The check has started. The notes appear here when it is done.") }),
      onError: (failure) => setProblem(failureWords(failure, t)),
    });
  };

  return (
    <div className={`card ai-notes ai-notes--${check.status}`} id="aiNotes">
      <div className="card__head">
        <Icon name="sparkles" />
        <h2>{t("ملاحظات الـ AI على الترجمة", "AI notes on the translation")}</h2>
        <div className="grow" />
        <Status check={check} />
        <span className="muted mono ai-notes__when">
          {check.at ? (lang === "en" ? check.at.en : check.at.ar) : ""}
          {check.automatic ? ` · ${t("تلقائي", "automatic")}` : ""}
        </span>
        {notes.can_recheck && (
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
          {notes.can_revise && notes.issues.length > 0 && (
            <div className="ai-notes__accept row row--tight" data-ai-accept>
              <span className="muted">{t("اقبل الملاحظات اللي صح، وهنعمل ملف جديد بالتعديلات دي بس.", "Accept the notes that are right and a new file is made with only those corrections.")}</span>
              <div className="grow" />
              <button className="btn btn--sm" type="button" onClick={() => setPicked(picked.length === ids.length ? [] : ids)}>
                {picked.length === ids.length ? t("إلغاء الكل", "Clear all") : t("اختار الكل", "Select all")}
              </button>
              <button className="btn btn--sm btn--primary" type="button" disabled={picked.length === 0 || revise.isPending} onClick={() => make({ issues: picked })}>
                <Icon name="file" size="sm" />
                <span>{t(`اعمل ملف بالتعديلات (${picked.length})`, `Make a file with the corrections (${picked.length})`)}</span>
              </button>
              <button className="btn btn--sm" type="button" disabled={revise.isPending} onClick={() => make({ all: true })}>
                <span>{t("اقبل الكل واعمل الملف", "Accept all and make the file")}</span>
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
                    notes.can_revise && issue.id !== null
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
              "دي اقتراحات بس، والقرار للتيم ليدر. ملف المترجم مابيتغيّرش أبدًا: اللي بتقبله بيتعمل منه ملف جديد (نص من غير التنسيق).",
              "Suggestions only; the team leader decides. The translator file is never changed: what you accept goes into a new file (text, without the layout).",
            )}
          </p>
          <Revisions rows={notes.revisions} />
        </>
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
  return <Box code={code} notes={query.data} />;
}
