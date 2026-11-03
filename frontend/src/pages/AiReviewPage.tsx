import { useEffect, useRef, useState } from "react";
import { Navigate, useSearchParams } from "react-router";
import { useAiReviewDelete, useAiReviewRetry, useAiReviewSend } from "../api/aiReview";
import { ApiError } from "../api/client";
import { useAiReviewBoard, useAiReviewSession, useMe } from "../api/queries";
import type { AiReviewLine, AiReviewSession } from "../api/types";
import { ReviewComposer, type PendingFile } from "../components/ai/ReviewComposer";
import { Icon } from "../components/Icon";
import { Loading } from "../components/Loading";
import { usePreferences } from "../i18n/Preferences";
import { safeInternalPath } from "../lib/safeUrl";
import { taskProblem } from "../lib/taskProblem";

/** Starting points for a first message: they fill the box, the leader edits and sends. */
const SUGGESTIONS: [string, string][] = [
  ["راجع الترجمة على الأصل وطلّعلي كل الأخطاء.", "Review the translation against the source and list every mistake."],
  ["دوّر على الأرقام والتواريخ والأسماء بس.", "Check only the numbers, dates and names."],
  ["قيّم جودة الترجمة وقولي أهم 3 حاجات تتصلح.", "Rate the translation and tell me the 3 most important things to fix."],
];

function Attached({ file }: { file: AiReviewLine["files"][number] }) {
  const { t } = usePreferences();
  const href = safeInternalPath(file.url);
  const label = file.label === "source" ? t("أصل", "Source") : file.label === "translation" ? t("ترجمة", "Translation") : "";
  const body = (
    <>
      <Icon name="paperclip" size="sm" />
      <span dir="auto">{file.name}</span>
      {label && <small className="muted">· {label}</small>}
    </>
  );
  return href ? (
    <a className="file-pill" href={href} target="_blank" rel="noopener noreferrer" title={file.size}>
      {body}
    </a>
  ) : (
    <span className="file-pill">{body}</span>
  );
}

/** One line of the talk: the leader's on one side, the AI's on the other, with its writing and failed states. */
function Line({ line, canRetry, retrying, onRetry }: { line: AiReviewLine; canRetry: boolean; retrying: boolean; onRetry: () => void }) {
  const { t, lang } = usePreferences();
  const mine = line.role === "user";
  const at = line.at ? (lang === "en" ? line.at.en : line.at.ar) : "";
  return (
    <div className={`revchat__line ${mine ? "revchat__line--me" : "revchat__line--ai"}`} data-line={line.role}>
      {!mine && (
        <span className="revchat__who">
          <Icon name="sparkles" size="sm" /> {t("الـAI", "AI")}
        </span>
      )}
      {line.status === "pending" && (
        <span className="muted revchat__writing" role="status">
          <Icon name="timer" size="sm" /> {t("الـAI بيقرا ويكتب الرد... ممكن ياخد كام دقيقة مع الملفات الكبيرة.", "The AI is reading and writing... large files can take a few minutes.")}
        </span>
      )}
      {line.status === "error" && (
        <span className="revchat__error" role="alert">
          <Icon name="alert" size="sm" /> {t("الـAI مردّش.", "The AI did not answer.")}
          {canRetry && (
            <button className="btn btn--sm" type="button" disabled={retrying} onClick={onRetry}>
              {t("جرّب تاني", "Try again")}
            </button>
          )}
        </span>
      )}
      {line.files.length > 0 && (
        <div className="revchat__files">
          {line.files.map((file) => (
            <Attached key={file.id} file={file} />
          ))}
        </div>
      )}
      {line.body && (
        <div className="revchat__text" dir="auto">
          {line.body}
        </div>
      )}
      {line.status !== "pending" && at && <small className="muted mono">{at}</small>}
    </div>
  );
}

