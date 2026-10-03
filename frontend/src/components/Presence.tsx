import type { PresenceState, Stamp } from "../api/types";
import { usePreferences } from "../i18n/Preferences";

/** What the board says for each state, and the dot it draws (`PRESENCE_STATES` in eagle_tags.py). */
const STATES: Record<PresenceState, { dot: string; ar: string; en: string }> = {
  free: { dot: "on", ar: "فاضي", en: "Free" },
  busy: { dot: "busy", ar: "مشغول", en: "Busy" },
  shift: { dot: "shift", ar: "في الشيفت — مش فاتح", en: "On shift — not open" },
  off: { dot: "off", ar: "أوفلاين", en: "Offline" },
};

/**
 * One person's state in a row: the dot, the word, and - for the two states where it matters - when they were last
 * here. Written by the server (it works out who is online); this only draws it.
 */
export function Presence({ state, seen }: { state: PresenceState; seen?: Stamp }) {
  const { lang } = usePreferences();
  const { dot, ar, en } = STATES[state] ?? STATES.off;
  // The board of who is free does not say when they were last here: the state is the answer it is read for.
  const when = seen ? (lang === "ar" ? seen.ar : seen.en) : "";
  return (
    <span className="presence" data-state={state} title={when}>
      <span className={`dot dot--${dot}`} />
      <small className="presence__state">{lang === "ar" ? ar : en}</small>
      {when && (state === "off" || state === "shift") && <small className="presence__seen">{when}</small>}
    </span>
  );
}
