import { useEffect, useRef } from "react";
import { api } from "../api/client";
import type { AttendanceGate, CallInfo, HeartbeatResponse, PendingAssignment } from "../api/types";
import { onBeatNow } from "../lib/beat";
import { useRealtimeStatus } from "../realtime/RealtimeProvider";

/** Larger than any notification id, so the answer carries no notification rows. */
const NO_NOTIFICATIONS = 9007199254740991;

/**
 * The pace while the socket is open. Each beat was ~20 queries and, on the host, a fresh connection to the database; at
 * one every 3 s in every open tab that traffic paused the database (15/10/2026). With the socket open what is urgent
 * comes with a doorbell (`lib/beat`), so the beat only keeps the presence dot and the check-in screen.
 */
export const LIVE_BEAT_MS = 30000;
/** The floor, and the pace while the socket is down: then nothing rings, and the beat is how anything arrives. */
export const MIN_BEAT_MS = 3000;
/** How long after a hand-off's window ends the page asks again, so the server takes it back on time. */
export const EXPIRY_GRACE_MS = 1500;

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
 *
 * And it carries `pending`, the hand-off waiting for an answer: `onPending` is told what every beat
 * says - the hand-off, or `null` when there is none - so the accept screen appears within a beat of the
 * assignment and goes away within a beat of the answer. `onGate` is the same for the check-in screen: what it
 * asks (or `null`) when this app draws it. `onCall` is told the call that is ringing for this person (said again on every
 * beat while it rings: the one who takes it knows to ignore what is already on the screen). A beat that failed says
 * nothing, and leaves what was shown as it was: the next one tells the truth.
 *
 * Its pace: every `LIVE_BEAT_MS` while the socket is open, and at once whenever a doorbell rings (`lib/beat`); every
 * `pollMs` (3 s at the least) while the socket is down, which is how it always was.
 */
export function useHeartbeat(
  pollMs: number,
  onLive?: () => void,
  onPending?: (pending: PendingAssignment | null) => void,
  onGate?: (gate: AttendanceGate | null) => void,
  onCall?: (call: CallInfo | null) => void,
): void {
  const onLiveRef = useRef(onLive);
  const onPendingRef = useRef(onPending);
  const onGateRef = useRef(onGate);
  const onCallRef = useRef(onCall);
  useEffect(() => {
    onLiveRef.current = onLive;
    onPendingRef.current = onPending;
    onGateRef.current = onGate;
    onCallRef.current = onCall;
  });

  const live = useRealtimeStatus() === "open";
  const every = Math.max(pollMs, live ? LIVE_BEAT_MS : MIN_BEAT_MS);

  useEffect(() => {
    let busy = false;
    let again = false;
    let stopped = false;
    let early: number | undefined;
    let stamp: string | null = null;
    /** `rung`: asked by a doorbell. A slow answer must not pile up behind itself; but a doorbell that rang meanwhile is
     * asked once it is in, because the answer on its way may have been read before what the doorbell rang for. */
    const beat = async (rung = false) => {
      if (busy) {
        if (rung) again = true;
        return;
      }
      busy = true;
      try {
        const answer = await api<HeartbeatResponse>(`/api/heartbeat/?after=${NO_NOTIFICATIONS}`);
        onPendingRef.current?.(answer.pending ?? null);
        onCallRef.current?.(answer.call ?? null);
        onGateRef.current?.(answer.attendance ?? null);
        if (typeof answer.live === "string") {
          if (stamp !== null && answer.live !== stamp) onLiveRef.current?.();
          stamp = answer.live;
        }
        // A hand-off on the screen: ask again just after its window ends, so the server takes it back on time.
        window.clearTimeout(early);
        const left = answer.pending?.seconds_left;
        if (typeof left === "number" && !stopped) {
          const due = Math.max(left * 1000 + EXPIRY_GRACE_MS, MIN_BEAT_MS);
          if (due < every) early = window.setTimeout(() => void beat(), due);
        }
      } catch {
        /* the next beat tries again */
      } finally {
        busy = false;
      }
      if (again && !stopped) {
        again = false;
        void beat(true);
      }
    };
    const off = onBeatNow(() => {
      if (!stopped) void beat(true);
    });
    void beat();
    const timer = window.setInterval(() => void beat(), every);
    return () => {
      stopped = true;
      window.clearInterval(timer);
      window.clearTimeout(early);
      off();
    };
  }, [every]);
}
