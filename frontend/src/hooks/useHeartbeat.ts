import { useEffect, useRef } from "react";
import { api } from "../api/client";
import type { AttendanceGate, CallInfo, HeartbeatResponse, PendingAssignment } from "../api/types";

/** Larger than any notification id, so the answer carries no notification rows. */
const NO_NOTIFICATIONS = 9007199254740991;

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

  useEffect(() => {
    let busy = false;
    let stamp: string | null = null;
    const beat = async () => {
      if (busy) return; // a slow answer must not pile up behind itself
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
