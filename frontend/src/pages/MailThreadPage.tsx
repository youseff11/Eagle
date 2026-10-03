import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type RefObject } from "react";
import { Link, Navigate, useParams, useSearchParams } from "react-router";
import { ApiError } from "../api/client";
import { useConfirmReceipt, useMarkThreadSeen, useReply } from "../api/mailActions";
import { useMailThread, useMe } from "../api/queries";
import type { MailEntry, MailLetter, MailReply } from "../api/types";
import { Confirm } from "../components/Confirm";
import { Icon } from "../components/Icon";
import { MailFiles } from "../components/MailFiles";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";
import { prettySize } from "../lib/size";
import { taskProblem } from "../lib/taskProblem";

/** The most an e-mail carries (`services.MAX_MAIL_BYTES`): the server refuses more, this only says so before the upload. */
const MAX_MAIL_BYTES = 25 * 1024 * 1024;

const keyOf = (entry: MailEntry) => `${entry.kind}-${entry.id}`;

/** «تحويل لتاسك»: tick the files that are the job (nothing ticked is everything), then the task form opens with them. */
function Convert({ letter }: { letter: MailLetter }) {
  const { t } = usePreferences();
  const [picked, setPicked] = useState<number[]>(letter.documents);
  const documents = letter.files.filter((file) => letter.documents.includes(file.id));
  const params = new URLSearchParams({ message: String(letter.id) });
  // Everything ticked is what leaving it out means: the address stays short, and a file that arrives later is not missed.
  if (picked.length > 0 && picked.length < documents.length) params.set("files", picked.join(","));
  return (
    <div className="mail__convert">
      <div className="pick__label">{t("اختار الملفات اللي هتروح للتاسك:", "Pick the files that go to the task:")}</div>
      <div className="pick">
        {documents.map((file) => (
          <label key={file.id} className="pick__item">
            <input
              type="checkbox"
              checked={picked.includes(file.id)}
              onChange={() => setPicked((now) => (now.includes(file.id) ? now.filter((id) => id !== file.id) : [...now, file.id]))}
            />
            <Icon name="paperclip" size="sm" />
            <span>{file.name}</span>
          </label>
        ))}
      </div>
      <Link className="btn btn--sm btn--primary" to={`/tasks/new?${params.toString()}`}>
        <Icon name="arrow-right" size="sm" />
        <span>{t("تحويل لتاسك", "Convert to task")}</span>
      </Link>
    </div>
  );
}

function ConfirmButton({ thread, letter }: { thread: number; letter: MailLetter }) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const confirm = useConfirmReceipt(thread);
  const [asking, setAsking] = useState(false);
  const [problem, setProblem] = useState("");
  return (
    <>
      <button
        className="btn btn--sm btn--accent"
        type="button"
        onClick={() => {
          setProblem("");
          setAsking(true);
        }}
      >
        <Icon name="check" size="sm" />
        <span>{t("استلمت", "Received")}</span>
      </button>
      {asking && (
        <Confirm
          title={t("تأكيد الاستلام؟", "Confirm receipt?")}
          icon="check"
          body={t(
            "هيتبعت للعميل رد فيه كلمة confirmed. تمام؟",
            "The client will receive a reply saying confirmed. Go ahead?",
          )}
          yes={t("ابعت", "Send")}
          busy={confirm.isPending}
          problem={problem}
          onNo={() => setAsking(false)}
          onYes={() =>
            confirm.mutate(letter.id, {
              onSuccess: () => {
                setAsking(false);
                push({ level: "success", title: t("اتبعت للعميل إنها وصلت", "The client was told it arrived") });
              },
              onError: (error) => setProblem(taskProblem(error, t)),
            })
          }
        />
      )}
    </>
  );
}

