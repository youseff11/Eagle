import { useRef, useState, type DragEvent } from "react";
import { Navigate } from "react-router";
import { useAiReviewDelete, useAiReviewSend } from "../api/aiReview";
import { useAiReviewBoard, useAiReviewCheck, useMe } from "../api/queries";
import type { AiReviewRow } from "../api/types";
import { Issue } from "../components/ai/AiNotesCard";
import { Icon } from "../components/Icon";
import { Loading } from "../components/Loading";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";
import { taskProblem } from "../lib/taskProblem";

/** What the server can read: Word and text it turns into words, PDFs and pictures the model reads itself (`doc_review`). */
const ACCEPT = ".docx,.txt,.md,.csv,.tsv,.json,.srt,.vtt,.html,.htm,.pdf,.png,.jpg,.jpeg,.webp,.gif";

function size(bytes: number) {
  return bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** One side of the request: a box to drop files on or pick them, and the list of what is in it. */
function Side({
  name,
  title,
  hint,
  files,
  max,
  megabytes,
  disabled,
  onChange,
}: {
  name: "source" | "target";
  title: string;
  hint: string;
  files: File[];
  max: number;
  megabytes: number;
  disabled: boolean;
  onChange: (files: File[]) => void;
}) {
  const { t } = usePreferences();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [note, setNote] = useState("");

  const add = (incoming: File[]) => {
    const fits = incoming.filter((file) => file.size <= megabytes * 1024 * 1024);
    const merged = [...files, ...fits].slice(0, max);
    const tooBig = incoming.length - fits.length;
    setNote(
      tooBig > 0
        ? t(`فيه ${tooBig} ملف أكبر من ${megabytes} ميجا ومااتضافش.`, `${tooBig} file(s) over ${megabytes} MB were not added.`)
        : files.length + fits.length > max
          ? t(`أقصى عدد ${max} ملفات.`, `At most ${max} files.`)
          : "",
    );
    onChange(merged);
  };
  const drop = (event: DragEvent) => {
    event.preventDefault();
    setOver(false);
    if (!disabled) add(Array.from(event.dataTransfer.files));
  };

  return (
    <div
      className={`aireview-side${over ? " is-over" : ""}`}
      data-side={name}
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={drop}
    >
      <div className="aireview-side__head">
        <strong>{title}</strong>
        <span className="muted">{hint}</span>
      </div>
      <input
        ref={input}
        type="file"
        multiple
        hidden
        accept={ACCEPT}
        data-input={name}
        aria-label={title}
        disabled={disabled}
        onChange={(event) => {
          add(Array.from(event.target.files ?? []));
          // The same file may be chosen again after it was taken off.
          event.target.value = "";
        }}
      />
      <button className="btn btn--sm" type="button" disabled={disabled || files.length >= max} onClick={() => input.current?.click()}>
        <Icon name="paperclip" size="sm" />
        <span>{files.length ? t("ضيف ملفات", "Add files") : t("اختار ملفات", "Choose files")}</span>
      </button>
      <span className="muted aireview-side__drop">{t("أو اسحب الملفات هنا", "or drop files here")}</span>
      {note && <div className="note note--warn">{note}</div>}
      {files.length > 0 && (
        <ul className="aireview-files">
          {files.map((file, index) => (
            <li key={`${file.name}-${index}`}>
              <Icon name="file" size="sm" />
              <span className="aireview-files__name" dir="auto">
                {file.name}
              </span>
              <small className="muted mono">{size(file.size)}</small>
              <button
                className="btn btn--ghost btn--sm"
                type="button"
                aria-label={t(`شيل ${file.name}`, `Remove ${file.name}`)}
                disabled={disabled}
                onClick={() => onChange(files.filter((_, at) => at !== index))}
              >
                <Icon name="x" size="sm" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function StatusBadge({ status, count }: { status: AiReviewRow["status"]; count: number }) {
  const { t } = usePreferences();
  if (status === "issues") {
    return (
      <span className="badge badge--dead">
        <span className="mono">{count}</span> <span>{t("ملاحظة", "note(s)")}</span>
      </span>
    );
  }
  if (status === "clean") return <span className="badge badge--ok">{t("مفيش أخطاء واضحة", "Nothing obvious")}</span>;
  if (status === "running") return <span className="badge badge--wait">{t("شغال دلوقتي", "Running")}</span>;
  return <span className="badge badge--dead">{t("مخلصش", "Did not finish")}</span>;
}

/** The names of the files of a check, shortened to the first and how many more. */
function Names({ names }: { names: string[] }) {
  const { t } = usePreferences();
  if (names.length === 0) return <span className="muted">—</span>;
  return (
    <span dir="auto">
      {names[0]}
      {names.length > 1 && <span className="muted"> {t(`+${names.length - 1} كمان`, `+${names.length - 1} more`)}</span>}
    </span>
  );
}

/** One check opened: what was sent, the verdict, and the notes. Suggestions only; nothing here changes anybody's work. */
function Detail({ id, onClose }: { id: number; onClose: () => void }) {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const query = useAiReviewCheck(id);
  const remove = useAiReviewDelete();
  const data = query.data;
  if (!data) {
    return (
      <div className="card">
        {query.isError ? (
          <div className="empty" role="alert">
            <Icon name="alert" size="xl" />
            <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
          </div>
        ) : (
          <Loading className="empty" />
        )}
      </div>
    );
  }
  const { check, issues } = data;
  return (
    <div className={`card ai-notes ai-notes--${check.status}`} data-review={check.id}>
      <div className="card__head">
        <Icon name="sparkles" />
        <h2>{t("نتيجة المراجعة", "Review result")}</h2>
        <div className="grow" />
        <StatusBadge status={check.status} count={check.count} />
        <span className="muted mono ai-notes__when">{check.at ? (lang === "en" ? check.at.en : check.at.ar) : ""}</span>
      </div>

      <dl className="aireview-sent">
        <div>
          <dt>{t("الأصل", "Source")}</dt>
          <dd>{check.source_names.length ? check.source_names.join(" · ") : t("مفيش (اتراجعت الترجمة لوحدها)", "none (the translation alone was checked)")}</dd>
        </div>
        <div>
          <dt>{t("الترجمة", "Translation")}</dt>
          <dd>{check.target_names.join(" · ")}</dd>
        </div>
        {(check.source_lang || check.target_lang) && (
          <div>
            <dt>{t("اللغات", "Languages")}</dt>
            <dd dir="auto">
              {check.source_lang || "?"} → {check.target_lang || "?"}
            </dd>
          </div>
        )}
        {check.instructions && (
          <div>
            <dt>{t("ملاحظاتك للـAI", "Your notes")}</dt>
            <dd dir="auto" style={{ whiteSpace: "pre-line" }}>
              {check.instructions}
            </dd>
          </div>
        )}
      </dl>

      {check.skipped.length > 0 && (
        <div className="note note--warn">
          <Icon name="info" />
          <div>
            {t("الـAI ماقراش الملفات دي (نوعها مش مقروء أو زيادة عن الحد):", "The AI did not read these files (an unreadable kind, or past the limit):")}{" "}
            <span dir="auto">{check.skipped.join(" · ")}</span>
          </div>
        </div>
      )}

      {check.status === "running" ? (
        <div className="note note--info">
          <Icon name="timer" />
          <div>{t("الـAI بيقرا الملفات دلوقتي. الصفحة هتتحدث لوحدها أول ما يخلص.", "The AI is reading the files now. This page updates itself when it is done.")}</div>
        </div>
      ) : check.status === "error" ? (
        <div className="note note--high">
          <Icon name="alert" />
          <div>
            <strong>{t("المراجعة مخلصتش — ابعت الملفات تاني.", "The review did not finish - send the files again.")}</strong>
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
          {issues.length > 0 ? (
            <ol className="ai-issues">
              {issues.map((issue, index) => (
                <Issue key={index} issue={issue} index={index} />
              ))}
            </ol>
          ) : (
            check.status === "clean" && (
              <div className="note note--ok">
                <Icon name="check-circle" />
                <div>{t("الـAI مالقاش أخطاء واضحة. المراجعة البشرية لسه مطلوبة.", "The AI found nothing obvious. Your own review still stands.")}</div>
              </div>
            )
          )}
          <p className="muted ai-notes__foot">{t("دي اقتراحات بس، والقرار ليك. الـAI مابيعدّلش الترجمة.", "Suggestions only; the decision is yours. The AI never edits the translation.")}</p>
        </>
      )}

      <div className="row row--tight">
        <button className="btn btn--ghost btn--sm" type="button" onClick={onClose}>
          {t("قفل", "Close")}
        </button>
        <div className="grow" />
        {check.status !== "running" && (
          <button
            className="btn btn--sm btn--danger"
            type="button"
            disabled={remove.isPending}
            onClick={() =>
              remove.mutate(check.id, {
                onSuccess: () => {
                  onClose();
                  push({ level: "info", title: t("اتمسحت.", "Removed.") });
                },
              })
            }
          >
            <Icon name="trash" size="sm" />
            <span>{t("امسح النتيجة", "Remove this result")}</span>
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * «مراجعة بالـAI»: the team leader sends the source and the translation - one file or several of each - straight to the AI and reads its
 * notes here, with no task behind them. Advisory only: it never rewrites anything, and nobody's stars ride on it. The files are read once
 * and not kept; only their names stay in the list.
 */
export function AiReviewPage() {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const me = useMe();
  const allowed = me.data !== undefined && (me.data.user.role === "team_lead" || me.data.user.is_admin);
  const board = useAiReviewBoard(allowed);
  const send = useAiReviewSend();
  const [source, setSource] = useState<File[]>([]);
  const [target, setTarget] = useState<File[]>([]);
  const [sourceLang, setSourceLang] = useState("");
  const [targetLang, setTargetLang] = useState("");
  const [instructions, setInstructions] = useState("");
  const [problem, setProblem] = useState("");
  const [opened, setOpened] = useState<number | null>(null);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  const data = board.data;
  const blocked = !data || !data.available || data.running;

  const submit = () => {
    setProblem("");
    send.mutate(
      { source, target, sourceLang, targetLang, instructions },
      {
        onSuccess: (answer) => {
          setSource([]);
          setTarget([]);
          setInstructions("");
          setOpened(answer.id);
          push({ level: "info", title: t("الملفات اتبعتت. النتيجة هتظهر هنا أول ما الـAI يخلص.", "Files sent. The result appears here when the AI is done.") });
        },
        onError: (failure) => setProblem(taskProblem(failure, t)),
      },
    );
  };

  return (
    <>
      <div className="page-head">
        <h1>{t("مراجعة بالـAI", "AI review")}</h1>
        <span className="page-head__sub">
          {t("ابعت الأصل والترجمة والـAI يراجعهم. مش لازم تاسك.", "Send the source and the translation for the AI to check. No task needed.")}
        </span>
      </div>

      {!data ? (
        <div className="card">
          {board.isError ? (
            <div className="empty" role="alert">
              <Icon name="alert" size="xl" />
              <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
            </div>
          ) : (
            <Loading className="empty" />
          )}
        </div>
      ) : (
        <>
          <div className="card" data-card="send">
            <div className="card__head">
              <Icon name="sparkles" />
              <h3>{t("ابعت مستندات للمراجعة", "Send documents for review")}</h3>
            </div>
            {!data.available && (
              <div className="note note--warn" role="status">
                <Icon name="info" />
                <div>{t("فحص الـAI مقفول. الأدمن يفتحه من الإعدادات (ومفتاح Claude لازم يبقى محفوظ).", "The AI check is off. The admin turns it on in the settings (and a Claude key must be saved).")}</div>
              </div>
            )}
            {data.available && data.running && (
              <div className="note note--info" role="status">
                <Icon name="timer" />
                <div>{t("فيه مراجعة شغالة دلوقتي. استنى لما تخلص عشان تبعت غيرها.", "A review is running now. Wait for it to finish before sending another.")}</div>
              </div>
            )}
            <div className="aireview-sides">
              <Side
                name="source"
                title={t("الملف الأصلي", "Source")}
                hint={t("اختياري، بس من غيره الـAI مش هيقارن", "Optional, but without it the AI cannot compare")}
                files={source}
                max={data.limits.files}
                megabytes={data.limits.megabytes}
                disabled={blocked}
                onChange={setSource}
              />
              <Side
                name="target"
                title={t("الترجمة", "Translation")}
                hint={t("اللي الـAI هيراجعه", "What the AI will check")}
                files={target}
                max={data.limits.files}
                megabytes={data.limits.megabytes}
                disabled={blocked}
                onChange={setTarget}
              />
            </div>
            <p className="muted aireview-limits">
              {t(
                `Word وPDF وصور ونصوص. لحد ${data.limits.files} ملفات في كل جنب، والملف لحد ${data.limits.megabytes} ميجا.`,
                `Word, PDF, pictures and text. Up to ${data.limits.files} files a side, ${data.limits.megabytes} MB each.`,
              )}
            </p>
            <div className="form-grid">
              <div className="field">
                <label htmlFor="aireview-from">{t("من لغة", "From language")}</label>
                <input id="aireview-from" className="input" maxLength={60} value={sourceLang} disabled={blocked} onChange={(event) => setSourceLang(event.target.value)} placeholder={t("اختياري", "Optional")} />
              </div>
              <div className="field">
                <label htmlFor="aireview-to">{t("إلى لغة", "To language")}</label>
                <input id="aireview-to" className="input" maxLength={60} value={targetLang} disabled={blocked} onChange={(event) => setTargetLang(event.target.value)} placeholder={t("اختياري", "Optional")} />
              </div>
            </div>
            <div className="field">
              <label htmlFor="aireview-notes">{t("عايز الـAI يركّز على إيه؟", "What should the AI look at?")}</label>
              <textarea
                id="aireview-notes"
                className="input"
                rows={3}
                maxLength={2000}
                value={instructions}
                disabled={blocked}
                onChange={(event) => setInstructions(event.target.value)}
                placeholder={t("اختياري. مثلًا: ركّز على الأرقام والأسماء، أو المصطلحات القانونية.", "Optional. For example: focus on numbers and names, or the legal terms.")}
              />
            </div>
            {problem && (
              <div className="note note--high" role="alert">
                <Icon name="alert" />
                <div>{problem}</div>
              </div>
            )}
            <div className="row row--tight">
              <button className="btn btn--primary" type="button" disabled={blocked || target.length === 0 || send.isPending} onClick={submit}>
                <Icon name="sparkles" size="sm" />
                <span>{t("ابعت للـAI", "Send to the AI")}</span>
              </button>
              {target.length === 0 && <span className="muted">{t("ارفع ملف الترجمة الأول.", "Add the translation file first.")}</span>}
            </div>
          </div>

          {opened !== null && <Detail key={opened} id={opened} onClose={() => setOpened(null)} />}

          <div className="card" data-card="history">
            <div className="card__head">
              <Icon name="list-checks" />
              <h3>{t("مراجعاتي", "My reviews")}</h3>
            </div>
            {data.checks.length === 0 ? (
              <div className="empty">
                <Icon name="archive" size="xl" />
                <span>{t("لسه ماراجعتش حاجة.", "Nothing reviewed yet.")}</span>
              </div>
            ) : (
              <ul className="aireview-history">
                {data.checks.map((row) => (
                  <li key={row.id} data-review-row={row.id}>
                    <button className={`aireview-history__row${opened === row.id ? " is-open" : ""}`} type="button" onClick={() => setOpened(opened === row.id ? null : row.id)}>
                      <span className="aireview-history__files">
                        <Names names={row.target_names} />
                        <small className="muted">
                          {t("الأصل:", "Source:")} <Names names={row.source_names} />
                        </small>
                      </span>
                      <StatusBadge status={row.status} count={row.count} />
                      <small className="muted mono">{row.at ? (lang === "en" ? row.at.en : row.at.ar) : ""}</small>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </>
  );
}
