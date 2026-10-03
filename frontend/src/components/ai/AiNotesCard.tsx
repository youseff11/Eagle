import { useState } from "react";
import { ApiError } from "../../api/client";
import { useAiRecheck } from "../../api/opsActions";
import { useTaskAiNotes } from "../../api/queries";
import type { AiNote, TaskAiNotes } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { taskProblem } from "../../lib/taskProblem";
import { Icon } from "../Icon";
import { useToasts } from "../Toasts";

const SEVERITY: Record<AiNote["severity"], [string, string]> = {
  high: ["مهم", "High"],
  medium: ["متوسط", "Medium"],
  low: ["بسيط", "Low"],
};

/** One note, as the classic box draws it: how serious, what kind, where; the two texts side by side; what is wrong; what the source means. */
export function Issue({ issue, index }: { issue: AiNote; index: number }) {
  const { t, lang } = usePreferences();
  return (
    <li className={`ai-issue ai-issue--${issue.severity}`} data-severity={issue.severity}>
      <div className="ai-issue__top">
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

function Box({ code, notes }: { code: string; notes: TaskAiNotes }) {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const recheck = useAiRecheck(code);
  const [problem, setProblem] = useState("");
  const { check } = notes;
  // No check has run yet (or an answer that is not one): nothing to say.
  if (!check) return null;

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
          {notes.issues.length > 0 ? (
            <ol className="ai-issues">
              {notes.issues.map((issue, index) => (
                <Issue key={index} issue={issue} index={index} />
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
            {t("دي اقتراحات بس — الـ AI مابيعدّلش الترجمة، والقرار للتيم ليدر.", "Suggestions only - the AI never edits the translation; the team leader decides.")}
          </p>
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