/** One letter of the client's. */
function Letter({
  letter,
  thread,
  open,
  fresh,
  onToggle,
}: {
  letter: MailLetter;
  thread: number;
  open: boolean;
  fresh: boolean;
  onToggle: () => void;
}) {
  const { t } = usePreferences();
  const classes = ["mail", "mail--letter"];
  if (fresh) classes.push("is-unread");
  if (letter.blocked) classes.push("is-blocked");
  if (open) classes.push("is-open");
  return (
    <article className={classes.join(" ")} data-message={letter.id}>
      <button className="mail__row" type="button" onClick={onToggle} aria-expanded={open} title={t("افتح الميل", "Open the e-mail")}>
        <span className="avatar avatar--brand mail__avatar">
          {letter.code ? letter.code.slice(3) : <Icon name="mail" size="sm" />}
        </span>
        <span className="mail__body">
          <span className="mail__top">
            <b className="mail__from">{letter.from || t("مرسل غير معروف", "Unknown sender")}</b>
            {letter.at && <span className="mail__time mono">{t(letter.at.ar, letter.at.en)}</span>}
          </span>
          {/* Only a preview of a folded letter: once it is open the whole letter is below. */}
          {!open && <span className="mail__snippet">{letter.snippet}</span>}
          <span className="mail__tags">
            {letter.blocked && (
              <span className="badge badge--dead">
                <i className="badge__dot" />
                <span>{t("محجوبة — سعر", "Hidden — rate")}</span>
              </span>
            )}
            {letter.task && <span className="badge badge--ok mono">{letter.task}</span>}
            {letter.files.length > 0 && (
              <span className="chip chip--sm">
                <Icon name="paperclip" size="sm" />
                {letter.files.length}
              </span>
            )}
            {letter.claimed_by && (
              <span className="chip chip--sm">
                <Icon name="user-check" size="sm" />
                {letter.claimed_by}
              </span>
            )}
          </span>
        </span>
        <span className="mail__chev">
          <Icon name="chevron-down" size="sm" />
        </span>
      </button>

      {open && (
        <div className="mail__open">
          <div className="mail__text" dir="auto">
            {letter.body}
          </div>
          <MailFiles files={letter.files} />
          {letter.raw && <div className="muted mono mail__raw">{letter.raw}</div>}
          {(letter.can_confirm || letter.claimed_by) && (
            <div className="mail__actions">
              {letter.can_confirm && !letter.claimed_by && <ConfirmButton thread={thread} letter={letter} />}
              {letter.claimed_by && (
                <span className="badge badge--ok">
                  <Icon name="user-check" size="sm" />
                  <span>{t("استلمها", "Claimed by")}</span> {letter.claimed_by}
                </span>
              )}
            </div>
          )}
          {letter.can_convert && <Convert letter={letter} />}
        </div>
      )}
    </article>
  );
}

/** One of our own replies, with the reason when it did not go: a failed send stays on the page. */
function Reply({ reply, open, onToggle }: { reply: MailReply; open: boolean; onToggle: () => void }) {
  const { t } = usePreferences();
  const classes = ["mail", "mail--letter", "mail--ours"];
  if (open) classes.push("is-open");
  if (reply.failed) classes.push("is-failed");
  return (
    <article className={classes.join(" ")} data-reply={reply.id}>
      <button className="mail__row" type="button" onClick={onToggle} aria-expanded={open} title={t("افتح الرد", "Open the reply")}>
        <span className="avatar mail__avatar mail__avatar--ours">
          <Icon name="reply" size="sm" />
        </span>
        <span className="mail__body">
          <span className="mail__top">
            <b className="mail__from">
              {t("ردّنا", "Our reply")}
              {reply.by ? ` · ${reply.by}` : ""}
            </b>
            {reply.at && <span className="mail__time mono">{t(reply.at.ar, reply.at.en)}</span>}
          </span>
          {!open && <span className="mail__snippet">{reply.body ? reply.body.slice(0, 120) : t("(ملفات بس)", "(files only)")}</span>}
          <span className="mail__tags">
            {reply.failed && (
              <span className="badge badge--dead">
                <i className="badge__dot" />
                <span>{t("متبعتش", "Not sent")}</span>
              </span>
            )}
            {reply.files.length > 0 && (
              <span className="chip chip--sm">
                <Icon name="paperclip" size="sm" />
                {reply.files.length}
              </span>
            )}
          </span>
        </span>
        <span className="mail__chev">
          <Icon name="chevron-down" size="sm" />
        </span>
      </button>
      {open && (
        <div className="mail__open">
          {reply.body && (
            <div className="mail__text" dir="auto">
              {reply.body}
            </div>
          )}
          <MailFiles files={reply.files} />
          {reply.failed && reply.error && (
            <div className="note note--high mt" role="alert">
              <Icon name="alert" />
              <div>{reply.error}</div>
            </div>
          )}
        </div>
      )}
    </article>
  );
}

