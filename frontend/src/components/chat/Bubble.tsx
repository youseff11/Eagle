import type { MouseEvent } from "react";
import type { Reaction, ThreadEntry, ThreadFile } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { clockText } from "../../lib/clock";
import type { Outgoing } from "../../lib/outbox";
import { formatSeconds } from "../../lib/recorder";
import { prettySize } from "../../lib/size";
import { safeInternalPath } from "../../lib/safeUrl";
import { Avatar } from "../Avatar";
import { Icon } from "../Icon";
import { Ticks } from "./Ticks";
import { VoiceNote } from "./VoiceNote";
import { DocumentPreview } from "./DocumentPreview";

/** The colours of the reaction symbols (`r-<kind>` in the sprite). Anything else is not drawn. */
const REACTIONS = new Set(["like", "love", "laugh", "wow", "sad", "done"]);

/**
 * A tick box beside a file, for the two modes that pick files: the translator's «خلصت التاسك» (`hand`: their own
 * files) and the operation's "select files" (`pick`: a client's files, across messages). The mode is the page's;
 * the bubble only draws it. While `active` the boxes are drawn - and in `pick` a tap on the file itself ticks it
 * instead of opening it, where a photo is a link and the box is small. A voice note is never a file to pick.
 */
export interface FileMark {
  mode: "hand" | "pick";
  active: boolean;
  /** Which files can be ticked at all. */
  show: (entry: ThreadEntry, file: ThreadFile) => boolean;
  ticked: (file: ThreadFile) => boolean;
  toggle: (entry: ThreadEntry, file: ThreadFile) => void;
  /** Outside the mode: a button beside the file that turns the mode on with this file already ticked. */
  start?: { label: string; run: (entry: ThreadEntry, file: ThreadFile) => void };
}

function File({ file, entry, mark }: { file: ThreadFile; entry: ThreadEntry; mark?: FileMark }) {
  const { t } = usePreferences();
  // The server wrote the address. It is used only if it is a path on this site: never another site,
  // never a `javascript:` address.
  const url = safeInternalPath(file.url);
  if (file.audio && url) {
    return (
      <div className="bub__voice">
        <div className="bub__voice-head">
          <Icon name="mic" size="sm" />
          <span>{t("رسالة صوتية", "Voice note")}</span>
        </div>
        <VoiceNote url={url} length={file.length} />
      </div>
    );
  }
  const markable = mark !== undefined && mark.show(entry, file);
  const on = markable && mark.active;
  const ticked = on && mark.ticked(file);
  const classes = ["bub__file"];
  if (file.image && url) classes.push("bub__file--img");
  else if (url) classes.push("bub__file--document");
  if (ticked) classes.push("is-picked");
  // While picking, a tap on the file ticks it; a tap on the box is the box's own.
  const tap =
    on && mark.mode === "pick"
      ? (event: MouseEvent<HTMLDivElement>) => {
          if ((event.target as Element).closest("input")) return;
          event.preventDefault();
          mark.toggle(entry, file);
        }
      : undefined;
  const box = on ? (
    <input
      type="checkbox"
      className={mark.mode === "hand" ? "bub__hand" : "bub__pick"}
      checked={ticked}
      onChange={() => mark.toggle(entry, file)}
      aria-label={t("حدد الملف", "Select the file") + `: ${file.name}`}
    />
  ) : null;
  const start =
    markable && !on && mark.start ? (
      <button type="button" className="btn btn--sm btn--primary bub__handbtn" onClick={() => mark.start!.run(entry, file)}>
        <Icon name="check-circle" size="sm" />
        <span>{mark.start.label}</span>
      </button>
    ) : null;

  if (file.image && url) {
    return (
      <div className={classes.join(" ")} onClick={tap}>
        {box}
        <a className="bub__img" href={url} target="_blank" rel="noopener noreferrer" title={file.name}>
          <img src={url} alt={file.name} loading="lazy" />
        </a>
        {start}
      </div>
    );
  }
  return (
    <div className={classes.join(" ")} onClick={tap}>
      {box}
      {url ? (
        <DocumentPreview key={url} file={file} url={url} />
      ) : (
        <span>{file.name}</span>
      )}
      {start}
    </div>
  );
}

