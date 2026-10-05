import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { AHEAD_AGED_EVENT } from "../api/client";
import { askAhead } from "../api/intent";
import type { MeResponse } from "../api/types";

/**
 * The pointer coming to a link, a key reaching it, or a finger touching it: ask for its page now (`askAhead`). And when a page
 * was opened on an answer that had time to go stale, ask again behind it: the page is already drawn, so nothing shows.
 */
export function useAskAhead(me: MeResponse | undefined): void {
  const client = useQueryClient();
  useEffect(() => {
    let timer: number | undefined;
    const onAged = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => void client.invalidateQueries(), 150);
    };
    window.addEventListener(AHEAD_AGED_EVENT, onAged);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener(AHEAD_AGED_EVENT, onAged);
    };
  }, [client]);

  useEffect(() => {
    if (!me) return;
    const onIntent = (event: Event) => {
      const target = event.target;
      const link = target instanceof Element ? target.closest("a[href]") : null;
      if (!(link instanceof HTMLAnchorElement)) return;
      let url: URL;
      try {
        url = new URL(link.href, window.location.href);
      } catch {
        return;
      }
      if (url.origin !== window.location.origin) return;
      void askAhead(client, url.pathname, me);
    };
    const options = { passive: true } as const;
    document.addEventListener("pointerover", onIntent, options);
    document.addEventListener("focusin", onIntent);
    document.addEventListener("touchstart", onIntent, options);
    return () => {
      document.removeEventListener("pointerover", onIntent);
      document.removeEventListener("focusin", onIntent);
      document.removeEventListener("touchstart", onIntent);
    };
  }, [client, me]);
}
