import { useEffect, useId, useRef, useState } from "react";
import { GROUPS, pushRecent, readRecent } from "../../lib/emoji";
import { usePreferences } from "../../i18n/Preferences";
import { Icon } from "../Icon";

/**
 * The button beside the box and the panel of emoji it opens, as WhatsApp has them: tabs for the groups, the ones used last first,
 * and a tap puts the emoji into the words at the cursor. The panel stays open while several are added; it closes on Escape, on a
 * press anywhere else, and with its own button.
 */
export function EmojiPicker({ disabled, onPick }: { disabled: boolean; onPick: (emoji: string) => void }) {
  const { t } = usePreferences();
  const [open, setOpen] = useState(false);
  const [recent, setRecent] = useState<string[]>(() => readRecent());
  const [group, setGroup] = useState(() => (readRecent().length > 0 ? "recent" : GROUPS[0]!.key));
  const root = useRef<HTMLDivElement>(null);
  const panel = useId();

  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  // A box that is switched off (the 24-hour window is closed) takes its panel with it.
  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  const choose = (emoji: string) => {
    setRecent(pushRecent(emoji));
    onPick(emoji);
  };

  const shown = group === "recent" ? recent : (GROUPS.find((one) => one.key === group)?.emoji ?? []);
  const label = t("إيموجي", "Emoji");

  return (
    <div className="emoji" ref={root}>
      <button
        type="button"
        className={`icon-btn${open ? " is-live" : ""}`}
        disabled={disabled}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panel : undefined}
        title={label}
        aria-label={label}
        onClick={() => setOpen((now) => !now)}
      >
        <Icon name="smile" />
      </button>

      {open && (
        <div className="emoji__pop" id={panel} role="dialog" aria-label={label}>
          <div className="emoji__tabs" role="tablist">
            {recent.length > 0 && (
              <button
                type="button"
                role="tab"
                aria-selected={group === "recent"}
                aria-label={t("اللي استخدمتهم", "Recent")}
                title={t("اللي استخدمتهم", "Recent")}
                className={`emoji__tab${group === "recent" ? " is-on" : ""}`}
                onClick={() => setGroup("recent")}
              >
                <Icon name="clock" size="sm" />
              </button>
            )}
            {GROUPS.map((one) => (
              <button
                type="button"
                role="tab"
                key={one.key}
                aria-selected={group === one.key}
                aria-label={t(...one.label)}
                title={t(...one.label)}
                className={`emoji__tab${group === one.key ? " is-on" : ""}`}
                onClick={() => setGroup(one.key)}
              >
                {one.tab}
              </button>
            ))}
          </div>
          <div className="emoji__grid" role="group" aria-label={label}>
            {shown.map((emoji) => (
              <button type="button" key={emoji} className="emoji__item" onClick={() => choose(emoji)}>
                {emoji}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
