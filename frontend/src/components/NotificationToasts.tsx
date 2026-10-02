import { useEffect, useRef } from "react";
import { useLatestNotifications } from "../api/queries";
import { usePreferences } from "../i18n/Preferences";
import { armSound, chime } from "../lib/chime";
import { useToasts } from "./Toasts";

/**
 * Shows a toast, and rings the chime, for every notification that arrives while the app is open:
 * what the classic pages do from their heartbeat (`tick` in static/js/app.js).
 *
 * The heartbeat of this app asks for no notifications (`useHeartbeat`), so this watches the same
 * list the notifications page shows. A doorbell on the socket asks for it again at once; with the
 * socket down it is asked every 15 seconds. What was already there when the page opened is not
 * announced, and neither is anything already read (opened on another tab, say).
 *
 * Nothing is drawn: the toasts belong to the `ToastProvider` this sits inside.
 */
export function NotificationToasts() {
  const { lang } = usePreferences();
  const { push } = useToasts();
  const query = useLatestNotifications();
  // The newest id already seen. `null` until the first answer, which is only what the page opened with.
  const seen = useRef<number | null>(null);

  useEffect(() => armSound(), []);

  useEffect(() => {
    const items = query.data?.items;
    if (!items) return;
    const newest = items.reduce((most, item) => Math.max(most, item.id), 0);
    if (seen.current === null) {
      seen.current = newest;
      return;
    }
    const before = seen.current;
    seen.current = Math.max(before, newest);
    // Oldest first, so the newest ends up at the bottom of the stack.
    const fresh = items.filter((item) => item.id > before && !item.read).sort((a, b) => a.id - b.id);
    if (fresh.length === 0) return;
    for (const item of fresh) {
      push({
        level: item.level,
        title: lang === "ar" ? item.title_ar : item.title_en,
        body: (lang === "ar" ? item.body_ar : item.body_en) || undefined,
        url: item.url,
        sticky: item.level === "danger",
      });
    }
    // One chime for the batch, not one per notification: a laptop that wakes up with six waiting
    // would otherwise ring for six seconds. The loud pair if any of them asked for a sound.
    if (fresh.some((item) => item.sound)) chime(2, 784);
    else chime(1, 988, true);
  }, [query.data, lang, push]);

  return null;
}
