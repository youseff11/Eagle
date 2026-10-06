import { Loading } from "../Loading";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { ApiError } from "../../api/client";
import { readPath, threadPath, useGroupMembers, useHandInTasks, useMarkChatRead, useMe, useReact, useThread } from "../../api/queries";
import type { ChatKind, ChatRow, ThreadEntry } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { useFilePick } from "../../hooks/useFilePick";
import { kindOfCode } from "../../lib/chatCode";
import { unmatched, useOutbox, useOutboxActions, type Outgoing, type ReplyTarget } from "../../lib/outbox";
import { safeInternalPath } from "../../lib/safeUrl";
import { AiNotesPanel } from "../ai/AiNotesPanel";
import { CallButtons } from "./CallButtons";
import { Avatar } from "../Avatar";
import { Icon } from "../Icon";
import { AddMembersDialog } from "./AddMembersDialog";
import { Bubble, OutgoingBubble, type FileMark } from "./Bubble";
import { ConvertDialog } from "./ConvertDialog";
import { Composer, DEFAULT_LIMITS, type Written } from "./Composer";
import { ForwardDialog } from "./ForwardDialog";
import { HandInBar } from "./HandInBar";
import { PickBar } from "./PickBar";
import { ReceiptDialog } from "./ReceiptDialog";
import { ReactionPicker } from "./ReactionPicker";

