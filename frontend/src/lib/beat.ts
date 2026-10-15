/**
 * "Ask the heartbeat now": the socket's doorbells (`RealtimeProvider`) ring it, the heartbeat (`useHeartbeat`) listens.
 *
 * While the socket is open the heartbeat beats only every 30 s, so what it alone carries - the hand-off to accept and
 * a colleague's call - would be up to 30 s late. Every one of those comes with a doorbell, and the doorbell asks at once.
 */

const BEAT_NOW = "eagle:beat-now";

export function beatNow(): void {
  window.dispatchEvent(new Event(BEAT_NOW));
}

export function onBeatNow(listener: () => void): () => void {
  window.addEventListener(BEAT_NOW, listener);
  return () => window.removeEventListener(BEAT_NOW, listener);
}
