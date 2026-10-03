import { useEffect, useState } from "react";

/** How far the local clock may drift from what the server last said before it is set again (ms). */
const DRIFT = 2500;

/**
 * Whole seconds left, counted down in the browser from what the server said (`null` while there is nothing to count).
 *
 * The server is the authority - it refuses an answer that comes late - so this is only what the person sees:
 * it is set from `seconds` when `key` changes (another hand-off) and again whenever the server's number and
 * the local count disagree by more than a couple of seconds, and in between it runs by itself, once a second.
 */
export function useCountdown(seconds: number | null, key: unknown): number | null {
  const [ends, setEnds] = useState<{ key: unknown; at: number } | null>(null);
  const [, tick] = useState(0);

  useEffect(() => {
    if (seconds === null) {
      setEnds(null);
      return;
    }
    const fresh = Date.now() + seconds * 1000;
    setEnds((current) => (current && Object.is(current.key, key) && Math.abs(current.at - fresh) <= DRIFT ? current : { key, at: fresh }));
  }, [seconds, key]);

  const running = ends !== null;
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(timer);
  }, [running]);

  if (ends === null) return null;
  // The first render for a new hand-off, before the effect has set the end: what the server said.
  if (!Object.is(ends.key, key)) return seconds;
  return Math.max(0, Math.ceil((ends.at - Date.now()) / 1000));
}
