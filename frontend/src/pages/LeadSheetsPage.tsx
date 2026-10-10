import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router";
import { refusalText, useB2bSheets, useCreateSheet, type B2bPerson } from "../api/b2b";
import { useMe } from "../api/queries";
import { Icon } from "../components/Icon";
import { Loading } from "../components/Loading";
import { usePreferences } from "../i18n/Preferences";

/** The manager's box for a new sheet: a name, the Sales person who gets it, and what the manager wants from it. */
function NewSheet({ sales }: { sales: B2bPerson[] }) {
  const { t, lang } = usePreferences();
  const navigate = useNavigate();
  const create = useCreateSheet();
  const [title, setTitle] = useState("");
  const [person, setPerson] = useState("");
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (create.isPending) return;
    setProblem("");
    create.mutate(
      { title: title.trim(), note: note.trim(), assigned_to: Number(person) },
      {
        onSuccess: (answer) => navigate(`/leads/${answer.sheet.id}`),
        onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش أعمل الشيت. جرّب تاني.", "Could not make the sheet. Try again."))),
      },
    );
  };

  return (
    <form className="card" onSubmit={submit} style={{ marginBottom: 14 }}>
      <div className="card__head">
        <Icon name="plus" />
        <h3>{t("شيت جديد", "New sheet")}</h3>
      </div>
      <div className="grid grid--main">
        <div className="field">
          <label htmlFor="sheetTitle">{t("اسم الشيت", "Sheet name")}</label>
          <input
            className="input"
            id="sheetTitle"
            maxLength={160}
            value={title}
            placeholder={t("مثلًا: شركات ترجمة ألمانيا", "e.g. Translation agencies, Germany")}
            onChange={(event) => setTitle(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="sheetSales">{t("الـSales اللي هياخده", "Sales person")}</label>
          <select className="input" id="sheetSales" value={person} onChange={(event) => setPerson(event.target.value)}>
            <option value="">{t("— اختار —", "— choose —")}</option>
            {sales.map((one) => (
              <option key={one.id} value={one.id}>
                {one.name}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="field">
        <label htmlFor="sheetNote">{t("المطلوب منه (اختياري)", "What you want from it (optional)")}</label>
        <textarea className="input" id="sheetNote" rows={2} maxLength={2000} value={note} onChange={(event) => setNote(event.target.value)} />
      </div>
      {problem && (
        <div className="note note--danger" role="alert" style={{ marginBottom: 10 }}>
          <Icon name="alert" />
          <div>{problem}</div>
        </div>
      )}
      <button className="btn btn--primary" type="submit" disabled={create.isPending}>
        <Icon name="plus" />
        {t("اعمل الشيت", "Make the sheet")}
      </button>
    </form>
  );
}

/**
 * The B2B company sheets: a Sales person's own, or - for the Sales manager and the owner - all of them, with the box that
 * makes a new one. Titles and counts only: the companies are on the sheet's own page.
 */
export function LeadSheetsPage() {
  const { t } = usePreferences();
  const me = useMe();
  const allowed = me.data !== undefined && (me.data.user.role === "sales" || me.data.user.is_admin);
  const list = useB2bSheets(allowed);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  const data = list.data;

  return (
    <>
      <div className="page-head">
        <h1>{t("شيتات الشركات", "Company sheets")}</h1>
        <span className="page-head__sub">
          {t(
            "الشركات اللي بنتواصل معاها (B2B). الواتساب والإيميل اللي بيتبعتوا من الشيت بيتعلّموا لوحدهم، والمكالمة بتتسجّل بإيدك.",
            "The companies we reach out to (B2B). WhatsApp and e-mail sent from a sheet are marked by themselves; a call is logged by hand.",
          )}
        </span>
      </div>

      {data?.can_manage && <NewSheet sales={data.sales} />}

      <div className="card">
        {data ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("الشيت", "Sheet")}</th>
                  <th>{t("الـSales", "Sales person")}</th>
                  <th>{t("الشركات", "Companies")}</th>
                  <th>{t("اتواصلنا معاهم", "Contacted")}</th>
                  <th>{t("اتعمل", "Made")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.sheets.map((sheet) => (
                  <tr key={sheet.id} data-sheet={sheet.id}>
                    <td>
                      <strong>{sheet.title}</strong>
                      {sheet.note && <div className="muted">{sheet.note}</div>}
                    </td>
                    <td>{sheet.assigned_to?.name ?? "—"}</td>
                    <td className="mono">{sheet.rows}</td>
                    <td className="mono">
                      {sheet.contacted} / {sheet.rows}
                    </td>
                    <td className="mono">{sheet.created_at}</td>
                    <td>
                      <Link className="btn btn--sm" to={`/leads/${sheet.id}`}>
                        {t("افتح", "Open")}
                      </Link>
                    </td>
                  </tr>
                ))}
                {data.sheets.length === 0 && (
                  <tr>
                    <td colSpan={6} className="empty">
                      <Icon name="building" size="xl" />
                      <span>
                        {data.can_manage
                          ? t("مفيش شيتات لسه. اعمل أول واحد من فوق.", "No sheets yet. Make the first one above.")
                          : t("مفيش شيتات ليك لسه. المانجر هيبعتلك.", "No sheets for you yet. Your manager will send one.")}
                      </span>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        ) : list.isError ? (
          <div className="empty" role="alert">
            <Icon name="alert" size="xl" />
            <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
          </div>
        ) : (
          <Loading className="empty" />
        )}
      </div>
    </>
  );
}