/** The pill that hangs off the bubble: who reacted, and a tap on it opens the bar of reactions. */
function Reactions({ reactions, onOpen, off }: { reactions: Reaction[]; onOpen?: (trigger: HTMLElement) => void; off: boolean }) {
  const { t } = usePreferences();
  if (reactions.length === 0) return null;
  const total = reactions.reduce((sum, reaction) => sum + reaction.count, 0);
  const top = [...reactions].sort((a, b) => b.count - a.count).slice(0, 3);
  const who = reactions.map((reaction) => reaction.who.join(", ")).join(" · ");
  const mine = reactions.some((reaction) => reaction.mine);
  return (
    <button
      type="button"
      className={`bub__reacts${mine ? " is-mine" : ""}`}
      title={who}
      aria-label={`${t("التفاعلات", "Reactions")}: ${who}`}
      data-react-open=""
      disabled={off || !onOpen}
      onClick={(event) => onOpen?.(event.currentTarget)}
    >
      {top
        .filter((reaction) => REACTIONS.has(reaction.kind))
        .map((reaction) => (
          <svg key={reaction.kind} className="remoji remoji--sm" aria-hidden="true">
            <use href={`#r-${reaction.kind}`} />
          </svg>
        ))}
      {total > 1 && <span className="bub__reacts-n">{total}</span>}
    </button>
  );
}

/**
 * One message, as the classic page draws it (`templates/ops/_client_bubble.html`, `bubbleHtml` in chat.js):
 * the forwarded tag, the quoted message, the text, the files, who and when, the marks and the reactions.
 *
 * Replying (`onReply`), reacting (`onReact`, which is given the button that was pressed, so the bar of reactions
 * can be put beside it) and forwarding (`onForward`: the first message of a selection) are the buttons beside the
 * bubble. While a selection is being made (`selecting`) they step aside: a tap on the bubble itself picks it or
 * drops it (`onToggle`), except on a link, a player or a button inside it, which keep working. The buttons that
 * turn a message into a task come with their own step. Every string is drawn as text; nothing the server sent
 * is read as markup.
 */
