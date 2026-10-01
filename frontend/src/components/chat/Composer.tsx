import { useEffect, useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { usePreferences } from "../../i18n/Preferences";
import type { ReplyTarget } from "../../lib/outbox";
import { Icon } from "../Icon";

/** What was typed in each conversation and not sent: kept while the person looks at another one, never longer than the page. */
const drafts = new Map<string, string>();

/** Forget every unsent draft (a test starts from nothing). */
export function forgetDrafts(): void {
  drafts.clear();
}

const MAX_HEIGHT = 140;

/**
 * The longest message, until the server says (`me.limits`): what goes to a client (WhatsApp cuts a text at 4000
 * characters, silently; a client group adds the sender's role in front, which counts), and what stays inside.
 */
export const DEFAULT_LIMITS = { to_client: 4000, to_client_group: 3987, inside: 10000 };

/**
 * Where a message is written (chat slice 3b: words and replies; files and voice come with their own step).
 *
 * Enter sends, Shift+Enter is a new line, and neither does anything while an input method is still composing.
 * Escape drops the reply that was chosen. One message at a time is on its way (`busy`): it keeps what the
 * person writes in order, and a second tap cannot send the same words twice. When WhatsApp's 24-hour window
 * is closed (`closed`) the box is off and says why - the server would only be told "no" by Meta.
 */
export function Composer({
  code,
  toClient,
  limit,
  reply,
  onClearReply,
  closed,
  busy,
  onSend,
}: {
  code: string;
  /** What is written here reaches a client's phone. */
  toClient: boolean;
  /** The most characters one message may have here (what the server allows this person in this conversation). */
  limit: number;
  reply: ReplyTarget | null;
  onClearReply: () => void;
  closed: boolean;
  busy: boolean;
  onSend: (body: string) => void;
}) {
  const { t } = usePreferences();
  const [text, setText] = useState(() => drafts.get(code) ?? "");
  const box = useRef<HTMLTextAreaElement>(null);

  // The box grows with what is typed, up to a limit, then scrolls.
  useLayoutEffect(() => {
    const node = box.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, MAX_HEIGHT)}px`;
  }, [text]);

  // Choosing a message to answer puts the cursor back in the box.
  useEffect(() => {
    if (reply) box.current?.focus();
  }, [reply]);

  const body = text.trim();
  const over = body.length > limit;
  const ready = body !== "" && !busy && !closed && !over;

  const change = (value: string) => {
    setText(value);
    if (value === "") drafts.delete(code);
    else drafts.set(code, value);
  };

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (!ready) return;
    onSend(body);
    change("");
  };

  const keys = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Escape" && reply) {
      onClearReply();
    } else if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  const placeholder = closed
    ? t("نافذة الـ24 ساعة قفلت: مينفعش تبعت دلوقتي.", "The 24-hour window is closed: you cannot send now.")
    : toClient
      ? t("اكتب رسالتك للعميل...", "Write your reply to the client...")
      : t("اكتب رسالة...", "Write a message...");

  return (
    <>
      {reply && (
        <div className="cchat__replybar">
          <Icon name="reply" size="sm" />
          <div className="cchat__replybar-body">
            <b>{reply.who}</b>
            <span>{reply.text}</span>
          </div>
          <button
            type="button"
            className="icon-btn"
            onClick={onClearReply}
            title={t("إلغاء الرد", "Cancel the reply")}
            aria-label={t("إلغاء الرد", "Cancel the reply")}
          >
            <Icon name="x" size="sm" />
          </button>
        </div>
      )}
      {body.length > limit * 0.9 && (
        <div className={`cchat__count mono${over ? " is-over" : ""}`} role={over ? "alert" : undefined}>
          {body.length} / {limit}
          {over && (
            <span>
              {" "}
              {toClient
                ? t("— قصّرها: واتساب مش هيوصّل أكتر من كده.", "— shorten it: WhatsApp will not carry more than that.")
                : t("— قصّرها.", "— shorten it.")}
            </span>
          )}
        </div>
      )}
      <form className="cchat__composer" onSubmit={submit} autoComplete="off">
        <textarea
          ref={box}
          className="input grow cchat__input"
          rows={1}
          value={text}
          disabled={closed}
          placeholder={placeholder}
          aria-label={t("الرسالة", "Message")}
          onChange={(event) => change(event.target.value)}
          onKeyDown={keys}
        />
        <button className="btn btn--primary" type="submit" id="chatSend" disabled={!ready}>
          <Icon name="send" size="sm" />
          <span>{t("إرسال", "Send")}</span>
        </button>
      </form>
    </>
  );
}
