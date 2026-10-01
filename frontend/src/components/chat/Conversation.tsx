import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { ApiError } from "../../api/client";
import { readPath, threadPath, useMarkChatRead, useMe, useThread } from "../../api/queries";
import type { ChatKind, ChatRow, ThreadEntry } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { unmatched, useOutbox, useOutboxActions, type Outgoing, type ReplyTarget } from "../../lib/outbox";
import { safeInternalPath } from "../../lib/safeUrl";
import { Icon } from "../Icon";
import { Bubble, OutgoingBubble } from "./Bubble";
import { Composer, DEFAULT_LIMITS, type Written } from "./Composer";

function Header({ row, code }: { row: ChatRow; code: string }) {
  const { t } = usePreferences();
  let meta: string;
  if (row.staff) meta = t("زميل", "Colleague");
  else if (row.group) meta = row.team ? t("جروب شغل", "Work group") : t("جروب", "Group");
  else if (row.channel === "whatsapp") meta = "WhatsApp";
  else if (row.channel === "email") meta = "Email";
  else meta = t("مفيش قناة", "No channel");

  return (
    <>
      <span className={`avatar ${row.staff ? "avatar--staff" : row.group ? "avatar--group" : "avatar--brand"}`}>
        {row.group ? <Icon name="users" size="sm" /> : row.staff ? row.initials : code.slice(3)}
      </span>
      <div>
        <div className={`cchat__who${row.staff || row.group ? "" : " mono"}`}>{row.label}</div>
        <div className="cchat__meta muted">
          {row.staff ? <Icon name="user" size="sm" /> : row.group ? <Icon name="users" size="sm" /> : <Icon name="phone" size="sm" />}
          {meta}
        </div>
      </div>
    </>
  );
}

/**
 * WhatsApp lets a free-form message go only within 24 hours of the client's last one: the notes say so, and the
 * box is off. Only for what reaches a client - a colleague's chat and a work group never do, whatever client
 * their task belongs to.
 */
export function windowClosed(row: ChatRow): boolean {
  return !row.staff && !row.team && row.channel === "whatsapp" && !row.window_open;
}

