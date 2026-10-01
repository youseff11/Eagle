import type { Reaction, ThreadEntry, ThreadFile } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { clockText } from "../../lib/clock";
import type { Outgoing } from "../../lib/outbox";
import { safeInternalPath } from "../../lib/safeUrl";
import { Icon } from "../Icon";
import { Ticks } from "./Ticks";
import { VoiceNote } from "./VoiceNote";

/** The colours of the reaction symbols (`r-<kind>` in the sprite). Anything else is not drawn. */
const REACTIONS = new Set(["like", "love", "laugh", "wow", "sad", "done"]);

function File({ file }: { file: ThreadFile }) {
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
  if (file.image && url) {
    return (
      <div className="bub__file bub__file--img">
        <a className="bub__img" href={url} target="_blank" rel="noopener noreferrer" title={file.name}>
          <img src={url} alt={file.name} loading="lazy" />
        </a>
      </div>
    );
  }
  return (
    <div className="bub__file">
      <Icon name="paperclip" size="sm" />
      {url ? (
        <a href={url} target="_blank" rel="noopener noreferrer">
          {file.name}
        </a>
      ) : (
        <span>{file.name}</span>
      )}
    </div>
  );
}

function Reactions({ reactions }: { reactions: Reaction[] }) {
  if (reactions.length === 0) return null;
  const total = reactions.reduce((sum, reaction) => sum + reaction.count, 0);
  const top = [...reactions].sort((a, b) => b.count - a.count).slice(0, 3);
  const who = reactions.map((reaction) => reaction.who.join(", ")).join(" · ");
  const mine = reactions.some((reaction) => reaction.mine);
  return (
    <span className={`bub__reacts${mine ? " is-mine" : ""}`} title={who}>
      {top
        .filter((reaction) => REACTIONS.has(reaction.kind))
        .map((reaction) => (
          <svg key={reaction.kind} className="remoji remoji--sm" aria-hidden="true">
            <use href={`#r-${reaction.kind}`} />
          </svg>
        ))}
      {total > 1 && <span className="bub__reacts-n">{total}</span>}
    </span>
  );
}

/**
 * One message, as the classic page draws it (`templates/ops/_client_bubble.html`, `bubbleHtml` in chat.js):
 * the forwarded tag, the quoted message, the text, the files, who and when, the marks and the reactions.
 *
 * Replying is here (`onReply`); reacting, forwarding and the buttons that turn a message into a task come
 * with their own steps. Every string is drawn as text; nothing the server sent is read as markup.
 */
export function Bubble({ entry, onReply }: { entry: ThreadEntry; onReply?: (entry: ThreadEntry) => void }) {
  const { t, lang } = usePreferences();
  const out = entry.kind === "out";
  const classes = ["bub", out ? "bub--out" : "bub--in"];
  if (entry.status === "failed") classes.push("bub--failed");
  if (entry.reactions.length > 0) classes.push("has-reacts");

  return (
    <div className={classes.join(" ")} data-uid={entry.uid}>
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
          <File key={`${file.id}-${index}`} file={file} />
        ))}
        <div className="bub__foot">
          {entry.is_delivery && <span className="chip chip--sm">{t("تسليم تاسك", "Task delivery")}</span>}
          {entry.task_code && <span className="mono muted">{entry.task_code}</span>}
          {entry.sender && <span className="muted">{entry.sender}</span>}
          <span className="bub__time mono">{clockText(entry.time, lang)}</span>
          {out && <Ticks status={entry.status} receipt={entry.receipt} mine={entry.mine} seenBy={entry.seen_by} />}
        </div>
        {entry.error && <div className="bub__error">{entry.error}</div>}
        <Reactions reactions={entry.reactions} />
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
        <div className="bub__text">{item.body}</div>
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
