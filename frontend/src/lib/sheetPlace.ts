/**
 * Where a person was standing on a B2B sheet: its page and what it was showing (14/10/2026: on a 5000-row sheet the
 * Sales person walked to company 2000 with «التالي», wrote to it, and on coming back walked there again from the first
 * page). Kept in this browser for each sheet on its own; the search is not kept, it is a look for one company.
 */
const KEY = "eagle.sheet.place";

export type SheetPlace = { page: number; only: string };

const NOWHERE: SheetPlace = { page: 0, only: "all" };

function readAll(): Record<string, SheetPlace> {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(KEY) ?? "{}");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    return parsed as Record<string, SheetPlace>;
  } catch {
    return {};
  }
}

/** The place kept for this sheet, or its first page showing everything; `shows` says which views the page knows. */
export function readPlace(sheetId: number, shows: readonly string[]): SheetPlace {
  const kept: unknown = readAll()[String(sheetId)];
  if (!kept || typeof kept !== "object") return NOWHERE;
  const { page, only } = kept as Partial<SheetPlace>;
  return {
    page: typeof page === "number" && Number.isInteger(page) && page > 0 && page < 1000 ? page : 0,
    only: typeof only === "string" && shows.includes(only) ? only : "all",
  };
}

export function keepPlace(sheetId: number, place: SheetPlace): void {
  if (!sheetId) return;
  try {
    const all = readAll();
    if (place.page === 0 && place.only === "all") delete all[String(sheetId)];
    else all[String(sheetId)] = place;
    localStorage.setItem(KEY, JSON.stringify(all));
  } catch {
    // A private window: this visit only, then.
  }
}
