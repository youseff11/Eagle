/**
 * The shares the team leader gives when he hands a task to one translator or to several (07/10/2026).
 *
 * What he types here is the translator and - once more than one translator is on the task - which pages. The language pair is the task's
 * own (the operation says it) and the words are written afterwards, when the translation is with him for review (08/10/2026). These are
 * the rules the server enforces (`services.parse_parts`), asked here first so the button says what is missing before anything is sent.
 * The server stays the judge: a request that gets past this still meets it.
 */

export interface PartRow {
  /** Only for the list's keys: a row has no identity but its place. */
  key: number;
  translator: number | null;
  from: string;
  to: string;
}

/** A share already taken on the task (it stays when the new ones go out); only its pages matter to the new rows. */
export interface TakenShare {
  name: string;
  page_from: number | null;
  page_to: number | null;
}

type Say = (ar: string, en: string) => string;

const whole = (text: string) => (/^\d{1,12}$/.test(text.trim()) ? Number(text.trim()) : null);

/** The most translators one task is split between (the server's `MAX_PARTS`). */
export const MAX_PARTS = 10;

/**
 * What is wrong with each row, in order: an empty string means the row is fine. `taken` are the shares already out, so the pages
 * are asked as soon as the task would have more than one translator.
 */
export function rowProblems(rows: PartRow[], taken: TakenShare[], names: Map<number, string>, t: Say): string[] {
  const many = taken.length + rows.length > 1;
  const out: string[] = [];
  const ranges: { from: number; to: number; who: string }[] = taken
    .filter((share) => share.page_from !== null)
    .map((share) => ({ from: share.page_from as number, to: (share.page_to ?? share.page_from) as number, who: share.name }));
  const seen = new Set<number>();

  rows.forEach((row) => {
    if (row.translator === null) return void out.push(t("اختار مترجم.", "Pick a translator."));
    if (seen.has(row.translator)) return void out.push(t("المترجم ده اتكرر: كل مترجم ليه جزء واحد.", "This translator is listed twice: one share each."));
    seen.add(row.translator);

    const typed = row.from.trim() !== "" || row.to.trim() !== "";
    if (typed || many) {
      const from = whole(row.from);
      const to = whole(row.to);
      if (from === null || to === null || from < 1 || to < 1) {
        return void out.push(
          many ? t("اكتب من صفحة كام لحد صفحة كام.", "Type the first and the last page.") : t("اكتب الصفحتين: من وإلى.", "Type both pages: from and to."),
        );
      }
      if (from > to) return void out.push(t("الصفحة الأخيرة لازم تكون بعد الأولى أو نفسها.", "The last page must be after the first, or the same."));
      const name = names.get(row.translator) ?? "";
      const clash = ranges.find((range) => from <= range.to && range.from <= to);
      if (clash) {
        return void out.push(
          t(`الصفحات متداخلة مع ${clash.who || "مترجم تاني"} (${clash.from}-${clash.to}).`, `These pages overlap ${clash.who || "another translator"} (${clash.from}-${clash.to}).`),
        );
      }
      ranges.push({ from, to, who: name });
    }
    out.push("");
  });
  return out;
}

/** A words box as the server reads it: a whole number from 1 up, or `null`. */
export const wordsTyped = (text: string) => {
  const value = whole(text);
  return value !== null && value >= 1 ? value : null;
};
