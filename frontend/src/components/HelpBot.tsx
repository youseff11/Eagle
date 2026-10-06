import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { useAsk, useCancelOrder, useHelpHome, useRunOrder, type HelpTurn } from "../api/helpActions";
import { ApiError } from "../api/client";
import type { HelpGuide, HelpOrder } from "../api/types";
import { usePreferences } from "../i18n/Preferences";
import { Icon } from "./Icon";

/** How an order card stands: waiting for the owner's yes, being carried out, or over (done, refused, withdrawn, replaced by a newer one). */
type OrderState = "waiting" | "running" | "done" | "failed" | "cancelled" | "replaced";

interface Turn {
  id: number;
  who: "me" | "bot";
  text: string;
  /** The guide the answer is about: its page gets a button. */
  open?: HelpGuide | null;
  related?: HelpGuide[];
  order?: { card: HelpOrder; state: OrderState; message?: string };
  /** The turn is an error of ours, not an answer: it is not sent back as part of the conversation. */
  problem?: boolean;
  /** The server asked for it to be left out of the conversation (it names people of ours). */
  forget?: boolean;
}

/** The last turns the server's AI path may read, and the longest of them it keeps. */
const HISTORY = 6;

const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const NAMES = /(«[^»]+»)/;

/** A line of words, with each button or menu name between guillemets set apart, so a step can be followed on the screen. */
function Words({ text }: { text: string }) {
  return (
    <>
      {text.split(NAMES).map((part, index) =>
        index % 2 === 1 ? (
          <b className="help__name" key={index}>
            {part}
          </b>
        ) : (
          part
        ),
      )}
    </>
  );
}

/**
 * An answer as text: its numbered lines become a list, the rest are paragraphs, and a title line above a list is set bold. It is
 * only ever drawn as text (the words are the server's or the model's, never markup).
 */
function Answer({ text }: { text: string }) {
  const blocks: ({ kind: "p"; text: string } | { kind: "ol"; items: string[] })[] = [];
  for (const line of text.split("\n")) {
    const step = NUMBERED.exec(line);
    const last = blocks[blocks.length - 1];
    if (step) {
      if (last?.kind === "ol") last.items.push(step[1]!);
      else blocks.push({ kind: "ol", items: [step[1]!] });
    } else if (line.trim()) {
      blocks.push({ kind: "p", text: line.trim() });
    }
  }
  return (
    <>
      {blocks.map((block, index) =>
        block.kind === "ol" ? (
          <ol className="help__steps" key={index}>
            {block.items.map((item, at) => (
              <li key={at}>
                <Words text={item} />
              </li>
            ))}
          </ol>
        ) : (
          <p className={index === 0 && blocks[1]?.kind === "ol" ? "help__title" : undefined} key={index}>
            <Words text={block.text} />
          </p>
        ),
      )}
    </>
  );
}

/**
 * The assistant: a button in the top bar that opens a small chat, on every page, for everybody. A person asks how to do something
 * and is told the steps in this system (the server answers from its own guides, for the person's role); what it offers first is
 * the role's own questions. For the owner, when they have allowed it, it can also take an order and shows it on a card that does
 * nothing until the owner presses «Run».
 */
