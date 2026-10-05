import { useIsFetching } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { usePreferences } from "../i18n/Preferences";

/** How long a page must be waiting before the bar shows: a page that opens at once never draws it. */
export const PROGRESS_DELAY_MS = 150;

/**
 * A thin bar at the top of the window while a page that has nothing to draw yet is waiting for its data. Only the first ask for
 * a thing counts (a query with no data): the asks that run again behind a page already drawn - the doorbell, the poll, a refresh
 * on coming back - never show it, so it means "this page is on its way" and nothing else.
 */
export function TopProgress() {
  const { t } = usePreferences();
  const waiting = useIsFetching({ predicate: (query) => query.state.data === undefined }) > 0;
  const [shown, setShown] = useState(false);

  useEffect(() => {
    if (!waiting) {
      setShown(false);
      return;
    }
    const timer = setTimeout(() => setShown(true), PROGRESS_DELAY_MS);
    return () => clearTimeout(timer);
  }, [waiting]);

  return shown ? <div className="top-progress" role="progressbar" aria-busy="true" aria-label={t("بيحمّل", "Loading")} /> : null;
}
