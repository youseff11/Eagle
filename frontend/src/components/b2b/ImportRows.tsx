import { useState, type ChangeEvent } from "react";
import { refusalText, useAddRows, useReadRows, type B2bColumn, type B2bRow, type B2bSheetResponse } from "../../api/b2b";
import { usePreferences } from "../../i18n/Preferences";
import { Icon } from "../Icon";
import { Modal } from "../Modal";
import { useToasts } from "../Toasts";

type Columns = B2bSheetResponse["columns"];

/** The widths the grid gives the columns that are usually long. */
const WIDE: Partial<Record<B2bColumn, number>> = { company_name: 200, email: 200, website: 180, linkedin: 180, services: 180, languages: 150 };

/** The sheet's own fields a file may carry besides the columns (status, priority, deal value, notes): they come in as they
 * were read, and are named here for the list of columns found. */
const SHEET_FIELDS: Record<string, [string, string]> = {
  status: ["الحالة", "Status"],
  priority: ["الأولوية", "Priority"],
  deal_value: ["قيمة الصفقة", "Deal value"],
  notes: ["ملاحظات", "Notes"],
};

function emptyRow(columns: Columns): B2bRow {
  return Object.fromEntries(columns.map((column) => [column.name, ""])) as B2bRow;
}

/**
 * Companies brought in a block: an Excel (.xlsx) or CSV file - Google Sheets downloads either - or cells pasted from one.
 * The server reads it (`b2b_import`: the columns are found by their names, in Arabic or English) and writes nothing; the
 * rows come back into a grid where every cell can be corrected, a row taken out or one added, and only then are they added.
 */
function answerHas(rows: B2bRow[], name: string): boolean {
  return rows.some((row) => Boolean((row as Record<string, string>)[name]));
}

