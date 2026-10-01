import { useEffect, useLayoutEffect, useRef } from "react";
import { Link } from "react-router";
import { ApiError } from "../../api/client";
import { readPath, threadPath, useMarkChatRead, useThread } from "../../api/queries";
import type { ChatKind, ChatRow, ThreadEntry } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { safeInternalPath } from "../../lib/safeUrl";
import { Icon } from "../Icon";
import { Bubble } from "./Bubble";

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

/** The notes above the messages: what a group reaches, and the WhatsApp 24-hour rule. */
function Notes({ row }: { row: ChatRow }) {
  const { t } = usePreferences();
  const clientLine = !row.staff && (row.channel === "whatsapp" || row.reaches_client);
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
      {clientLine && row.channel === "whatsapp" && !row.window_open && (
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

function Stream({ messages, reset }: { messages: ThreadEntry[]; reset: string }) {
  const { t } = usePreferences();
  const element = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const newest = messages.length > 0 ? messages[messages.length - 1]!.uid : "";

  // Opening a conversation starts at its end.
  useEffect(() => {
    stick.current = true;
  }, [reset]);

  // New messages keep the end in view, unless the person has scrolled up to read.
  useLayoutEffect(() => {
    const node = element.current;
    if (node && stick.current) node.scrollTop = node.scrollHeight;
  }, [newest, reset]);

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
      {messages.length === 0 && (
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
            <Bubble entry={entry} />
          </div>
        );
      })}
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

/**
 * One conversation, read only (step 3a of the chat screen): the header, the notes, the messages.
 *
 * Having it on screen, with the tab in front, says "I have read this" - a POST of its own, the same one the
 * classic page sends, which for a client is also the read receipt on their phone. It is sent only for what
 * was actually shown: after the thread has been fetched again since this page opened (the cache may hold
 * minutes-old messages, and something newer may have arrived meanwhile), and naming the newest message on
 * screen, so a later one is not marked read - or told to the client's phone - before anybody has seen it.
 * Sending, replying, files, voice, reactions and forwarding come in the next steps; until then the way to
 * the classic page is on screen.
 */
export function Conversation({ code, kind, allowed }: { code: string; kind: ChatKind; allowed: boolean }) {
  const { t } = usePreferences();
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
          <Stream messages={messages} reset={code} />
          <div className="note note--info cchat__window">
            <Icon name="info" />
            <div>
              {t(
                "القراءة بس في الواجهة الجديدة لحد دلوقتي. للرد ابعت من الواجهة الحالية.",
                "Reading only in the new interface for now. To reply, use the classic interface.",
              )}{" "}
              {classicUrl && <a href={classicUrl}>{t("افتح المحادثة هناك", "Open it there")}</a>}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
