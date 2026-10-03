import { useState } from "react";
import type { Labelled } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { taskProblem } from "../../lib/taskProblem";
import { Icon } from "../Icon";
import { useToasts } from "../Toasts";

const REQUIREMENT_ICON: Record<string, string> = { like: "thumbs-up", dislike: "thumbs-down", rule: "pin" };
const REQUIREMENT_KINDS: [string, string, string][] = [
  ["rule", "قاعدة", "Rule"],
  ["like", "بيحب", "Likes"],
  ["dislike", "بيكره", "Dislikes"],
];

/** A thing the client likes, dislikes or insists on. The words are masked by the server for whoever may not know the client. */
export interface Requirement {
  id: number;
  kind: Labelled;
  author: string | null;
  text: string;
  /** The day it was written, when the page shows it (the client page does, the task page does not). */
  at?: { ar: string; en: string } | null;
}

/** What the form needs of the action it adds with: the mutation of either page fits. */
export interface AddsRequirement {
  mutate: (
    values: { kind: string; text: string },
    options: { onSuccess: () => void; onError: (error: unknown) => void },
  ) => void;
  isPending: boolean;
}

/** What the client likes, dislikes and insists on, read by everybody on the job - and the form that adds one. */
export function Requirements({ requirements, add }: { requirements: Requirement[]; add: AddsRequirement | null }) {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const [kind, setKind] = useState("rule");
  const [text, setText] = useState("");
  const [problem, setProblem] = useState("");

  return (
    <>
      {requirements.map((requirement) => (
        <div className={`note${requirement.kind.value === "dislike" ? " note--high" : ""}`} key={requirement.id}>
          <Icon name={REQUIREMENT_ICON[requirement.kind.value] ?? "pin"} />
          <div>
            <div className="note__where">
              {lang === "ar" ? requirement.kind.ar : requirement.kind.en} · {requirement.author ?? "—"}
              {requirement.at ? ` · ${lang === "ar" ? requirement.at.ar : requirement.at.en}` : ""}
            </div>
            <div>{requirement.text}</div>
          </div>
        </div>
      ))}
      {requirements.length === 0 && <div className="muted">{t("مفيش متطلبات مسجلة لحد دلوقتي.", "No requirements recorded yet.")}</div>}

      {add && (
        <form
          className="mt"
          onSubmit={(event) => {
            event.preventDefault();
            if (!text.trim() || add.isPending) return;
            setProblem("");
            add.mutate(
              { kind, text: text.trim() },
              {
                onSuccess: () => {
                  setText("");
                  push({ level: "success", title: t("المتطلب اتضاف", "Requirement added") });
                },
                onError: (error) => setProblem(taskProblem(error, t)),
              },
            );
          }}
        >
          <div className="field">
            <select className="input" value={kind} aria-label={t("النوع", "Kind")} onChange={(event) => setKind(event.target.value)}>
              {REQUIREMENT_KINDS.map(([value, ar, en]) => (
                <option key={value} value={value}>
                  {lang === "ar" ? ar : en}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <textarea
              className="input"
              rows={2}
              maxLength={2000}
              value={text}
              aria-label={t("المتطلب", "Requirement")}
              onChange={(event) => setText(event.target.value)}
            />
          </div>
          <button className="btn btn--sm btn--block" type="submit" disabled={!text.trim() || add.isPending}>
            <Icon name="plus" size="sm" />
            <span>{t("ضيف متطلب", "Add requirement")}</span>
          </button>
          {problem && (
            <div className="note note--high mt" role="alert">
              <Icon name="alert" />
              <div>{problem}</div>
            </div>
          )}
        </form>
      )}
    </>
  );
}