/** Gmail's reply box: it goes to the client by e-mail, inside their own conversation. */
function ReplyBox({ id, client, boxRef }: { id: number; client: string; boxRef: RefObject<HTMLFormElement | null> }) {
  const { t } = usePreferences();
  const reply = useReply(id);
  const [body, setBody] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [problem, setProblem] = useState("");
  const pick = useRef<HTMLInputElement>(null);

  const send = () => {
    if (reply.isPending) return;
    if (!body.trim() && files.length === 0) {
      setProblem(t("اكتب رد أو ارفق ملف.", "Write a reply or attach a file."));
      return;
    }
    if (files.reduce((sum, file) => sum + file.size, 0) > MAX_MAIL_BYTES) {
      setProblem(t("الملفات مع بعض أكبر من 25 ميجا — الإيميل مش هيقبلها.", "The files together are over 25 MB - e-mail will not take them."));
      return;
    }
    setProblem("");
    reply.mutate(
      { body, files },
      {
        onSuccess: () => {
          setBody("");
          setFiles([]);
        },
        // The server answers a refusal with its reason in `error` (a sentence in Arabic that never quotes the address).
        onError: (error) => {
          const said = error instanceof ApiError ? (error.payload as { error?: string } | null)?.error : "";
          setProblem(said || taskProblem(error, t));
        },
      },
    );
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    send();
  };
  const onKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      send();
    }
  };

  return (
    <form className={`card mail-reply${reply.isPending ? " is-sending" : ""}`} ref={boxRef} autoComplete="off" onSubmit={submit}>
      <div className="mail-reply__head">
        <Icon name="reply" size="sm" />
        <span>{t("رد على", "Reply to")}</span>
        <b>{client}</b>
      </div>
      <textarea
        className="input mail-reply__body"
        rows={5}
        dir="auto"
        value={body}
        onChange={(event) => setBody(event.target.value)}
        onKeyDown={onKey}
        placeholder={t("اكتب ردك هنا…", "Write your reply…")}
        aria-label={t("الرد", "Reply")}
      />
      <div className="files mail-reply__files">
        {files.map((file, index) => (
          <span key={`${file.name}-${index}`} className="file-pill">
            <Icon name="paperclip" size="sm" />
            {file.name} <small>{prettySize(file.size)}</small>
            <button
              type="button"
              className="file-pill__x"
              aria-label={t("شيل الملف", "Remove the file") + `: ${file.name}`}
              onClick={() => setFiles((now) => now.filter((_, at) => at !== index))}
            >
              <Icon name="x" size="sm" />
            </button>
          </span>
        ))}
      </div>
      {problem && (
        <div className="note note--high mt" role="alert">
          <Icon name="alert" />
          <div>{problem}</div>
        </div>
      )}
      <div className="mail-reply__bar">
        <button className="btn btn--sm mail-reply__attach" type="button" onClick={() => pick.current?.click()}>
          <Icon name="paperclip" size="sm" />
          <span>{t("ارفق ملفات", "Attach files")}</span>
        </button>
        <input
          ref={pick}
          type="file"
          multiple
          hidden
          data-testid="mail-reply-pick"
          onChange={(event) => {
            const chosen = Array.from(event.target.files ?? []);
            if (chosen.length > 0) setFiles((now) => [...now, ...chosen]);
            // The same file chosen again must still fire a change.
            event.target.value = "";
          }}
        />
        <span className="muted mail-reply__hint">{t("لحد 25 ميجا · Ctrl+Enter يبعت", "Up to 25 MB · Ctrl+Enter sends")}</span>
        <div className="grow" />
        <button className="btn btn--primary" type="submit" disabled={reply.isPending}>
          <Icon name="send" size="sm" />
          <span>{t("ابعت", "Send")}</span>
        </button>
      </div>
    </form>
  );
}

