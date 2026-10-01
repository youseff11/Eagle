import { useEffect, useRef } from "react";
import { api } from "../api/client";
import type { HeartbeatResponse } from "../api/types";
import { CLASSIC_HOME, navigation } from "../lib/navigation";

/** Larger than any notification id, so the answer carries no notification rows. */
const NO_NOTIFICATIONS = 9007199254740991;

/**
 * Whether the answer says something is waiting that only the classic interface can show.
 *
 *  - an attendance screen: the mandatory check-in, which may not be skipped, and the
 *    check-out and extra-time reminders, which are not shown here and which a person who
 *    never sees them pays for with the whole day;
 *  - an assignment waiting for an answer: the accept screen has a 60-second clock,
 *    and a person who is shown as online but cannot see it loses the assignment and
 *    the rating penalty that comes with it;
 *  - a call that is ringing.
 *
 * The classic reminders can be put off, and the server does not hand a person back to this
 * app while one is still due (`newui.hand_on`), so sending them away cannot loop.
 */
export function needsClassicInterface(answer: HeartbeatResponse): boolean {
  return Boolean(answer.attendance) || Boolean(answer.pending) || Boolean(answer.call);
}

/**
 * The old pages' pulse, kept going while someone works in the new app.
 *
 * `/api/heartbeat/` is not only a poll: it records that this person is here
 * (the "online" dot the operation and team leaders see), runs the housekeeping
 * that expires unanswered assignments, and carries those screens. A person who
 * spent the day in this app and never sent it would show as absent; one who sent
 * it without reading the answer would show as present and miss them.
 *
 * It also carries `live`, the fingerprint of the boards. The classic list pages
 * fetch themselves again when it moves; `onLive` is how this app does the same: it
 * is called when the value *changes* (not on the first answer, which is only what
 * the page just loaded).
 */
export function useHeartbeat(pollMs: number, onLive?: () => void): void {
  const onLiveRef = useRef(onLive);
  useEffect(() => {
    onLiveRef.current = onLive;
  });

  useEffect(() => {
    let busy = false;
    let stamp: string | null = null;
    const beat = async () => {
      if (busy) return; // a slow answer must not pile up behind itself
      busy = true;
      try {
        const answer = await api<HeartbeatResponse>(`/api/heartbeat/?after=${NO_NOTIFICATIONS}`);
        if (needsClassicInterface(answer)) {
          navigation.assign(CLASSIC_HOME);
          return;
        }
        if (typeof answer.live === "string") {
          if (stamp !== null && answer.live !== stamp) onLiveRef.current?.();
          stamp = answer.live;
        }
      } catch {
        /* the next beat tries again */
      } finally {
        busy = false;
      }
    };
    void beat();
    const timer = window.setInterval(() => void beat(), Math.max(pollMs, 3000));
    return () => window.clearInterval(timer);
  }, [pollMs]);
}