/** The sessions of the person: «جلسة جديدة», each with its title and time, and a delete that asks once. */
function Sessions({
  sessions,
  opened,
  onOpen,
  onDeleted,
}: {
  sessions: AiReviewSession[];
  opened: number | null;
  onOpen: (id: number | null) => void;
  onDeleted: (id: number) => void;
}) {
  const { t, lang } = usePreferences();
  const remove = useAiReviewDelete();
  const [asking, setAsking] = useState<number | null>(null);
  const [problem, setProblem] = useState("");

  return (
    <aside className="card revchat__sessions" data-card="sessions">
      <button className="btn btn--primary btn--sm" type="button" data-action="new-session" onClick={() => onOpen(null)}>
        <Icon name="plus" size="sm" />
        <span>{t("جلسة جديدة", "New session")}</span>
      </button>
      {problem && (
        <div className="note note--high" role="alert">
          {problem}
        </div>
      )}
      {sessions.length === 0 ? (
        <div className="muted revchat__none">{t("لسه مفيش جلسات.", "No sessions yet.")}</div>
      ) : (
        <ul className="revchat__sessions-list">
          {sessions.map((session) => (
            <li key={session.id} data-session={session.id} className={opened === session.id ? "is-open" : ""}>
              {asking === session.id ? (
                <div className="revchat__ask">
                  <span>{t("تمسح الجلسة دي بملفاتها؟", "Delete this session and its files?")}</span>
                  <button
                    className="btn btn--danger btn--sm"
                    type="button"
                    disabled={remove.isPending}
                    onClick={() =>
                      remove.mutate(session.id, {
                        onSuccess: () => {
                          setAsking(null);
                          onDeleted(session.id);
                        },
                        onError: (failure) => {
                          setAsking(null);
                          setProblem(
                            failure instanceof ApiError && failure.status === 409
                              ? t("الـAI لسه بيرد في الجلسة دي. استنى لما يخلص.", "The AI is still answering in this session. Wait for it.")
                              : taskProblem(failure, t),
                          );
                        },
                      })
                    }
                  >
                    {t("امسح", "Delete")}
                  </button>
                  <button className="btn btn--ghost btn--sm" type="button" onClick={() => setAsking(null)}>
                    {t("لأ", "No")}
                  </button>
                </div>
              ) : (
                <>
                  <button className="revchat__open" type="button" aria-current={opened === session.id} onClick={() => onOpen(session.id)}>
                    <span className="revchat__title" dir="auto">
                      {session.title || t("جلسة", "Session")}
                    </span>
                    <small className="muted">
                      {session.pending ? (
                        <>
                          <Icon name="timer" size="sm" /> {t("بيرد...", "Answering...")}
                        </>
                      ) : session.at ? (
                        lang === "en" ? session.at.en : session.at.ar
                      ) : (
                        ""
                      )}
                    </small>
                  </button>
                  <button
                    className="btn btn--ghost btn--sm"
                    type="button"
                    aria-label={t(`امسح جلسة ${session.title}`, `Delete session ${session.title}`)}
                    onClick={() => {
                      setProblem("");
                      setAsking(session.id);
                    }}
                  >
                    <Icon name="trash" size="sm" />
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}

/**
 * «مراجعة بالـAI»: a chat. The team leader opens a session, sends the source, the translation or any file, and talks to the AI about them;
 * it answers from the files and from the talk so far, and he keeps asking. Each session is its own talk, and he opens, switches and
 * deletes them from the list. The open one is in the address (`?s=`), so a notification or a reload lands on it. Advisory only: it never
 * edits anything, and nobody's stars ride on it.
 */
export function AiReviewPage() {
  const { t } = usePreferences();
  const me = useMe();
  const allowed = me.data !== undefined && (me.data.user.role === "team_lead" || me.data.user.is_admin);
  const board = useAiReviewBoard(allowed);
  const [params, setParams] = useSearchParams();
  const raw = Number(params.get("s"));
  const opened = Number.isInteger(raw) && raw > 0 ? raw : null;
  const session = useAiReviewSession(opened);
  const send = useAiReviewSend();
  const retry = useAiReviewRetry();
  const [text, setText] = useState("");
  const [files, setFiles] = useState<PendingFile[]>([]);
  const [problem, setProblem] = useState("");
  const end = useRef<HTMLDivElement>(null);

  const open = (id: number | null) => {
    setProblem("");
    setParams(id === null ? {} : { s: String(id) }, { replace: true });
  };
  const messages = session.data?.messages ?? [];
  const writing = session.data?.session.pending === true || retry.isPending;
  const lastId = messages.length ? messages[messages.length - 1]!.id : 0;

  // The newest line is in view as it comes.
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "nearest" });
  }, [lastId, writing]);
  // A session that is gone (deleted somewhere else, or not the person's) is not kept in the address.
  useEffect(() => {
    if (opened !== null && session.isError) setParams({}, { replace: true });
  }, [opened, session.isError, setParams]);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  const data = board.data;

  const submit = () => {
    setProblem("");
    send.mutate(
      { session: opened, text: text.trim(), files },
      {
        onSuccess: (answer) => {
          setText("");
          setFiles([]);
          if (answer.session.id !== opened) open(answer.session.id);
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
          {t("ابعت الأصل والترجمة واتكلم مع الـAI عليهم. كل جلسة شات لوحدها.", "Send the source and the translation and talk to the AI about them. Each session is its own chat.")}
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
        <div className="revchat">
          <Sessions
            sessions={data.sessions}
            opened={opened}
            onOpen={open}
            onDeleted={(id) => {
              if (id === opened) open(null);
            }}
          />

          <section className="card revchat__main" data-card="chat">
            <div className="card__head">
              <Icon name="sparkles" />
              <h3 dir="auto">{session.data?.session.title || (opened === null ? t("جلسة جديدة", "New session") : t("مراجعة بالـAI", "AI review"))}</h3>
            </div>
            {!data.available && (
              <div className="note note--warn" role="status">
                <Icon name="info" />
                <div>{t("فحص الـAI مقفول. الأدمن يفتحه من الإعدادات (ومفتاح Claude لازم يبقى محفوظ).", "The AI check is off. The admin turns it on in the settings (and a Claude key must be saved).")}</div>
              </div>
            )}

            <div className="revchat__log" role="log" aria-live="polite" data-box="review-log">
              {opened !== null && session.isLoading && <Loading className="empty" />}
              {opened === null && (
                <div className="revchat__empty">
                  <Icon name="sparkles" size="xl" />
                  <strong>{t("ابدأ مراجعة جديدة", "Start a new review")}</strong>
                  <span className="muted">
                    {t(
                      "ارفع الأصل والترجمة (أو أي ملف) واكتب عايز الـAI يعمل إيه. تقدر تكمّل معاه أسئلة في نفس الجلسة.",
                      "Attach the source and the translation (or any file) and say what you want. You can keep asking in the same session.",
                    )}
                  </span>
                  <div className="revchat__suggest">
                    {SUGGESTIONS.map(([ar, en]) => (
                      <button key={en} className="btn btn--sm" type="button" onClick={() => setText(t(ar, en))}>
                        {t(ar, en)}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {messages.map((line, index) => (
                <Line
                  key={line.id}
                  line={line}
                  canRetry={index === messages.length - 1}
                  retrying={retry.isPending}
                  onRetry={() => opened !== null && retry.mutate(opened, { onError: (failure) => setProblem(taskProblem(failure, t)) })}
                />
              ))}
              <div ref={end} />
            </div>

            <ReviewComposer
              text={text}
              files={files}
              limits={data.limits}
              disabled={!data.available || writing}
              sending={send.isPending}
              note={
                !data.available
                  ? ""
                  : writing
                    ? t("الـAI بيرد دلوقتي. تقدر تكتب رسالتك وتبعتها لما يخلص.", "The AI is answering. You can write your next message and send it when it is done.")
                    : ""
              }
              problem={problem}
              onText={setText}
              onFiles={setFiles}
              onSend={submit}
            />
          </section>
        </div>
      )}
    </>
  );
}
