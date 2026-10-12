import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { refusalText, useSaveCell, type B2bChoice, type B2bLead, type LeadValues } from "../../api/b2b";
import { usePreferences } from "../../i18n/Preferences";
import { useToasts } from "../Toasts";

/**
 * The company sheet drawn as the Sales team's own Google Sheet (12/10/2026): the same columns in the same order, the green
 * header, the black band under it and the peach rows. A cell is typed in where it stands and saves itself when the cursor
 * leaves it (or on Enter); the status and the priority are lists in the cell. Each cell sends itself alone
 * (`useSaveCell`), and a refusal puts the cell back as it was and says why.
 */

/** The sheet's own words for the status list and the priority, as the team writes them (the server's labels are English). */
export const STATUS_AR: Record<string, string> = {
  new: "عميل جديد",
  contacted: "تم التواصل",
  follow_up: "متابعة",
  won: "تم التعاقد",
  lost: "مرفوض",
  whatsapp: "whatsapp",
  visit: "زيارة",
  no_answer: "لم يتم الرد",
  call: "call",
};
export const PRIORITY_AR: Record<string, string> = {
  high: "عالية",
  medium: "متوسطة",
  low: "منخفضة",
};

/** The columns of the team's sheet, in its order, with the widths it gives them. */
export type GridColumn = "company_name" | "contact_person" | "phone" | "email" | "status" | "priority" | "deal_value" | "industry" | "notes" | "country";
export const GRID_COLUMNS: { name: GridColumn; ar: string; en: string; width: number; max: number; ltr?: boolean }[] = [
  { name: "company_name", ar: "الشركة", en: "Company", width: 290, max: 160 },
  { name: "contact_person", ar: "الشخص المسؤول", en: "Contact person", width: 150, max: 160 },
  { name: "phone", ar: "رقم الهاتف", en: "Phone", width: 160, max: 40, ltr: true },
  { name: "email", ar: "البريد الإلكتروني", en: "Email", width: 170, max: 254, ltr: true },
  { name: "status", ar: "الحالة", en: "Status", width: 150, max: 20 },
  { name: "priority", ar: "الأولوية", en: "Priority", width: 115, max: 10 },
  { name: "deal_value", ar: "قيمة الصفقة", en: "Deal value", width: 110, max: 20, ltr: true },
  { name: "industry", ar: "النشاط", en: "Activity", width: 110, max: 120 },
  { name: "notes", ar: "ملاحظات", en: "Notes", width: 320, max: 4000 },
  { name: "country", ar: "الدوله", en: "Country", width: 100, max: 80 },
];

function useCellSave(lead: B2bLead, name: keyof LeadValues) {
  const { t, lang } = usePreferences();
  const toasts = useToasts();
  const save = useSaveCell();
  return (value: string, undo: () => void) =>
    save.mutate(
      { id: lead.id, values: { [name]: value } },
      {
        onError: (failure) => {
          undo();
          toasts.push({ level: "danger", title: refusalText(failure, lang, t("الخانة ماتحفظتش. جرّب تاني.", "The cell was not saved. Try again.")) });
        },
      },
    );
}

/** A cell typed in: saved when the cursor leaves it or on Enter, put back on Escape. */
export function TextCell({ lead, name, label, max, ltr }: { lead: B2bLead; name: Exclude<GridColumn, "status" | "priority">; label: string; max: number; ltr?: boolean }) {
  const saved = lead[name];
  const [value, setValue] = useState(saved);
  const editing = useRef(false);
  // Escape: the blur that follows must not save what was typed (the value it sees is still the typed one).
  const dropped = useRef(false);
  const commit = useCellSave(lead, name);
  // What the server answers (this cell saved, or another person's edit) shows unless the cell is being typed in.
  useEffect(() => {
    if (!editing.current) setValue(saved);
  }, [saved]);

  const leave = () => {
    editing.current = false;
    if (dropped.current) {
      dropped.current = false;
      setValue(saved);
      return;
    }
    const next = value.trim();
    if (next === saved) {
      setValue(saved);
      return;
    }
    setValue(next);
    commit(next, () => setValue(saved));
  };
  const keys = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") event.currentTarget.blur();
    if (event.key === "Escape") {
      dropped.current = true;
      setValue(saved);
      event.currentTarget.blur();
    }
  };

  return (
    <input
      className="sheet__cell"
      value={value}
      maxLength={max}
      // A Latin name in an Arabic page keeps its dot at its end: each cell follows its own text.
      dir={ltr ? "ltr" : "auto"}
      inputMode={name === "deal_value" ? "decimal" : undefined}
      aria-label={`${label} · ${lead.company_name}`}
      title={value || undefined}
      onFocus={() => {
        editing.current = true;
      }}
      onChange={(event) => setValue(event.target.value)}
      onBlur={leave}
      onKeyDown={keys}
    />
  );
}

/** A list in the cell: the status or the priority, saved as soon as it is picked. */
export function ChoiceCell({ lead, name, label, choices, words, empty, children }: {
  lead: B2bLead;
  name: "status" | "priority";
  label: string;
  choices: B2bChoice[];
  words: Record<string, string>;
  empty?: boolean;
  children?: ReactNode;
}) {
  const { lang } = usePreferences();
  const saved = lead[name];
  const [value, setValue] = useState(saved);
  const commit = useCellSave(lead, name);
  useEffect(() => setValue(saved), [saved]);

  return (
    <>
      <select
        className={`sheet__cell sheet__cell--choice${name === "status" ? " sheet__cell--status" : ""}`}
        value={value}
        aria-label={`${label} · ${lead.company_name}`}
        data-value={value || "none"}
        onChange={(event) => {
          const next = event.target.value;
          setValue(next);
          commit(next, () => setValue(saved));
        }}
      >
        {empty && <option value="" />}
        {choices.map((choice) => (
          <option key={choice.value} value={choice.value}>
            {lang === "ar" ? (words[choice.value] ?? choice.label) : choice.label}
          </option>
        ))}
      </select>
      {children}
    </>
  );
}