/** The notes above the messages: what a group reaches, and the WhatsApp 24-hour rule. */
function Notes({ row }: { row: ChatRow }) {
  const { t } = usePreferences();
  return (
    <>
      {row.reaches_client && (
        <div className="note note--warn cchat__window">
          <Icon name="users" />
          <div>
            <strong>{t("الجروب ده بيوصل العميل", "This group reaches the client")}</strong>
            <div>
              {t(
                "أي رسالة هنا بتروح واتساب العميل باسم دورك — مش اسمك ولا رقمك.",
                "Anything here goes to the client's WhatsApp under your role — not your name or number.",
              )}
            </div>
          </div>
        </div>
      )}
      {row.team && (
        <div className="note cchat__window">
          <Icon name="shield-check" />
          <div>
            <strong>{t("جروب شغل داخلي", "Internal work group")}</strong>
            <div>{t("مفيش حاجة هنا بتوصل العميل.", "Nothing here reaches the client.")}</div>
          </div>
        </div>
      )}
      {windowClosed(row) && (
        <div className="note note--warn cchat__window">
          <Icon name="clock" />
          <div>
            <strong>{t("نافذة الـ24 ساعة قفلت", "The 24-hour window is closed")}</strong>
            <div>
              {t(
                "واتساب مش بيسمح تبعت رسالة حرة بعد 24 ساعة من آخر رسالة للعميل.",
                "WhatsApp does not allow a free-form message more than 24h after the client's last one.",
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function Stream({
  messages,
  outbox,
  reset,
  sent,
  onReply,
  onRetry,
  onDiscard,
}: {
  messages: ThreadEntry[];
  outbox: Outgoing[];
  reset: string;
  /** Moves each time the person sends: their own message is always brought into view. */
  sent: number;
  onReply: (entry: ThreadEntry) => void;
  onRetry: (key: number) => void;
  onDiscard: (key: number) => void;
}) {
  const { t } = usePreferences();
  const element = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const newest = `${messages.length > 0 ? messages[messages.length - 1]!.uid : ""}|${outbox.map((item) => `${item.key}${item.state}`).join(",")}`;

  // Opening a conversation starts at its end.
  useEffect(() => {
    stick.current = true;
  }, [reset]);

  // Writing something puts it in view, wherever the person had scrolled to.
  useLayoutEffect(() => {
    stick.current = true;
  }, [sent]);

  // New messages keep the end in view, unless the person has scrolled up to read.
  useLayoutEffect(() => {
    const node = element.current;
    if (node && stick.current) node.scrollTop = node.scrollHeight;
  }, [newest, reset, sent]);

  let day = "";
  return (
    <div
      className="cchat__stream"
      ref={element}
      onScroll={(event) => {
        const node = event.currentTarget;
        stick.current = node.scrollHeight - node.scrollTop - node.clientHeight < 80;
      }}
    >
      {messages.length === 0 && outbox.length === 0 && (
        <div className="empty cchat__blank">
          <Icon name="message" size="xl" />
          <span>{t("مفيش رسايل لسه.", "No messages yet.")}</span>
        </div>
      )}
      {messages.map((entry) => {
        const divider = entry.date !== day;
        day = entry.date;
        return (
          <div key={entry.uid} className="chat-entry">
            {divider && <div className="chat-day muted mono">{entry.date}</div>}
            <Bubble entry={entry} onReply={onReply} />
          </div>
        );
      })}
      {outbox.map((item) => (
        <div key={`pending-${item.key}`} className="chat-entry">
          <OutgoingBubble item={item} onRetry={onRetry} onDiscard={onDiscard} />
        </div>
      ))}
    </div>
  );
}

/**
 * The id of the newest message the screen shows, from the uids the server wrote (`in-12`, `g3-45`).
 *
 * In a client's thread only the client's own messages count: they are what "read" is about, and our own
 * (`out-5`) live in another table with ids of their own.
 */
export function newestShown(code: string, messages: ThreadEntry[]): number {
  const clients = !/^[gu]\d+$/.test(code);
  let top = 0;
  for (const entry of messages) {
    if (clients && entry.kind !== "in") continue;
    const id = Number(/-(\d+)$/.exec(entry.uid)?.[1] ?? 0);
    if (id > top) top = id;
  }
  return top;
}

/** The message a reply answers, as the reply bar and the quote in the new bubble show it. */
export function replyTargetOf(entry: ThreadEntry, t: (ar: string, en: string) => string): ReplyTarget {
  const text = entry.body.trim().slice(0, 90) || entry.files[0]?.name || t("مرفق", "Attachment");
  return { uid: entry.uid, who: entry.kind === "in" ? t("العميل", "Client") : entry.sender, text };
}

/**
 * One conversation (steps 3a and 3b of the chat screen): the header, the notes, the messages, and the box to
 * write in.
 *
 * Having it on screen, with the tab in front, says "I have read this" - a POST of its own, the same one the
 * classic page sends, which for a client is also the read receipt on their phone. It is sent only for what
 * was actually shown: after the thread has been fetched again since this page opened (the cache may hold
 * minutes-old messages, and something newer may have arrived meanwhile), and naming the newest message on
 * screen, so a later one is not marked read - or told to the client's phone - before anybody has seen it.
 * Writing is not reading: a send marks nothing read, and the answer to it (the thread as it now is) goes
 * through the same rule.
 *
 * Words, replies and files can be written here; voice, reactions and forwarding come in the next steps, and
 * until then the way to the classic page stays on screen.
 */
export function Conversation({ code, kind, allowed }: { code: string; kind: ChatKind; allowed: boolean }) {
  const { t } = usePreferences();
  const account = useMe().data;
  const me = account?.user.id ?? 0;
  const limits = account?.limits ?? DEFAULT_LIMITS;
  // A code the page does not know, or a list this role does not have (a translator has no client
  // conversations): nothing is asked of the server, so nothing is refused and written to the audit log
  // at every refresh.
  const known = allowed && threadPath(code) !== null;
  const thread = useThread(known ? code : undefined);
  const mark = useMarkChatRead();
  const row = thread.data?.client;
  const messages = thread.data?.messages ?? [];
  const upto = newestShown(code, messages);
  const readUrl = readPath(code, row?.room);
  const posted = useRef("");
  const fresh = thread.isSuccess && thread.isFetchedAfterMount && !thread.isFetching;

  useEffect(() => {
    posted.current = "";
  }, [code]);

  useEffect(() => {
    if (!fresh || !readUrl || upto === 0) return;
    const check = () => {
      if (document.visibilityState !== "visible") return;
      const key = `${code}:${upto}`;
      if (posted.current === key) return;
      posted.current = key;
      mark.mutate({ path: readUrl, upto });
    };
    check();
    document.addEventListener("visibilitychange", check);
    return () => document.removeEventListener("visibilitychange", check);
  }, [fresh, code, upto, readUrl, mark.mutate]);

  const queued = useOutbox(code);
  const outbox = useOutboxActions(code, me);
  const [replyTo, setReplyTo] = useState<ReplyTarget | null>(null);
  const [sent, setSent] = useState(0);
  // What has reached the thread by another road (the doorbell, a poll) is not shown twice.
  const waiting = unmatched(queued, messages, me);
  const arrived = queued.filter((item) => item.state !== "sending" && !waiting.includes(item)).map((item) => item.key);
  const arrivedKeys = arrived.join(",");
  useEffect(() => {
    if (arrivedKeys) outbox.prune(arrivedKeys.split(",").map(Number));
  }, [arrivedKeys, outbox.prune]);

  const write = ({ body, files, task, voice }: Written) => {
    outbox.send({ body, files, task, voice, reply: replyTo, known: messages.map((entry) => entry.uid) });
    setReplyTo(null);
    setSent((count) => count + 1);
  };

  const classicUrl = row ? safeInternalPath(row.url) : "";
  const refused = !known || (thread.error instanceof ApiError && [401, 403, 404].includes(thread.error.status));

  return (
    <section className="cchat__room">
      <header className="cchat__head">
        <Link className="cchat__back" to={`/chats?type=${kind}`} title={t("رجوع", "Back")} aria-label={t("رجوع", "Back")}>
          <Icon name="arrow-right" />
        </Link>
        {row && <Header row={row} code={code} />}
      </header>

      {known && thread.isPending && (
        <div className="empty cchat__blank">
          <Icon name="refresh" size="xl" />
          <span>{t("بيحمّل...", "Loading...")}</span>
        </div>
      )}
      {(thread.isError || !known) && (
        <div className="empty cchat__blank" role="alert">
          <Icon name="alert" size="xl" />
          <span>
            {refused ? t("المحادثة دي مش متاحة ليك.", "This conversation is not available to you.") : t("حصلت مشكلة في التحميل.", "Could not load.")}
          </span>
        </div>
      )}
      {thread.data && row && (
        <>
          <Notes row={row} />
          <Stream
            messages={messages}
            outbox={waiting}
            reset={code}
            sent={sent}
            onReply={(entry) => setReplyTo(replyTargetOf(entry, t))}
            onRetry={outbox.retry}
            onDiscard={outbox.discard}
          />
          <Composer
            code={code}
            toClient={!row.staff && (row.reaches_client === true || !row.group)}
            pickTasks={row.staff === true || row.team === true}
            fileLimits={limits.files}
            voiceLimits={limits.voice}
            limit={row.staff || row.team ? limits.inside : row.reaches_client ? limits.to_client_group : limits.to_client}
            reply={replyTo}
            onClearReply={() => setReplyTo(null)}
            closed={windowClosed(row)}
            busy={queued.some((item) => item.state === "sending")}
            onSend={write}
          />
          <div className="cchat__hint muted">
            <Icon name="info" size="sm" />
            <span>
              {t(
                "التفاعلات والتحويل وتحويل الرسالة لتاسك لسه من الواجهة الحالية.",
                "Reactions, forwarding and turning a message into a task are still done in the classic interface.",
              )}{" "}
              {classicUrl && <a href={classicUrl}>{t("افتح المحادثة هناك", "Open it there")}</a>}
            </span>
          </div>
        </>
      )}
    </section>
  );
}
