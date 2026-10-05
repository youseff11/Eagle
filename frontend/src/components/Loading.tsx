import { useEffect, useState } from "react";
import { usePreferences } from "../i18n/Preferences";
import { Icon } from "./Icon";

/** How long a page waits for its data before it says it is loading: a load shorter than this shows nothing at all. */
export const LOADING_DELAY_MS = 450;

/** `false` for `ms` after the component first draws, then `true`. */
export function useAfter(ms: number): boolean {
  const [late, setLate] = useState(ms <= 0);
  useEffect(() => {
    if (ms <= 0) return;
    const timer = setTimeout(() => setLate(true), ms);
    return () => clearTimeout(timer);
  }, [ms]);
  return late;
}

/**
 * What a page draws while its data is on the way. It draws nothing for the first `LOADING_DELAY_MS`: most pages open on data
 * that is already here or arrives at once, and a card that flashes for a moment is worse than a page that is simply a moment
 * late (the bar at the top of the window says something is on its way). A page that really is slow shows a quiet turning
 * mark and no word on it (the words are there for a screen reader).
 */
export function Loading({ className = "card empty" }: { className?: string }) {
  const { t } = usePreferences();
  const late = useAfter(LOADING_DELAY_MS);
  if (!late) return null;
  return (
    <div className={className} role="status">
      <Icon name="refresh" size="xl" className="spin" />
      <span className="sr-only">{t("بيحمّل...", "Loading...")}</span>
    </div>
  );
}