export function HelpBot() {
  const { t, lang } = usePreferences();
  const location = useLocation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const counter = useRef(0);
  const panel = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const log = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const home = useHelpHome(lang, open);
  const ask = useAsk();
  const run = useRunOrder();
  const cancel = useCancelOrder();

  useEffect(() => {
    if (open) box.current?.focus();
  }, [open]);

  // The newest turn is in view.
  useEffect(() => {
    const element = log.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [turns, ask.isPending]);

  useEffect(() => {
    if (!open) return;
    const escape = (event: KeyboardEvent | globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      trigger.current?.focus();
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [open]);

  const add = (turn: Omit<Turn, "id">) => setTurns((now) => [...now, { ...turn, id: ++counter.current }]);
  const settle = (id: number, order: Partial<NonNullable<Turn["order"]>>) =>
    setTurns((now) => now.map((turn) => (turn.id === id && turn.order ? { ...turn, order: { ...turn.order, ...order } } : turn)));

  const asking = (error: unknown) =>
    error instanceof ApiError && error.code === "slow_down"
      ? t("بتسأل بسرعة. استنى شوية وجرّب تاني.", "You are asking too fast. Wait a moment and try again.")
      : t("مقدرتش أرد دلوقتي. جرّب تاني.", "I could not answer just now. Try again.");

  const refused = (error: unknown) => {
    const code = error instanceof ApiError ? error.code : "";
    if (code === "expired") return t("الأمر انتهت مدته. اطلبه تاني.", "The order has expired. Ask for it again.");
    if (code === "already_done" || code === "not_found") return t("الأمر ده اتنفّذ أو اتلغى قبل كده.", "That order was already carried out or withdrawn.");
    if (code === "orders_off") return t("الأوامر مقفولة من الإعدادات.", "Orders are switched off in the settings.");
    if (code === "slow_down") return t("استنى شوية وجرّب تاني.", "Wait a moment and try again.");
    return t("الأمر ماتنفّذش. جرّب تاني.", "The order was not carried out. Try again.");
  };

  const send = (typed: string, guide?: HelpGuide) => {
    const said = guide ? guide.title : typed.trim();
    if (!said || ask.isPending) return;
    const history: HelpTurn[] = turns
      .filter((turn) => turn.text && !turn.problem && !turn.forget)
      .slice(-HISTORY)
      .map((turn) => ({ role: turn.who === "me" ? "user" : "assistant", text: turn.text }));
    add({ who: "me", text: said });
    setText("");
    ask.mutate(
      { question: guide ? "" : said, guide: guide?.id, lang, page: location.pathname, history },
      {
        onSuccess: (answer) => {
          // A new order withdraws the one before it (the server does the same): only the newest card can be pressed.
          if (answer.order) {
            setTurns((now) =>
              now.map((turn) =>
                turn.order?.state === "waiting" ? { ...turn, order: { ...turn.order, state: "replaced" as const } } : turn,
              ),
            );
          }
          add({
            who: "bot",
            text: answer.answer,
            forget: answer.keep === false,
            open: answer.open,
            related: answer.related,
            order: answer.order ? { card: answer.order, state: "waiting" } : undefined,
          });
        },
        onError: (error) => add({ who: "bot", text: asking(error), problem: true }),
      },
    );
  };

  const decide = (turn: Turn, yes: boolean) => {
    if (!turn.order) return;
    const id = turn.order.card.id;
    settle(turn.id, { state: "running" });
    if (yes) {
      run.mutate(
        { id, lang },
        {
          onSuccess: (result) => settle(turn.id, { state: result.done ? "done" : "failed", message: result.message }),
          onError: (error) => settle(turn.id, { state: "failed", message: refused(error) }),
        },
      );
    } else {
      cancel.mutate(id, {
        onSuccess: () => settle(turn.id, { state: "cancelled" }),
        onError: () => settle(turn.id, { state: "cancelled" }),
      });
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    send(text);
  };

  const keys = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends; Shift+Enter is a new line (and an Enter that picks a letter in an input method is not a send).
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      send(text);
    }
  };

  /** On a phone the page behind is hidden by the chat: following a link to it puts the chat away. */
  const followed = () => {
    if (window.matchMedia?.("(max-width: 600px)").matches) setOpen(false);
  };

  /** The chat with technical support, when there is such an account: the same chat a colleague's name in the lists opens. */
  const support = home.data?.support ?? null;
  const contactSupport = () => {
    if (!support) return;
    setOpen(false);
    navigate(`/chats/u${support.id}?type=staff`);
  };

  const chip = (guide: HelpGuide) => (
    <button type="button" className="chip help__chip" key={guide.id} disabled={ask.isPending} onClick={() => send("", guide)}>
      {guide.title}
    </button>
  );

  const orderBox = (turn: Turn): ReactNode => {
    if (!turn.order) return null;
    const { card, state, message } = turn.order;
    const over = state === "done" || state === "failed" || state === "cancelled" || state === "replaced";
    return (
      <div className={`help__order${card.danger ? " is-danger" : ""} is-${state}`}>
        <div className="help__order-title">
          <Icon name={card.danger ? "alert" : "check-circle"} size="sm" />
          <b>{card.title}</b>
        </div>
        <p>{card.summary}</p>
        {!over && (
          <div className="help__order-actions">
            <button
              type="button"
              className={`btn btn--sm ${card.danger ? "btn--danger" : "btn--primary"}`}
              disabled={state === "running"}
              onClick={() => decide(turn, true)}
            >
              <Icon name="check" size="sm" />
              <span>{state === "running" ? t("بينفّذ...", "Running...") : t("نفّذ", "Run")}</span>
            </button>
            <button type="button" className="btn btn--sm btn--ghost" disabled={state === "running"} onClick={() => decide(turn, false)}>
              {t("إلغاء", "Cancel")}
            </button>
          </div>
        )}
        {state === "done" && (
          <div className="note note--ok" role="status">
            <Icon name="check-circle" />
            <div>{message}</div>
          </div>
        )}
        {state === "failed" && (
          <div className="note note--high" role="alert">
            <Icon name="alert" />
            <div>{message}</div>
          </div>
        )}
        {state === "cancelled" && <div className="muted">{t("اتلغى.", "Withdrawn.")}</div>}
        {state === "replaced" && <div className="muted">{t("اتلغى: فيه أمر أحدث.", "Withdrawn: there is a newer order.")}</div>}
      </div>
    );
  };

  return (
    <div className="help">
      <button
        type="button"
        ref={trigger}
        className={`icon-btn help__btn${open ? " is-open" : ""}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panel : undefined}
        title={t("مساعد النظام: اسأل إزاي تعمل أي حاجة", "System assistant: ask how to do anything")}
        onClick={() => setOpen((now) => !now)}
      >
        <Icon name="robot" />
        <span className="help__label">{t("المساعد", "Assistant")}</span>
      </button>

      {open && (
        <section className="help__pop" id={panel} role="dialog" aria-label={t("مساعد النظام", "System assistant")}>
          <header className="help__head">
            <Icon name="robot" />
            <b>{t("مساعد النظام", "System assistant")}</b>
            <span className="grow" />
            <button
              type="button"
              className="icon-btn"
              aria-label={t("اقفل المساعد", "Close the assistant")}
              onClick={() => {
                setOpen(false);
                trigger.current?.focus();
              }}
            >
              <Icon name="x" />
            </button>
          </header>

          <div className="help__log" ref={log} aria-live="polite">
            {turns.length === 0 && (
              <div className="help__bubble help__bubble--bot">
                <p>
                  {t(
                    "أنا مساعد النظام. اسألني إزاي تعمل أي حاجة وأقولك الخطوات بالظبط على شاشاتنا.",
                    "I am the system assistant. Ask me how to do anything and I will give you the exact steps on our screens.",
                  )}
                </p>
                {home.data?.orders && (
                  <p>
                    {t(
                      "وتقدر كمان تديني أوامر (زي «اعمل شيفت من 9 لـ 5»): بجهّزها لك وماتتنفّذش غير لما تأكّد.",
                      "You can also give me orders (like \"make a shift from 9 to 5\"): I prepare them, and nothing runs until you confirm.",
                    )}
                  </p>
                )}
                {home.isPending && <div className="muted">...</div>}
                {home.data && home.data.starters.length > 0 && (
                  <>
                    <p className="muted">{t("جرّب واحد من دول:", "Try one of these:")}</p>
                    <div className="help__chips">{home.data.starters.map(chip)}</div>
                  </>
                )}
              </div>
            )}

            {turns.map((turn) => (
              <div className={`help__bubble help__bubble--${turn.who}${turn.problem ? " is-problem" : ""}`} key={turn.id}>
                {turn.who === "me" ? <p dir="auto">{turn.text}</p> : <Answer text={turn.text} />}
                {turn.open?.path && (
                  <Link className="btn btn--sm help__go" to={turn.open.path} onClick={followed}>
                    <Icon name="arrow-right" size="sm" />
                    <span>{t("افتح الصفحة", "Open the page")}</span>
                  </Link>
                )}
                {orderBox(turn)}
                {turn.related && turn.related.length > 0 && <div className="help__chips">{turn.related.map(chip)}</div>}
              </div>
            ))}

            {ask.isPending && (
              <div className="help__bubble help__bubble--bot help__typing" role="status" aria-label={t("بيكتب", "Typing")}>
                <span />
                <span />
                <span />
              </div>
            )}
          </div>

          {support && (
            <button type="button" className="btn btn--sm btn--ghost help__support" onClick={contactSupport}>
              <Icon name="message" size="sm" />
              <span>{t("تواصل مع الدعم الفني", "Contact technical support")}</span>
            </button>
          )}

          <form className="help__form" onSubmit={submit}>
            <textarea
              ref={box}
              className="input help__input"
              rows={1}
              value={text}
              maxLength={500}
              dir="auto"
              aria-label={t("اكتب سؤالك", "Type your question")}
              placeholder={t("اكتب سؤالك... مثلًا: إزاي أسجل حضور؟", "Ask... for example: how do I check in?")}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={keys}
            />
            <button type="submit" className="btn btn--primary" disabled={ask.isPending || text.trim() === ""} aria-label={t("إرسال", "Send")}>
              <Icon name="send" size="sm" />
            </button>
          </form>
          <div className="help__hint">{t("متكتبش بيانات عملاء ولا باسوردات هنا.", "Do not type client details or passwords here.")}</div>
        </section>
      )}
    </div>
  );
}