export function ImportRows({ sheetId, columns, onClose }: { sheetId: number; columns: Columns; onClose: () => void }) {
  const { t, lang } = usePreferences();
  const toasts = useToasts();
  const read = useReadRows(sheetId);
  const add = useAddRows(sheetId);
  const [text, setText] = useState("");
  const [link, setLink] = useState("");
  const [rows, setRows] = useState<B2bRow[] | null>(null);
  const [mapped, setMapped] = useState<string[]>([]);
  const [more, setMore] = useState(false);
  const [problem, setProblem] = useState("");
  const busy = read.isPending || add.isPending;
  const ready = (rows ?? []).filter((row) => row.company_name.trim() !== "");

  const take = (source: { file: File } | { text: string } | { link: string }) => {
    setProblem("");
    read.mutate(source, {
      onSuccess: (answer) => {
        setRows(answer.rows.length ? answer.rows : [emptyRow(columns)]);
        setMore(answer.more);
        setMapped(
          Object.entries(answer.mapped).map(([name, header]) => {
            const column = columns.find((one) => one.name === name);
            const field = SHEET_FIELDS[name];
            const shown = column ? (lang === "ar" ? column.ar : column.en) : field ? t(...field) : name;
            return `${header} → ${shown}`;
          }),
        );
      },
      onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش أقرا الملف.", "Could not read the file."))),
    });
  };

  const pick = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) take({ file });
  };

  const set = (index: number, name: B2bColumn, value: string) =>
    setRows((before) => (before ?? []).map((row, i) => (i === index ? { ...row, [name]: value } : row)));

  const submit = () => {
    if (busy || ready.length === 0) return;
    setProblem("");
    add.mutate(ready, {
      onSuccess: (answer) => {
        toasts.push({ level: "success", title: t(`اتضاف ${answer.added} شركة`, `${answer.added} companies added`) });
        onClose();
      },
      onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش أضيفهم. جرّب تاني.", "Could not add them. Try again."))),
    });
  };

  return (
    <Modal title={t("ارفع Excel أو Google Sheet", "Upload Excel or Google Sheets")} icon="upload" busy={busy} wide onClose={onClose}>
      {rows === null ? (
        <>
          <p className="muted">
            {t(
              "ارفع ملف Excel (.xlsx) أو CSV. من Google Sheets: File ← Download ← Microsoft Excel أو CSV. الأعمدة بتتعرف بأسمائها (Company، Phone، Email، الدولة...) فمش لازم تبقى بنفس الترتيب.",
              "Upload an Excel (.xlsx) or CSV file. From Google Sheets: File → Download → Microsoft Excel or CSV. Columns are found by their names (Company, Phone, Email, Country...), in any order.",
            )}
          </p>
          <label className="btn btn--primary" style={{ display: "inline-flex", marginBottom: 14 }}>
            <Icon name="upload" />
            {read.isPending ? t("بيتقري...", "Reading...") : t("اختار الملف", "Choose the file")}
            <input type="file" accept=".xlsx,.xlsm,.csv,.tsv,.txt" style={{ display: "none" }} aria-label={t("ملف Excel أو CSV", "Excel or CSV file")} disabled={busy} onChange={pick} />
          </label>
          <div className="field">
            <label htmlFor="import-link">{t("أو حط لينك الشيت من Google Sheets", "Or paste the Google Sheets link")}</label>
            <div className="row row--tight" style={{ flexWrap: "nowrap" }}>
              <input
                className="input grow"
                id="import-link"
                dir="ltr"
                maxLength={2000}
                placeholder="https://docs.google.com/spreadsheets/d/..."
                value={link}
                onChange={(event) => setLink(event.target.value)}
              />
              <button className="btn" type="button" disabled={busy || !link.trim()} onClick={() => take({ link: link.trim() })}>
                <Icon name="globe" />
                {t("اقرا الشيت", "Read the sheet")}
              </button>
            </div>
            <small className="muted">
              {t(
                "لازم الشيت يبقى مفتوح للّينك: في Google Sheets اضغط Share ← General access ← Anyone with the link.",
                "The sheet must be open to the link: in Google Sheets press Share → General access → Anyone with the link.",
              )}
            </small>
          </div>
          <div className="field">
            <label htmlFor="import-text">{t("أو الزق الصفوف هنا (منسوخة من الشيت)", "Or paste the rows here (copied from the sheet)")}</label>
            <textarea className="input mono" id="import-text" rows={6} dir="ltr" value={text} onChange={(event) => setText(event.target.value)} />
          </div>
          <button className="btn" type="button" disabled={busy || !text.trim()} onClick={() => take({ text })}>
            <Icon name="list-checks" />
            {t("اعرض الصفوف", "Show the rows")}
          </button>
        </>
      ) : (
        <>
          {mapped.length > 0 && (
            <div className="note note--info" style={{ marginBottom: 10 }}>
              <Icon name="info" />
              <div>
                {t("الأعمدة اللي اتعرفت:", "Columns found:")} <span className="mono">{mapped.join(" · ")}</span>
              </div>
            </div>
          )}
          {more && (
            <div className="note note--info" style={{ marginBottom: 10 }}>
              <Icon name="info" />
              <div>{t("الملف فيه أكتر من 500 صف: اتقرا أول 500. ارفع الباقي في ملف تاني.", "The file has more than 500 rows: the first 500 were read. Upload the rest in another file.")}</div>
            </div>
          )}
          <p className="muted">
            {t("عدّل أي خانة قبل ما تضيف. الصف من غير اسم شركة مش هيتضاف.", "Correct any cell before adding. A row with no company name is not added.")}
            {Object.keys(SHEET_FIELDS).some((name) => answerHas(rows, name)) &&
              t(" الحالة والأولوية وقيمة الصفقة والملاحظات بتدخل زي ما اتقرت، وتعدّلها بعدين في الشيت.", " The status, priority, deal value and notes come in as read; change them later on the sheet.")}
          </p>
          <div className="table-wrap" style={{ maxHeight: "55vh", overflow: "auto" }}>
            <table className="table" data-import-grid>
              <thead>
                <tr>
                  <th />
                  {columns.map((column) => (
                    <th key={column.name}>{lang === "ar" ? column.ar : column.en}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr key={index} data-import-row={index}>
                    <td>
                      <button
                        className="icon-btn"
                        type="button"
                        title={t("شيل الصف", "Remove the row")}
                        aria-label={t("شيل الصف", "Remove the row")}
                        onClick={() => setRows((before) => (before ?? []).filter((_row, i) => i !== index))}
                      >
                        <Icon name="x" />
                      </button>
                    </td>
                    {columns.map((column) => (
                      <td key={column.name}>
                        <input
                          className="input"
                          style={{ width: WIDE[column.name] ?? 130, padding: "4px 6px" }}
                          maxLength={column.max}
                          dir={["email", "phone", "whatsapp", "website", "linkedin"].includes(column.name) ? "ltr" : undefined}
                          aria-label={`${lang === "ar" ? column.ar : column.en} ${index + 1}`}
                          value={row[column.name]}
                          onChange={(event) => set(index, column.name, event.target.value)}
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row" style={{ marginTop: 10 }}>
            <button className="btn btn--sm" type="button" onClick={() => setRows((before) => [...(before ?? []), emptyRow(columns)])}>
              <Icon name="plus" />
              {t("صف جديد", "New row")}
            </button>
            <button className="btn btn--sm btn--ghost" type="button" onClick={() => setRows(null)}>
              {t("ملف تاني", "Another file")}
            </button>
            <div className="grow" />
            <span className="muted">{t(`${ready.length} شركة جاهزة تتضاف`, `${ready.length} companies ready to add`)}</span>
            <button className="btn btn--primary" type="button" disabled={busy || ready.length === 0} onClick={submit}>
              <Icon name="plus" />
              {t("ضيفهم", "Add them")}
            </button>
          </div>
        </>
      )}
      {problem && (
        <div className="note note--danger" role="alert" style={{ marginTop: 10 }}>
          <Icon name="alert" />
          <div>{problem}</div>
        </div>
      )}
    </Modal>
  );
}
