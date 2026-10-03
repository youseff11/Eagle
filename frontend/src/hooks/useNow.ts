import { useEffect, useState } from "react";

/** The time now (ms), drawn again every `everyMs`: for a line that counts ("2 hours left") and must keep moving. */
export function useNow(everyMs = 15000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), everyMs);
    return () => window.clearInterval(timer);
  }, [everyMs]);
  return now;
}
