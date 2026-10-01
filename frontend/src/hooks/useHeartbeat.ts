import { useEffect } from "react";
import { api } from "../api/client";
import type { HeartbeatResponse } from "../api/types";
import { navigation } from "../lib/navigation";

/** Larger than any notification id, so the answer carries no notification rows. */
const NO_NOTIFICATIONS = 9007199254740991;

/**
 * Whether the answer says something is waiting that only the classic interface can show.
 *
 *  - the mandatory check-in screen, which may not be skipped;
 *  - an assignment waiting for an answer: the accept screen has a 60-second clock,
 *    and a person who is shown as online but cannot see it loses the assignment and
 *    the rating penalty that comes with it;
 *  - a call that is ringing.
 *
 * The check-out and extra-time reminders can be put off in the classic interface and
 * are not shown here yet, so they do not send anyone away.
 */
export function needsClassicInterface(answer: HeartbeatResponse): boolean {
  return answer.attendance?.kind === "check_in" || Boolean(answer.pending) || Boolean(answer.call);
}

/**
 * The old pages' pulse, kept going while someone works in the new app.
 *
 * `/api/heartbeat/` is not only a poll: it records that this person is here
 * (the "online" dot the operation and team leaders see), runs the housekeeping
 * that expires unanswered assignments, and carries those screens. A person who
 * spent the day in this app and never sent it would show as absent; one who sent
 * it without reading the answer would show as present and miss them.
 */
export function useHeartbeat(pollMs: number): void {
  useEffect(() => {
    let busy = false;
    const beat = async () => {
      if (busy) return; // a slow answer must not pile up behind itself
      busy = true;
      try {
        const answer = await api<HeartbeatResponse>(`/api/heartbeat/?after=${NO_NOTIFICATIONS}`);
        if (needsClassicInterface(answer)) navigation.assign("/");
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
