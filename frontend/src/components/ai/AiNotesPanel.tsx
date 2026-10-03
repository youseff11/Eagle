import { useChatAiNotes } from "../../api/queries";
import { usePreferences } from "../../i18n/Preferences";
import { Icon } from "../Icon";

/**
 * What the AI noticed about the translation this person just handed over, beside the team leader's chat with them
 * (`templates/ops/chats.html`: «اقتراحات الـAI»). Suggestions - the review is the leader's, and nobody else sees this:
 * the door answers a team leader alone, and the notes are never written into the room, so it is not a public correction.
 * Drawn only when there is something to say (a check that found issues on a task that is under review); the notes are
 * already read through the mask for this reader. A conversation with a client has none and is not asked.
 */
export function AiNotesPanel({ code, enabled }: { code: string; enabled: boolean }) {
  const { t, lang } = usePreferences();
  const query = useChatAiNotes(code, enabled);
  const notes = query.data?.notes;
  if (!notes) return null;

  return (
    <details className="note ai-notes" open data-ai-panel={notes.task.code}>
      <summary>
        <Icon name="sparkles" size="sm" />
        <strong>{t("اقتراحات الـAI", "AI suggestions")}</strong> <span className="chip chip--sm mono">{notes.task.code}</span>{" "}
        <span className="chip chip--sm">{notes.count}</span>
      </summary>
      <div className="ai-notes__hint muted">
        {t("دي اقتراحات مش تصحيحات. المراجعة قرارك إنت، ومحدش غيرك شايف الكلام ده.", "Suggestions, not corrections. The review is yours, and nobody else sees this.")}
      </div>
      <ul className="ai-notes__list">
        {notes.issues.map((issue, index) => (
          <li key={index}>
            {issue.location && (
              <>
                <b className="mono">{issue.location}</b> ·{" "}
              </>
            )}
            {lang === "en" ? issue.text.en : issue.text.ar}
            <span className="chip chip--sm">{issue.severity}</span>
          </li>
        ))}
      </ul>
      {/* The leader's task page is still the classic one (a leader has no page of their own in the new app yet). */}
      <a className="btn btn--sm" href={`/tasks/${encodeURIComponent(notes.task.code)}/`}>
        <Icon name="arrow-right" size="sm" />
        <span>{t("افتح التاسك", "Open the task")}</span>
      </a>
    </details>
  );
}