export function Bubble({
  entry,
  onReply,
  onReact,
  onForward,
  selecting = false,
  selected = false,
  onToggle,
  onConfirm,
  onConvert,
  fileMark,
  personal,
}: {
  entry: ThreadEntry;
  onReply?: (entry: ThreadEntry) => void;
  onReact?: (entry: ThreadEntry, trigger: HTMLElement) => void;
  onForward?: (entry: ThreadEntry) => void;
  selecting?: boolean;
  selected?: boolean;
  onToggle?: (entry: ThreadEntry) => void;
  /** «استلمت» and "turn into a task" under a client's message that carries a document (the server says who gets them). */
  onConfirm?: (entry: ThreadEntry) => void;
  onConvert?: (entry: ThreadEntry) => void;
  /** A mode that ticks files (see `FileMark`), or none. */
  fileMark?: FileMark;
  /**
   * A work group or a colleague's chat: only what this person wrote is on their side, and what the others wrote is on the other,
   * as in WhatsApp. In a client's conversation every message of ours is on our side (a colleague answered the client), and the
   * client is on the other.
   */
  personal?: boolean;
}) {
  const { t, lang } = usePreferences();
  const out = entry.kind === "out" && (!personal || entry.mine);
  const classes = ["bub", out ? "bub--out" : "bub--in"];
  if (entry.status === "failed") classes.push("bub--failed");
  if (entry.reactions.length > 0) classes.push("has-reacts");
  if (selected) classes.push("is-selected");

  return (
    <div
      className={classes.join(" ")}
      data-uid={entry.uid}
      onClick={(event) => {
        if (!selecting || !onToggle) return;
        if ((event.target as Element).closest("a, button, audio, input, .voice")) return;
        onToggle(entry);
      }}
    >
      {onReply && (
        <button
          className="bub__reply"
          type="button"
          title={t("رد", "Reply")}
          aria-label={t("رد", "Reply")}
          onClick={() => onReply(entry)}
        >
          <Icon name="reply" size="sm" />
        </button>
      )}
      {onReact && (
        <button
          className="bub__reply bub__react"
          type="button"
          data-react-open=""
          title={t("رياكت", "React")}
          aria-label={t("رياكت", "React")}
          onClick={(event) => onReact(entry, event.currentTarget)}
        >
          <Icon name="smile" size="sm" />
        </button>
      )}
      {onForward && (
        <button
          className="bub__reply bub__fwd"
          type="button"
          title={t("تحويل", "Forward")}
          aria-label={t("تحويل", "Forward")}
          onClick={() => onForward(entry)}
        >
          <Icon name="forward" size="sm" />
        </button>
      )}
      {onToggle && selecting && (
        <button
          type="button"
          className="bub__sel"
          aria-pressed={selected}
          aria-label={t("حدد الرسالة", "Select the message")}
          onClick={() => onToggle(entry)}
        >
          <Icon name="check" size="sm" />
        </button>
      )}
      <div className="bub__box">
        {entry.forwarded && (
          <div className="bub__fwdtag">
            <Icon name="forward" size="sm" />
            <span>{t("محوّلة", "Forwarded")}</span>
          </div>
        )}
        {entry.quote && (
          <div className="bub__quote">
            {entry.quote_who && <b>{entry.quote_who}</b>}
            <span>{entry.quote}</span>
          </div>
        )}
        {entry.subject && <div className="bub__subject">{entry.subject}</div>}
        {entry.body && <div className="bub__text">{entry.body}</div>}
        {entry.files.map((file, index) => (
          <File key={`${file.id}-${index}`} file={file} entry={entry} mark={fileMark} />
        ))}
        {entry.actions && entry.has_docs && (onConfirm || onConvert) && (
          <div className="bub__actions">
            {/* One receipt per message: once somebody has said "received", the button is gone and their name is there. */}
            {onConfirm && !entry.claimed_by && (
              <button type="button" className="btn btn--sm btn--accent" onClick={() => onConfirm(entry)}>
                <Icon name="check" size="sm" />
                <span>{t("استلمت", "Received")}</span>
              </button>
            )}
            {entry.task_code && <span className="chip chip--sm mono">{entry.task_code}</span>}
            {onConvert && (
              <button type="button" className="btn btn--sm" onClick={() => onConvert(entry)}>
                <Icon name={entry.task_code ? "plus" : "arrow-right"} size="sm" />
                <span>{entry.task_code ? t("طلب جديد", "New request") : t("تحويل لتاسك", "Convert to task")}</span>
              </button>
            )}
            {entry.claimed_by && (
              <span className="chip chip--sm">
                <Icon name="user-check" size="sm" />
                {entry.claimed_by}
              </span>
            )}
          </div>
        )}
        <div className="bub__foot">
          {entry.is_delivery && <span className="chip chip--sm">{t("تسليم تاسك", "Task delivery")}</span>}
          {entry.task_code && <span className="mono muted">{entry.task_code}</span>}
          {entry.sender && (
            <span className="bub__sender muted">
              {entry.sender_avatar && <Avatar src={entry.sender_avatar} initials={entry.sender.slice(0, 1)} tone="staff" className="avatar--xs" />}
              {entry.sender}
            </span>
          )}
          <span className="bub__time mono">{clockText(entry.time, lang)}</span>
          {out && <Ticks status={entry.status} receipt={entry.receipt} mine={entry.mine} seenBy={entry.seen_by} />}
        </div>
        {entry.error && <div className="bub__error">{entry.error}</div>}
        <Reactions
          reactions={entry.reactions}
          onOpen={onReact ? (trigger) => onReact(entry, trigger) : undefined}
          off={selecting}
        />
      </div>
    </div>
  );
}

