import type { LeadValues, ReadRowsResponse } from "../../api/b2b";

/** Cells copied from a spreadsheet come split by tabs: a paste that holds one is a row (or more), not a word for one box. */
export function isCopiedRow(text: string): boolean {
  return text.includes("\t");
}

/** A row the server read (`/read/`, each cell by what it holds) as the values to write: the filled ones, its note apart. */
export function filledValues(row: ReadRowsResponse["rows"][number]): { values: Partial<LeadValues>; note: string } {
  const { notes, ...rest } = row as Record<string, string>;
  const values = Object.fromEntries(Object.entries(rest).filter(([, value]) => value)) as Partial<LeadValues>;
  return { values, note: notes ?? "" };
}
