import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { usePreferences } from "../../i18n/Preferences";

/** The six reactions, in WhatsApp's order (`services.REACTIONS`); the colours are the `r-<kind>` symbols of the sprite. */
export const REACTION_CHOICES: { kind: string; ar: string; en: string }[] = [
  { kind: "like", ar: "لايك", en: "Like" },
  { kind: "love", ar: "حب", en: "Love" },
  { kind: "laugh", ar: "ضحك", en: "Laugh" },
  { kind: "wow", ar: "واو", en: "Wow" },
  { kind: "sad", ar: "زعلان", en: "Sad" },
  { kind: "done", ar: "شكرًا", en: "Thanks" },
];

/**
 * The small bar of reactions that opens beside a bubble (the smile beside it, or the pill under it). Yours is lit:
 * tapping it again takes it back. It is placed from the bubble's own box, above it or - when that is off the top
 * of the screen - below it, and it closes on Escape, on a tap anywhere else, and when anything scrolls or the
 * window changes size (it is fixed to the screen, so it would be left behind).
 *
 * `trigger` is the button that opened it: a tap on it is not "elsewhere" (the page decides whether that closes
 * the bar), and the focus goes back to it when the bar closes by the keyboard.
 */
export function ReactionPicker({
  trigger,
  mine,
  onPick,
  onClose,
}: {
  trigger: HTMLElement;
  /** The kind this person has given to the message, or "". */
  mine: string;
  onPick: (kind: string) => void;
  onClose: () => void;
}) {
  const { t } = usePreferences();
  const node = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState<{ left: number; top: number } | null>(null);

  useLayoutEffect(() => {
    const bubble = trigger.closest(".bub");
    const box = bubble?.querySelector(".bub__box") ?? bubble ?? trigger;
    const rect = box.getBoundingClientRect();
    const width = node.current?.offsetWidth ?? 0;
    const height = node.current?.offsetHeight ?? 0;
    const left = Math.min(Math.max(8, rect.left + rect.width / 2 - width / 2), Math.max(8, window.innerWidth - width - 8));
    let top = rect.top - height - 6;
    if (top < 8) top = rect.bottom + 6;
    setPlace({ left, top });
  }, [trigger]);

  // Opening it puts the focus on the one that is lit, or the first.
  useEffect(() => {
    const buttons = Array.from(node.current?.querySelectorAll<HTMLButtonElement>("button") ?? []);
    (buttons.find((button) => button.classList.contains("is-on")) ?? buttons[0])?.focus();
  }, []);

  useEffect(() => {
    const away = (event: MouseEvent) => {
      const target = event.target as Element | null;
      if (node.current?.contains(target)) return;
      if (target?.closest?.("[data-react-open]")) return;
      onClose();
    };
    const escape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      onClose();
      if (trigger.isConnected) trigger.focus();
    };
    const close = () => onClose();
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    // Any scroll, of any container (it does not bubble: captured), and a window that changes shape.
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", escape);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [onClose, trigger]);

  // Left and right move between the six, as in any row of buttons.
  const walk = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("button"));
    const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (at === -1) return;
    event.preventDefault();
    const step = event.key === "ArrowRight" ? 1 : -1;
    buttons[(at + step + buttons.length) % buttons.length]?.focus();
  };

  return (
    <div
      className="react-picker"
      role="group"
      aria-label={t("رياكت", "React")}
      ref={node}
      onKeyDown={walk}
      style={place ? { left: place.left, top: place.top } : { visibility: "hidden" }}
    >
      {REACTION_CHOICES.map((choice) => {
        const label = t(choice.ar, choice.en);
        return (
          <button
            key={choice.kind}
            type="button"
            className={mine === choice.kind ? "is-on" : undefined}
            aria-pressed={mine === choice.kind}
            aria-label={label}
            title={label}
            onClick={() => onPick(choice.kind)}
          >
            <svg className="remoji remoji--lg" aria-hidden="true">
              <use href={`#r-${choice.kind}`} />
            </svg>
          </button>
        );
      })}
    </div>
  );
}
