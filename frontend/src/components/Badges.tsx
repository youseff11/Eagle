import type { Labelled } from "../api/types";
import { usePreferences } from "../i18n/Preferences";
import { Icon } from "./Icon";

/** The badge looks `static/css/app.css` has. The server names one; anything else is drawn plain. */
const TONES = new Set(["new", "wait", "info", "work", "review", "ok", "done", "dead"]);
const PRIORITIES = new Set(["low", "normal", "high", "urgent"]);
const DEADLINE_STATES = new Set(["none", "ok", "soon", "late", "done"]);

/** `deadline--soon` and the like: the class for a date, from the state the server worked out. */
export function deadlineClass(state: string): string {
  return `deadline--${DEADLINE_STATES.has(state) ? state : "none"}`;
}

export function StatusBadge({ status }: { status: Labelled & { tone: string } }) {
  const { lang } = usePreferences();
  const tone = TONES.has(status.tone) ? status.tone : "new";
  return (
    <span className={`badge badge--${tone}`}>
      <i className="badge__dot" />
      <span>{lang === "ar" ? status.ar : status.en}</span>
    </span>
  );
}

/** The star readout of a rating, as the classic pages draw it: two decimals, the third in the tooltip. */
export function Rating({ value }: { value: number }) {
  return (
    <span className="rating" title={`${value.toFixed(3)} / 5`}>
      <Icon name="star" size="sm" filled />
      <b>{value.toFixed(2)}</b>
      <i>/5</i>
    </span>
  );
}

export function PriorityBadge({ priority }: { priority: Labelled }) {
  const { lang } = usePreferences();
  if (!PRIORITIES.has(priority.value)) return null;
  return <span className={`badge badge--prio-${priority.value}`}>{lang === "ar" ? priority.ar : priority.en}</span>;
}

/** Where the job came from: WhatsApp or e-mail. */
export function OriginBadge({ origin }: { origin: (Labelled & { icon: string }) | null }) {
  const { lang } = usePreferences();
  if (!origin) return null;
  return (
    <span className={`badge badge--origin badge--${origin.value === "email" ? "mail" : "wa"}`}>
      <Icon name={origin.icon} size="sm" />
      <span>{lang === "ar" ? origin.ar : origin.en}</span>
    </span>
  );
}