function Header({ row, code }: { row: ChatRow; code: string }) {
  const { t } = usePreferences();
  let meta: string;
  if (row.staff) meta = row.role === "support" ? t("دعم فني", "Technical support") : t("زميل", "Colleague");
  else if (row.group) meta = row.team ? t("جروب شغل", "Work group") : t("جروب", "Group");
  else if (row.channel === "whatsapp") meta = "WhatsApp";
  else if (row.channel === "email") meta = "Email";
  else meta = t("مفيش قناة", "No channel");

  return (
    <>
      {row.staff ? (
        <Avatar src={row.avatar} initials={row.initials ?? ""} tone="staff" />
      ) : (
        <span className={`avatar ${row.group ? "avatar--group" : "avatar--brand"}`}>
          {row.group ? <Icon name="users" size="sm" /> : code.slice(3)}
        </span>
      )}
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

/** What can be done with a message beside it: answer it, react to it, start forwarding from it, pick it. */
interface BubbleActions {
  onReply: (entry: ThreadEntry) => void;
  /** Not for every role in every conversation (a Sales person has no say in a client's thread): then they are off. */
  onReact?: (entry: ThreadEntry, trigger: HTMLElement) => void;
  onForward?: (entry: ThreadEntry) => void;
  onToggle?: (entry: ThreadEntry) => void;
  /** Under a client's message with a document: «استلمت», and turning it into a task. */
  onConfirm?: (entry: ThreadEntry) => void;
  onConvert?: (entry: ThreadEntry) => void;
}

function Stream({
  messages,
  outbox,
  reset,
  sent,
  actions,
  selecting,
  selected,
  fileMark,
  personal,
  onRetry,
  onDiscard,
}: {
  messages: ThreadEntry[];
  outbox: Outgoing[];
  reset: string;
  /** Moves each time the person sends: their own message is always brought into view. */
  sent: number;
  actions: BubbleActions;
  /** Messages are being picked to be forwarded: a tap picks or drops one. */
  selecting: boolean;
  selected: string[];
  /** A mode that ticks files is on, or could be started from a file. */
  fileMark?: FileMark;
  /** A work group or a colleague's chat (see `Bubble`): the sides follow who wrote each message. */
  personal: boolean;
  onRetry: (key: number) => void;
  onDiscard: (key: number) => void;
}) {
  const { t } = usePreferences();
  const element = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const newest = `${messages.length > 0 ? messages[messages.length - 1]!.uid : ""}|${outbox.map((item) => `${item.key}${item.state}`).join(",")}`;

  // Opening a conversation starts at its end.
  useLayoutEffect(() => {
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

  // Images, fonts and the phone's viewport can settle after the messages have rendered.
  // Watch the entries as well as the viewport: its scrollHeight can grow without its own box resizing.
  useLayoutEffect(() => {
    const node = element.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      if (stick.current) node.scrollTop = node.scrollHeight;
    });
    observer.observe(node);
    for (const child of node.children) observer.observe(child);
    return () => observer.disconnect();
  }, [newest, reset, messages.length]);

  let day = "";
  return (
    <div
      className={`cchat__stream${selecting ? " is-selecting" : ""}${fileMark?.active ? (fileMark.mode === "hand" ? " is-handing" : " is-picking") : ""}`}
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
            <Bubble
              entry={entry}
              onReply={actions.onReply}
              onReact={actions.onReact}
              onForward={actions.onForward}
              onToggle={actions.onToggle}
              onConfirm={actions.onConfirm}
              onConvert={actions.onConvert}
              selecting={selecting}
              selected={selected.includes(entry.uid)}
              fileMark={fileMark}
              personal={personal}
            />
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
 * Words, replies, files and voice can be written here, a message can be reacted to, and several can be picked and
 * forwarded to another conversation (step 3d). Step 3e adds the work groups (who is in one, opening one, adding to
 * one), the translator's «خلصت التاسك», and - for the operation and the admin - «استلمت», turning a message (or
 * files picked across messages) into a task, which leads to the classic task form. Calls to a colleague are placed from
 * the header (`CallButtons`) and drawn by the overlay; the way to the classic page stays on screen for what is not here. The AI's suggestions on what a translator handed over are the panel
 * a team leader gets beside a work group or a colleague's chat (`AiNotesPanel`).
 */
export function Conversation({ code, kind, allowed }: { code: string; kind: ChatKind; allowed: boolean }) {
  const { t } = usePreferences();
  const navigate = useNavigate();
  const account = useMe().data;
  const me = account?.user.id ?? 0;
  const limits = account?.limits ?? DEFAULT_LIMITS;
  // Marking a client's message and forwarding from a client's thread belong to the operation and the admin, as
  // on the classic page; a work group or a colleague's chat is open to whoever is in it.
  const mayAnswerClients = account?.user.role === "operation" || account?.user.is_admin === true;
  const mayMark = kindOfCode(code) !== "clients" || mayAnswerClients;
  const forwardKinds = (account?.chats.types ?? []).filter(
    (list): list is ChatKind => (list === "clients" ? mayAnswerClients : list === "groups" || list === "staff"),
  );
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

  // Reactions: one bar, put beside the bubble that asked for it; one reaction at a time is on its way.
  const react = useReact(code);
  const [picker, setPicker] = useState<{ uid: string; trigger: HTMLElement } | null>(null);
  const [notice, setNotice] = useState("");
  const closePicker = useCallback(() => setPicker(null), []);
  const openPicker = (entry: ThreadEntry, trigger: HTMLElement) => {
    setNotice("");
    setPicker((open) => (open?.uid === entry.uid ? null : { uid: entry.uid, trigger }));
  };
  const give = (reaction: string) => {
    if (!picker) return;
    const { uid, trigger } = picker;
    setPicker(null);
    if (trigger.isConnected) trigger.focus();
    if (react.isPending) return;
    setNotice("");
    react.mutate(
      { uid, kind: reaction },
      { onError: () => setNotice(t("التفاعل ماتسجلش. جرّب تاني.", "The reaction was not saved. Try again.")) },
    );
  };
  const pickerEntry = picker ? messages.find((entry) => entry.uid === picker.uid) : undefined;

  // Forwarding: the bubbles become a list to tap, the bar underneath says how many, and "Forward" asks where to.
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [forwarding, setForwarding] = useState(false);
  const startSelecting = (entry?: ThreadEntry) => {
    setPicker(null);
    setNotice("");
    stopHanding();
    pick.stop();
    setSelecting(true);
    setSelected(entry ? [entry.uid] : []);
  };
  const stopSelecting = useCallback(() => {
    setSelecting(false);
    setSelected([]);
    setForwarding(false);
  }, []);
  const toggle = (entry: ThreadEntry) =>
    setSelected((now) => (now.includes(entry.uid) ? now.filter((uid) => uid !== entry.uid) : [...now, entry.uid]));
  // What was picked and has gone from the thread is not forwarded.
  const present = messages.map((entry) => entry.uid).join(",");
  useEffect(() => {
    const here = new Set(present.split(","));
    setSelected((now) => (now.every((uid) => here.has(uid)) ? now : now.filter((uid) => here.has(uid))));
  }, [present]);
  useEffect(() => {
    if (!selecting || forwarding) return;
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && picker === null) stopSelecting();
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [selecting, forwarding, picker, stopSelecting]);
  const forwarded = (target: string | null) => {
    stopSelecting();
    if (target) navigate(`/chats/${target}?type=${kindOfCode(target)}`);
  };

  // Who is in a group, and adding to it. A private line is two people and has no row of them.
  const isGroup = /^g\d+$/.test(code);
  const members = useGroupMembers(row?.room, isGroup && known);
  const [adding, setAdding] = useState(false);

  // «خلصت التاسك»: a translator hands in their own files from a work group, and the task goes to review.
  const handTasks = useHandInTasks(row?.room, isGroup && known && row?.team === true && account?.user.role === "translator");
  const tasksToHand = handTasks.data?.tasks ?? [];
  const [handing, setHanding] = useState(false);
  const [handed, setHanded] = useState<number[]>([]);
  const [done, setDone] = useState("");
  const startHanding = (first?: number) => {
    setPicker(null);
    setNotice("");
    setDone("");
    stopSelecting();
    pick.stop();
    setHanding(true);
    setHanded(first ? [first] : []);
  };
  const stopHanding = useCallback(() => {
    setHanding(false);
    setHanded([]);
  }, []);
  // A file that has gone from the thread is not handed in.
  const mineHere = messages.flatMap((entry) => (entry.mine ? entry.files.map((one) => one.id) : [])).join(",");
  useEffect(() => {
    const here = new Set(mineHere.split(",").map(Number));
    setHanded((now) => (now.every((id) => here.has(id)) ? now : now.filter((id) => here.has(id))));
  }, [mineHere]);
  const handMark: FileMark | undefined =
    tasksToHand.length > 0
      ? {
          mode: "hand",
          active: handing,
          show: (entry, one) => entry.mine && one.id > 0 && !one.audio,
          ticked: (one) => handed.includes(one.id),
          toggle: (_entry, one) => setHanded((now) => (now.includes(one.id) ? now.filter((id) => id !== one.id) : [...now, one.id])),
          start: { label: t("خلصت التاسك", "Task done"), run: (_entry, one) => startHanding(one.id) },
        }
      : undefined;

  // A client's files: «استلمت» and turning a message into a task (the operation and the admin), and "select files" -
  // files ticked across messages become one task or are forwarded.
  const clientThread = kindOfCode(code) === "clients";
  const pick = useFilePick(messages);
  const [converting, setConverting] = useState<ThreadEntry | null>(null);
  const [receipting, setReceipting] = useState<ThreadEntry | null>(null);
  const [forwardingFiles, setForwardingFiles] = useState(false);
  const mayPick = clientThread && mayAnswerClients && pick.available;
  const startPicking = () => {
    setPicker(null);
    setNotice("");
    stopSelecting();
    stopHanding();
    pick.start();
  };

  const actions: BubbleActions = {
    onReply: (entry) => setReplyTo(replyTargetOf(entry, t)),
    ...(mayMark ? { onReact: openPicker, onForward: startSelecting, onToggle: toggle } : {}),
    ...(clientThread && mayAnswerClients ? { onConfirm: setReceipting, onConvert: setConverting } : {}),
  };

  const refused = !known || (thread.error instanceof ApiError && [401, 403, 404].includes(thread.error.status));

  return (
    <section className="cchat__room">
      <header className="cchat__head">
        <Link className="cchat__back" to={`/chats?type=${kind}`} title={t("رجوع", "Back")} aria-label={t("رجوع", "Back")}>
          <Icon name="arrow-right" />
        </Link>
        {row && <Header row={row} code={code} />}
        <div className="grow" />
        {members.data?.can_add && row && (
          <button type="button" className="btn btn--ghost" id="addMemberBtn" onClick={() => setAdding(true)}>
            <Icon name="user-check" size="sm" />
            <span>{t("ضيف عضو", "Add member")}</span>
          </button>
        )}
        {/* A colleague can be rung from here: a voice call or a video call. A client never is. */}
        {row?.staff && <CallButtons code={code} name={row.label} initials={row.initials ?? ""} />}
        {thread.data && clientThread && account?.chats.types.includes("clients") && (
          <a className="btn btn--ghost cchat__profile" href={`/clients/${encodeURIComponent(code)}/`}>
            <Icon name="user" size="sm" />
            <span>{t("ملف العميل", "Client profile")}</span>
          </a>
        )}
        {thread.data && mayPick && (
          <button
            type="button"
            className={`btn btn--ghost${pick.picking ? " is-on" : ""}`}
            id="pickToggle"
            aria-pressed={pick.picking}
            title={t("حدد ملفات من كذا رسالة وحوّلها لتاسك واحدة", "Tick files across several messages and turn them into one task")}
            onClick={() => (pick.picking ? pick.stop() : startPicking())}
          >
            <Icon name="list-checks" size="sm" />
            <span>{t("تحديد ملفات", "Select files")}</span>
          </button>
        )}
        {thread.data && tasksToHand.length > 0 && (
          <button
            type="button"
            className="btn btn--primary"
            id="handinToggle"
            aria-pressed={handing}
            title={t("حدد ملفات الترجمة وخلّص التاسك", "Pick the translated files and finish the task")}
            onClick={() => (handing ? stopHanding() : startHanding())}
          >
            <Icon name="check-circle" size="sm" />
            <span>{t("خلصت التاسك", "Task done")}</span>
          </button>
        )}
        {thread.data && mayMark && messages.length > 0 && (
          <button
            type="button"
            className={`btn btn--ghost${selecting ? " is-on" : ""}`}
            id="selectToggle"
            aria-pressed={selecting}
            title={t("حدد رسايل وحوّلها لشات تاني", "Select messages to forward")}
            onClick={() => (selecting ? stopSelecting() : startSelecting())}
          >
            <Icon name="forward" size="sm" />
            <span>{t("تحويل رسايل", "Forward")}</span>
          </button>
        )}
      </header>

      {known && thread.isPending && (
        <Loading className="empty cchat__blank" />
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
          {members.data && members.data.members.length > 0 && (
            <div className="cchat__members">
              <Icon name="users" size="sm" />
              {members.data.members.map((person) => (
                <span className="chip chip--sm" key={person.id}>
                  {person.name}
                </span>
              ))}
            </div>
          )}
          <Notes row={row} />
          {/* A team leader's: what the AI noticed in the translation this person handed over. Nobody else is asked. */}
          <AiNotesPanel code={code} enabled={account?.user.role === "team_lead"} />
          {notice && (
            <div className="note note--warn cchat__window" role="alert">
              <Icon name="alert" />
              <div>{notice}</div>
            </div>
          )}
          {done && (
            <div className="note cchat__window" role="status">
              <Icon name="check-circle" />
              <div>
                {t(`تمام: ${done} راحت للمراجعة.`, `Done: ${done} went to review.`)}{" "}
                {safeInternalPath(`/tasks/${encodeURIComponent(done)}/`) && (
                  <a href={safeInternalPath(`/tasks/${encodeURIComponent(done)}/`)!}>{t("افتح التاسك", "Open the task")}</a>
                )}
              </div>
            </div>
          )}
          <Stream
            messages={messages}
            outbox={waiting}
            reset={code}
            sent={sent}
            actions={actions}
            selecting={selecting}
            selected={selected}
            fileMark={selecting ? undefined : (pick.mark ?? handMark)}
            personal={kindOfCode(code) !== "clients"}
            onRetry={outbox.retry}
            onDiscard={outbox.discard}
          />
          {selecting ? (
            <div className="cchat__pickbar" role="toolbar" aria-label={t("تحويل رسايل", "Forward")}>
              <Icon name="forward" size="sm" />
              <span aria-live="polite">
                <b className="mono">{selected.length}</b> {t("رسالة متحددة", "selected")}
              </span>
              <span className="grow" />
              <button type="button" className="btn btn--sm" onClick={stopSelecting}>
                {t("إلغاء", "Cancel")}
              </button>
              <button type="button" className="btn btn--sm btn--primary" disabled={selected.length === 0} onClick={() => setForwarding(true)}>
                <Icon name="forward" size="sm" />
                <span>{t("تحويل", "Forward")}</span>
              </button>
            </div>
          ) : pick.picking ? (
            <PickBar
              count={pick.ids.length}
              days={pick.days}
              day={pick.day}
              allIn={pick.allIn}
              messages={pick.messageIds}
              files={pick.ids}
              onDay={pick.chooseDay}
              onAll={pick.toggleAll}
              onCancel={pick.stop}
              onForward={() => setForwardingFiles(true)}
            />
          ) : handing && row?.room !== undefined ? (
            <HandInBar
              room={row.room}
              code={code}
              tasks={tasksToHand}
              files={handed}
              onCancel={stopHanding}
              onDone={(task) => {
                stopHanding();
                setDone(task);
              }}
            />
          ) : (
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
          )}
          {picker && pickerEntry && (
            <ReactionPicker
              trigger={picker.trigger}
              mine={pickerEntry.reactions.find((reaction) => reaction.mine)?.kind ?? ""}
              onPick={give}
              onClose={closePicker}
            />
          )}
          {adding && row?.room !== undefined && members.data && (
            <AddMembersDialog
              room={row.room}
              code={code}
              addable={members.data.addable}
              reachesClient={row.reaches_client === true}
              onClose={() => setAdding(false)}
              onDone={(left) => {
                setAdding(false);
                setNotice(left);
              }}
            />
          )}
          {converting && <ConvertDialog entry={converting} onClose={() => setConverting(null)} />}
          {receipting && <ReceiptDialog entry={receipting} code={code} onClose={() => setReceipting(null)} />}
          {forwardingFiles && pick.ids.length > 0 && (
            <ForwardDialog
              source={code}
              count={pick.ids.length}
              uids={[]}
              files={pick.ids}
              kinds={forwardKinds}
              onClose={() => setForwardingFiles(false)}
              onDone={(target) => {
                setForwardingFiles(false);
                pick.stop();
                if (target) navigate(`/chats/${target}?type=${kindOfCode(target)}`);
              }}
            />
          )}
          {forwarding && selected.length > 0 && (
            <ForwardDialog
              source={code}
              count={selected.length}
              uids={selected}
              kinds={forwardKinds}
              onClose={() => setForwarding(false)}
              onDone={forwarded}
            />
          )}
        </>
      )}
    </section>
  );
}
