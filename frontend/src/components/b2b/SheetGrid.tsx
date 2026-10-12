import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { refusalText, useAddNote, useDeleteNote, useSaveCell, type B2bChoice, type B2bLead, type B2bNote, type LeadValues } from "../../api/b2b";
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
export type GridColumn = "company_name" | "contact_person" | "phone" | "whatsapp" | "email" | "status" | "priority" | "deal_value" | "industry" | "notes" | "country";
export const GRID_COLUMNS: { name: GridColumn; ar: string; en: string; width: number; max: number; ltr?: boolean; multiline?: boolean }[] = [
  { name: "company_name", ar: "الشركة", en: "Company", width: 290, max: 160 },
  { name: "contact_person", ar: "الشخص المسؤول", en: "Contact person", width: 150, max: 160 },
  { name: "phone", ar: "رقم الهاتف", en: "Phone", width: 160, max: 250, ltr: true, multiline: true },
  { name: "whatsapp", ar: "واتساب", en: "WhatsApp", width: 160, max: 250, ltr: true, multiline: true },
  { name: "email", ar: "البريد الإلكتروني", en: "Email", width: 170, max: 254, ltr: true },
  { name: "status", ar: "الحالة", en: "Status", width: 150, max: 20 },
  { name: "priority", ar: "الأولوية", en: "Priority", width: 115, max: 10 },
  { name: "deal_value", ar: "قيمة الصفقة", en: "Deal value", width: 110, max: 20, ltr: true },
  { name: "industry", ar: "النشاط", en: "Activity", width: 110, max: 120 },
  { name: "notes", ar: "ملاحظات", en: "Notes", width: 340, max: 4000 },
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

/** The lines a multi-line cell keeps: each one trimmed, the empty ones dropped. */
function tidyLines(value: string): string {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .join("\n");
}

/**
 * A cell typed in: saved when the cursor leaves it, put back on Escape. A one-line cell also saves on Enter; a multi-line
 * one (the phone numbers and the notes: a company has more than one of each) takes Enter as a new line, one number or one
 * note a line.
 */
export function TextCell({ lead, name, label, max, ltr, multiline }: {
  lead: B2bLead;
  name: Exclude<GridColumn, "status" | "priority" | "notes">;
  label: string;
  max: number;
  ltr?: boolean;
  multiline?: boolean;
}) {
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
    const next = multiline ? tidyLines(value) : value.trim();
    if (next === saved) {
      setValue(saved);
      return;
    }
    setValue(next);
    commit(next, () => setValue(saved));
  };
  const keys = (event: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !multiline) event.currentTarget.blur();
    if (event.key === "Escape") {
      dropped.current = true;
      setValue(saved);
      event.currentTarget.blur();
    }
  };

  const common = {
    value,
    maxLength: max,
    // A Latin name in an Arabic page keeps its dot at its end: each cell follows its own text.
    dir: ltr ? "ltr" : "auto",
    "aria-label": `${label} · ${lead.company_name}`,
    title: value || undefined,
    onFocus: () => {
      editing.current = true;
    },
    onBlur: leave,
    onKeyDown: keys,
  };
  if (multiline) {
    return (
      <textarea
        {...common}
        className="sheet__cell sheet__cell--lines"
        rows={Math.max(1, value.split("\n").length)}
        onChange={(event) => setValue(event.target.value)}
      />
    );
  }
  return <input {...common} className="sheet__cell" inputMode={name === "deal_value" ? "decimal" : undefined} onChange={(event) => setValue(event.target.value)} />;
}

/** One note: its day, its words, and (for its writer, the manager and the owner) a way to take it off, asked twice. */
function NoteLine({ note, lead, mayDelete }: { note: B2bNote; lead: B2bLead; mayDelete: boolean }) {
  const { t, lang } = usePreferences();
  const toasts = useToasts();
  const remove = useDeleteNote();
  const [sure, setSure] = useState(false);
  const who = note.by?.name ?? t("قبل التحديث", "From before");

  return (
    <div className="sheet__note" data-note={note.id}>
      <span className="sheet__note-day mono" title={`${note.at} · ${who}`}>
        {note.day}
      </span>
      <span className="sheet__note-text" dir="auto">
        {note.text}
      </span>
      {mayDelete && (
        <button
          className={`sheet__note-x${sure ? " is-sure" : ""}`}
          type="button"
          disabled={remove.isPending}
          aria-label={sure ? t("أكيد امسحها", "Yes, delete it") : t("امسح الملاحظة", "Delete the note") + ` · ${lead.company_name}`}
          title={sure ? t("أكيد امسحها", "Yes, delete it") : t("امسح الملاحظة", "Delete the note")}
          onBlur={() => setSure(false)}
          onClick={() => {
            if (!sure) {
              setSure(true);
              return;
            }
            remove.mutate(note.id, {
              onError: (failure) => {
                setSure(false);
                toasts.push({ level: "danger", title: refusalText(failure, lang, t("الملاحظة ماتمسحتش.", "The note was not deleted.")) });
              },
            });
          }}
        >
          {sure ? t("امسح؟", "Delete?") : "×"}
        </button>
      )}
    </div>
  );
}

/** The notes cell: every note on its own line with the day it was written, and a line at the bottom to write a new one
 * (Enter adds it). A note is never written over: it is added, or taken off. */
export function NotesCell({ lead, label, meId, manages }: { lead: B2bLead; label: string; meId: number; manages: boolean }) {
  const { t, lang } = usePreferences();
  const toasts = useToasts();
  const add = useAddNote();
  const [text, setText] = useState("");

  const submit = () => {
    const words = text.trim();
    if (!words || add.isPending) return;
    add.mutate(
      { id: lead.id, text: words },
      {
        onSuccess: () => setText(""),
        onError: (failure) =>
          toasts.push({ level: "danger", title: refusalText(failure, lang, t("الملاحظة ماتسجلتش. جرّب تاني.", "The note was not saved. Try again.")) }),
      },
    );
  };

  return (
    <div className="sheet__notes">
      {lead.notes.map((note) => (
        <NoteLine key={note.id} note={note} lead={lead} mayDelete={manages || note.by?.id === meId} />
      ))}
      <input
        className="sheet__cell sheet__note-new"
        value={text}
        maxLength={4000}
        dir="auto"
        placeholder={t("+ ملاحظة جديدة", "+ New note")}
        aria-label={`${label} · ${lead.company_name}`}
        disabled={add.isPending}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            submit();
          }
          if (event.key === "Escape") setText("");
        }}
      />
    </div>
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
