import { useState } from "react";
import { useAiCheck } from "../../api/queries";
import type { AiCheckAnswer, TranslatorTask } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { taskProblem } from "../../lib/taskProblem";
import { Icon } from "../Icon";

const SEVERITY_CLASS: Record<string, string> = { high: "note--high", medium: "note--warn", low: "note--info" };
const CHECK_CLASS: Record<string, string> = { issues: "note--warn", error: "note--high", running: "note--info" };
const CHECK_ICON: Record<string, string> = { issues: "alert", error: "alert", running: "timer" };

/** What the check found, as the classic page draws it: where, the two excerpts side by side, what is wrong, what the source means. */
function Result({ answer }: { answer: AiCheckAnswer }) {
  const { t, lang } = usePreferences();
  if (!answer.ok) {
    return (
      <div className="note note--high" role="alert">
        <Icon name="alert" />
        <div>{answer.error || t("الفحص فشل.", "The check failed.")}</div>
      </div>
    );
  }
  const issues = answer.issues ?? [];
  if (issues.length === 0) {
    return (
      <div className="note note--ok">
        <Icon name="check-circle" />
        <div>{t("مفيش أخطاء واضحة. ابعت الملفات في الشات للمراجعة.", "No obvious issues. Send the files in the chat for review.")}</div>
      </div>
    );
  }
  return (
    <>
      {answer.summary && (
        <div className="muted" style={{ marginBottom: 10, fontSize: ".84rem" }}>
          {answer.summary}
        </div>
      )}
      {issues.map((issue, index) => (
        <div className={`note ${SEVERITY_CLASS[issue.severity ?? "medium"] ?? "note--warn"}`} key={index}>
          <Icon name="map-pin" />
          <div>
            <div className="note__where">{issue.location}</div>
            {(issue.source_excerpt || issue.translation_excerpt) && (
              <div className="ai-issue__pair">
                <div className="ai-issue__side">
                  <div className="ai-issue__label">{t("الأصل", "Source")}</div>
                  <div className="ai-issue__quote" dir="auto">
                    {issue.source_excerpt || "-"}
                  </div>
                </div>
                <div className="ai-issue__side ai-issue__side--tr">
                  <div className="ai-issue__label">{t("الترجمة", "Translation")}</div>
                  <div className="ai-issue__quote" dir="auto">
                    {issue.translation_excerpt || t("(مش موجودة في الترجمة)", "(missing)")}
                  </div>
                </div>
              </div>
            )}
            <div>{lang === "ar" ? issue.issue_ar || issue.issue_en : issue.issue_en || issue.issue_ar}</div>
            {issue.correct_meaning_ar && (
              <div className="ai-issue__meaning">
                <strong>{t("المعنى في الأصل:", "The source means:")}</strong> {issue.correct_meaning_ar}
              </div>
            )}
          </div>
        </div>
      ))}
    </>
  );
}

/**
 * The translator's own check of a translation: the AI points out mistakes and where they are, and never edits.
 * Blank boxes mean "read the files on the task" - the server's call, the same files the automatic check reads.
 */
export function AiCheckCard({ code, ai }: { code: string; ai: TranslatorTask["ai"] }) {
  const { t, lang } = usePreferences();
  const check = useAiCheck(code);
  const [source, setSource] = useState("");
  const [translated, setTranslated] = useState("");

  return (
    <div className="card">
      <div className="card__head">
        <Icon name="sparkles" />
        <h3>{t("مراجعة الترجمة بالـ AI", "AI translation check")}</h3>
        <div className="grow" />
        <span className={`badge ${ai.enabled ? "badge--ok" : "badge--dead"}`}>
          <i className="badge__dot" />
          <span>{ai.enabled ? t("مفعّلة", "Enabled") : t("متوقفة من الأدمن", "Disabled by admin")}</span>
        </span>
      </div>

      {ai.enabled && (
        <>
          <p className="muted" style={{ fontSize: ".84rem" }}>
            {t(
              "الـ AI بيقولك الأخطاء ومكانها بس — مش بيعدّل الترجمة. سيب الخانات فاضية عشان يقرا آخر ملفات بعتها في الشات.",
              "The AI only points out issues and where they are — it never edits your translation. Leave the boxes empty to read the last files you sent in the chat.",
            )}
          </p>
          <div className="form-grid">
            <div className="field">
              <label htmlFor="aiSource">{t("النص الأصلي (اختياري)", "Source text (optional)")}</label>
              <textarea className="input" id="aiSource" rows={5} value={source} onChange={(event) => setSource(event.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="aiTranslated">{t("الترجمة", "Translation")}</label>
              <textarea className="input" id="aiTranslated" rows={5} value={translated} onChange={(event) => setTranslated(event.target.value)} />
            </div>
          </div>
          <button className="btn btn--accent" type="button" disabled={check.isPending} onClick={() => check.mutate({ source, translated })}>
            <Icon name="sparkles" size="sm" />
            <span>{check.isPending ? t("جاري المراجعة…", "Reviewing…") : t("تشيك", "Check")}</span>
          </button>
          <div className="mt">
            {check.isError && (
              <div className="note note--high" role="alert">
                <Icon name="alert" />
                <div>{taskProblem(check.error, t)}</div>
              </div>
            )}
            {check.data && <Result answer={check.data} />}
          </div>
        </>
      )}

      {ai.checks.map((row) => (
        <div className={`note mt ${CHECK_CLASS[row.status] ?? "note--ok"}`} key={row.id}>
          <Icon name={CHECK_ICON[row.status] ?? "check-circle"} />
          <div>
            <div className="note__where mono">
              {row.at ? (lang === "ar" ? row.at.ar : row.at.en) : ""} · {row.count}
              {row.automatic && <> · {t("تلقائي", "automatic")}</>}
            </div>
            {row.status === "running" ? (
              <div>{t("الفحص شغال دلوقتي — التنبيه هيوصلك أول ما يخلص.", "Running now — you will be notified when it finishes.")}</div>
            ) : (
              <div>{row.summary}</div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