/** One conversation, every letter and every reply of ours in it, oldest at the top - Gmail's open view. */
export function MailThreadPage() {
  const { t } = usePreferences();
  const me = useMe();
  const { id: raw } = useParams();
  const [params] = useSearchParams();
  const id = /^\d{1,12}$/.test(raw ?? "") ? Number(raw) : 0;
  const role = me.data?.user.role;
  const allowed = me.data !== undefined && (role === "operation" || role === "sales" || me.data.user.is_admin);
  const query = useMailThread(id, allowed && id > 0);
  const seen = useMarkThreadSeen(id);
  const boxRef = useRef<HTMLFormElement | null>(null);

  // What the person opened, and which letters were new to them: kept here because the answer asks again on a clock,
  // and a letter being read must not fold up (or lose its mark) under them. A letter seen for the first time starts as
  // the server says (the newest one, and the one a link named).
  const [opened, setOpened] = useState<Record<string, boolean>>({});
  const [fresh, setFresh] = useState<Record<string, boolean>>({});
  const entries = query.data?.thread.entries;
  useEffect(() => {
    if (!entries) return;
    setOpened((now) => {
      const next = { ...now };
      for (const entry of entries) if (!(keyOf(entry) in next)) next[keyOf(entry)] = entry.open;
      return next;
    });
    setFresh((now) => {
      const next = { ...now };
      for (const entry of entries) if (entry.kind === "in" && !(keyOf(entry) in next)) next[keyOf(entry)] = entry.unseen;
      return next;
    });
  }, [entries]);

  // The letters are on the page: say so once for whatever is new, and the badge falls (a GET does not do it).
  const anyUnseen = entries?.some((entry) => entry.kind === "in" && entry.unseen) ?? false;
  const markRead = seen.mutate;
  useEffect(() => {
    if (anyUnseen) markRead();
  }, [anyUnseen, entries?.length, markRead]);

  if (id === 0 || (me.data && !allowed)) return <Navigate to={id === 0 ? "/inbox" : "/"} replace />;

  // Back to the list as the person left it: the filters came along in the address.
  const back = new URLSearchParams();
  for (const name of ["state", "q"]) {
    const value = params.get(name);
    if (value) back.set(name, value);
  }
  const backTo = `/inbox${back.toString() ? `?${back.toString()}` : ""}`;

  const thread = query.data?.thread;
  const notFound = query.error instanceof ApiError && query.error.status === 404;
  const setAll = (value: boolean) =>
    setOpened(Object.fromEntries((entries ?? []).map((entry) => [keyOf(entry), value])));

  return (
    <>
      <div className="page-head thread-head">
        <Link className="btn btn--sm thread-head__back" to={backTo} title={t("رجوع للميلات", "Back to the mail")}>
          <Icon name="arrow-right" size="sm" />
          <span>{t("الميلات", "Mail")}</span>
        </Link>
        <h1 className="thread-head__subject">{thread ? thread.subject || t("(من غير عنوان)", "(no subject)") : ""}</h1>
        {thread && (
          <span className="badge badge--new mono" title={t("عدد الميلات في المحادثة", "Letters in this conversation")}>
            {thread.count}
          </span>
        )}
        <div className="grow" />
        {thread && thread.count > 1 && (
          <button className="btn btn--sm" type="button" onClick={() => setAll(true)}>
            <Icon name="chevron-down" size="sm" />
            <span>{t("افتح الكل", "Expand all")}</span>
          </button>
        )}
        {thread?.can_reply && (
          <button className="btn btn--sm btn--primary" type="button" onClick={() => boxRef.current?.scrollIntoView?.({ behavior: "smooth" })}>
            <Icon name="reply" size="sm" />
            <span>{t("رد", "Reply")}</span>
          </button>
        )}
      </div>

      {thread && (
        <div className="thread-meta">
          {thread.client && (
            <span className="chip">
              <Icon name="user" size="sm" />
              {thread.client}
            </span>
          )}
          {thread.tasks.map((code) => (
            <Link key={code} className="badge badge--ok mono" to={`/tasks/${encodeURIComponent(code)}`}>
              {code}
            </Link>
          ))}
          {thread.blocked && (
            <span className="badge badge--dead">
              <i className="badge__dot" />
              <span>{t("فيها ميلات محجوبة — سعر", "Has hidden letters — rate")}</span>
            </span>
          )}
        </div>
      )}

      {thread ? (
        <>
          <div className="mail-list mail-thread" id="threadList">
            {thread.entries.map((entry) =>
              entry.kind === "out" ? (
                <Reply
                  key={keyOf(entry)}
                  reply={entry}
                  open={opened[keyOf(entry)] ?? entry.open}
                  onToggle={() => setOpened((now) => ({ ...now, [keyOf(entry)]: !(now[keyOf(entry)] ?? entry.open) }))}
                />
              ) : (
                <Letter
                  key={keyOf(entry)}
                  letter={entry}
                  thread={id}
                  open={opened[keyOf(entry)] ?? entry.open}
                  fresh={fresh[keyOf(entry)] ?? entry.unseen}
                  onToggle={() => setOpened((now) => ({ ...now, [keyOf(entry)]: !(now[keyOf(entry)] ?? entry.open) }))}
                />
              ),
            )}
          </div>

          {thread.can_reply && thread.client ? (
            <ReplyBox id={id} client={thread.client} boxRef={boxRef} />
          ) : (
            <div className="note note--warn mt">
              <Icon name="alert" />
              <div>
                {t(
                  "المحادثة دي مش مربوطة بعميل، فمينفعش ترد عليها من هنا.",
                  "This conversation has no client, so it cannot be answered from here.",
                )}
              </div>
            </div>
          )}
        </>
      ) : notFound ? (
        <div className="card empty" role="alert">
          <Icon name="mail" size="xl" />
          <span>{t("المحادثة دي مش موجودة.", "That conversation does not exist.")}</span>
        </div>
      ) : query.isError ? (
        <div className="card empty" role="alert">
          <Icon name="alert" size="xl" />
          <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
        </div>
      ) : (
        <div className="card empty">
          <Icon name="refresh" size="xl" />
          <span>{t("بيحمّل...", "Loading...")}</span>
        </div>
      )}
    </>
  );
}
