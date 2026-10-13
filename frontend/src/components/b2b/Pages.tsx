import { usePreferences } from "../../i18n/Preferences";

/** How many rows a long grid draws at once (13/10/2026: a sheet holds 5000 companies, and drawing them all froze the page). */
export const PAGE_ROWS = 100;

/** The page a grid is on, kept inside its rows when they get fewer (a row taken out, a search typed). */
export function pageWithin(page: number, count: number, size = PAGE_ROWS): number {
  return Math.min(page, Math.max(0, Math.ceil(count / size) - 1));
}

/** Previous and next under a long grid, and which rows are showing. Nothing when everything fits on one page. */
export function Pages({ page, count, size = PAGE_ROWS, onPage }: { page: number; count: number; size?: number; onPage: (page: number) => void }) {
  const { t } = usePreferences();
  const last = Math.max(0, Math.ceil(count / size) - 1);
  if (last === 0) return null;
  const from = page * size + 1;
  const to = Math.min(count, (page + 1) * size);
  return (
    <div className="row row--tight" style={{ justifyContent: "center", marginTop: 10 }} data-pages>
      <button className="btn btn--sm" type="button" disabled={page === 0} onClick={() => onPage(page - 1)}>
        {t("السابق", "Previous")}
      </button>
      <span className="muted mono">{t(`${from}–${to} من ${count}`, `${from}–${to} of ${count}`)}</span>
      <button className="btn btn--sm" type="button" disabled={page >= last} onClick={() => onPage(page + 1)}>
        {t("التالي", "Next")}
      </button>
    </div>
  );
}
