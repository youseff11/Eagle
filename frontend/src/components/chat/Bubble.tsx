import type { Reaction, ThreadEntry, ThreadFile } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { clockText } from "../../lib/clock";
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
 * Reading only: replying, reacting, forwarding and the buttons that turn a message into a task come
 * with their own steps. Every string is drawn as text; nothing the server sent is read as markup.
 */
export function Bubble({ entry }: { entry: ThreadEntry }) {
  const { t, lang } = usePreferences();
  const out = entry.kind === "out";
  const classes = ["bub", out ? "bub--out" : "bub--in"];
  if (entry.status === "failed") classes.push("bub--failed");
  if (entry.reactions.length > 0) classes.push("has-reacts");

  return (
    <div className={classes.join(" ")} data-uid={entry.uid}>
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