/** Why a message that was refused was not sent, in the person's words; anything else is the general sentence. */
function refusal(code: string, t: (ar: string, en: string) => string): string {
  if (code === "empty") return t("مفيش حاجة تتبعت.", "There is nothing to send.");
  if (code === "too_long") return t("الرسالة أطول من الحد المسموح. قصّرها.", "The message is longer than allowed. Shorten it.");
  if (code === "forbidden" || code === "not_found") {
    return t("مش مسموحلك ترد في المحادثة دي.", "You cannot write in this conversation.");
  }
  if (code === "too_many_files") return t("عدد الملفات أكتر من المسموح.", "There are more files than allowed.");
  if (code === "empty_file") return t("التسجيل فاضي.", "The recording is empty.");
  if (code === "file_too_big") return t("فيه ملف أكبر من المسموح.", "A file is bigger than allowed.");
  if (code === "files_too_big") return t("الملفات مع بعض أكبر من المسموح.", "The files together are bigger than allowed.");
  if (code === "pick_task" || code === "bad_task") {
    return t(
      "حدد الملفات تبع أنهي تاسك. الشلّه وابعتها تاني بعد ما تختار.",
      "Say which task the files are for: discard it and send again after choosing.",
    );
  }
  if (code === "csrf") return t("الجلسة محتاجة تتحدّث. حدّث الصفحة وجرّب تاني.", "The session needs a refresh. Reload the page and try again.");
  if (code === "auth") return t("الجلسة خلصت. سجّل دخول تاني.", "The session ended. Sign in again.");
  return t("الرسالة ماتبعتتش.", "The message was not sent.");
}

/**
 * A message this person has written and the server has not yet confirmed: it is on its way ("sending"), or it
 * did not go and says so with the two things that can be done about it. `unsure` is the case where nothing
 * came back: the message may be there already, so the person is told to look before sending it again.
 */
export function OutgoingBubble({
  item,
  onRetry,
  onDiscard,
}: {
  item: Outgoing;
  onRetry: (key: number) => void;
  onDiscard: (key: number) => void;
}) {
  const { t } = usePreferences();
  const sending = item.state === "sending";
  const classes = ["bub", "bub--out", "bub--pending"];
  if (!sending) classes.push("bub--failed");

  return (
    <div className={classes.join(" ")} data-pending={item.key} aria-busy={sending}>
      <div className="bub__box">
        {item.reply && (
          <div className="bub__quote">
            {item.reply.who && <b>{item.reply.who}</b>}
            <span>{item.reply.text}</span>
          </div>
        )}
        {item.body && <div className="bub__text">{item.body}</div>}
        {item.files.map((file, index) => (
          <div className="bub__file" key={`${file.name}-${index}`}>
            <Icon name="paperclip" size="sm" />
            <span>{file.name}</span>
            <span className="muted mono">{prettySize(file.size)}</span>
          </div>
        ))}
        {item.voice && (
          <div className="bub__voice">
            <div className="bub__voice-head">
              <Icon name="mic" size="sm" />
              <span>{t("رسالة صوتية", "Voice note")}</span>
              <span className="mono">{formatSeconds(item.voice.seconds)}</span>
            </div>
          </div>
        )}
        <div className="bub__foot">
          {sending && (
            <span className="muted bub__sending">
              <Icon name="clock" size="sm" /> {t("بيتبعت...", "Sending...")}
            </span>
          )}
        </div>
        {item.state === "refused" && <div className="bub__error">{refusal(item.error, t)}</div>}
        {item.state === "unsure" && (
          <div className="bub__error">
            {t(
              "مش متأكدين إن الرسالة وصلت. بص على المحادثة قبل ما تبعتها تاني.",
              "We are not sure the message arrived. Check the conversation before sending it again.",
            )}
          </div>
        )}
        {!sending && (
          <div className="bub__retry">
            <button type="button" className="btn btn--sm" onClick={() => onRetry(item.key)}>
              {t("حاول تاني", "Try again")}
            </button>
            <button type="button" className="btn btn--sm" onClick={() => onDiscard(item.key)}>
              {t("امسح", "Discard")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
