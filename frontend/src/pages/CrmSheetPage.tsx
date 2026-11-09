import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router";
import { refusalText } from "../api/b2b";
import {
  dialable,
  parseCrmLines,
  useAddCrmRows,
  useCrmSheet,
  useCrmWhatsapp,
  useDeleteCrmRow,
  useSaveCrmRow,
  useSaveCrmSheet,
  type CrmPerson,
  type CrmRow,
  type CrmStatus,
  type CrmStatusChoice,
} from "../api/crm";
import { useMe } from "../api/queries";
import { Icon } from "../components/Icon";
import { Loading } from "../components/Loading";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

/** The manager's box that adds rows: typed or pasted, one person a line. */
function AddRows({ sheetId, onDone }: { sheetId: number; onDone: () => void }) {
  const { t, lang } = usePreferences();
  const add = useAddCrmRows(sheetId);
  const [text, setText] = useState("");
  const [problem, setProblem] = useState("");
  const rows = parseCrmLines(text);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (add.isPending || rows.length === 0) return;
    setProblem("");
    add.mutate(rows, {
      onSuccess: () => {
        setText("");
        onDone();
      },
      onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش أضيف الصفوف. جرّب تاني.", "Could not add the rows. Try again."))),
    });
  };

  return (
    <form className="card" onSubmit={submit} style={{ marginBottom: 14 }}>
      <div className="card__head">
        <Icon name="plus" />
        <h3>{t("ضيف صفوف", "Add rows")}</h3>
      </div>
      <div className="field">
        <label htmlFor="crmLines">{t("كل واحد في سطر: الاسم وبعده الرقم (أو الصقهم من Excel)", "One person a line: the name then the number (or paste them from Excel)")}</label>
        <textarea className="input" id="crmLines" rows={5} value={text} onChange={(event) => setText(event.target.value)} />
      </div>
      {problem && (
        <div className="note note--danger" role="alert" style={{ marginBottom: 10 }}>
          <Icon name="alert" />
          <div>{problem}</div>
        </div>
      )}
      <button className="btn btn--primary" type="submit" disabled={add.isPending || rows.length === 0}>
        <Icon name="plus" />
        {rows.length > 0 ? t(`ضيف ${rows.length}`, `Add ${rows.length}`) : t("ضيف", "Add")}
      </button>
    </form>
  );
}

/** A cell the manager corrects: saved when the box is left with something new in it. */
function EditCell({ value, label, ltr, onSave }: { value: string; label: string; ltr?: boolean; onSave: (next: string) => void }) {
  const [draft, setDraft] = useState(value);
  return (
    <input
      className={`input${ltr ? " mono" : ""}`}
      dir={ltr ? "ltr" : undefined}
      aria-label={label}
      value={draft}
      maxLength={ltr ? 40 : 160}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={() => {
        if (draft.trim() !== value) onSave(draft.trim());
      }}
    />
  );
}

function Row({
  row,
  statuses,
  canManage,
  canContact,
  onProblem,
}: {
  row: CrmRow;
  statuses: CrmStatusChoice[];
  canManage: boolean;
  canContact: boolean;
  onProblem: (words: string) => void;
}) {
  const { t, lang } = usePreferences();
  const navigate = useNavigate();
  const save = useSaveCrmRow();
  const remove = useDeleteCrmRow();
  const whatsapp = useCrmWhatsapp();
  const failed = (fallback: string) => (failure: unknown) => onProblem(refusalText(failure, lang, fallback));
  const write = (values: { status?: CrmStatus; name?: string; phone?: string }) =>
    save.mutate({ id: row.id, ...values }, { onError: failed(t("مقدرتش أحفظ. جرّب تاني.", "Could not save. Try again.")) });
  const number = dialable(row.phone);

  return (
    <tr data-crm-row={row.id}>
      <td>{canManage ? <EditCell value={row.name} label={t("الاسم", "Name")} onSave={(name) => write({ name })} /> : row.name || "—"}</td>
      <td className="mono" dir="ltr">
        {canManage ? <EditCell value={row.phone} label={t("رقم التليفون", "Phone")} ltr onSave={(phone) => write({ phone })} /> : row.phone || "—"}
      </td>
      <td>
        <select
          className="input"
          aria-label={t("الحالة", "Status")}
          value={row.status}
          disabled={save.isPending}
          onChange={(event) => write({ status: event.target.value as CrmStatus })}
        >
          <option value="">{t("— لسه —", "— not yet —")}</option>
          {statuses.map((status) => (
            <option key={status.value} value={status.value}>
              {lang === "en" ? status.en : status.ar}
            </option>
          ))}
        </select>
      </td>
      <td>
        <div className="row row--tight" style={{ flexWrap: "nowrap" }}>
          {number ? (
            <a className="btn btn--sm" href={`tel:${number}`}>
              <Icon name="phone" size="sm" />
              {t("اتصل", "Call")}
            </a>
          ) : null}
          {canContact && number ? (
            <button
              className="btn btn--sm"
              type="button"
              disabled={whatsapp.isPending}
              onClick={() =>
                whatsapp.mutate(row.id, {
                  onSuccess: (answer) => navigate(`/chats/${encodeURIComponent(answer.chat)}`),
                  onError: failed(t("مقدرتش أفتح الواتساب. جرّب تاني.", "Could not open WhatsApp. Try again.")),
                })
              }
            >
              <Icon name="message" size="sm" />
              {t("واتساب", "WhatsApp")}
            </button>
          ) : null}
          {canManage && (
            <button
              className="btn btn--sm btn--ghost"
              type="button"
              aria-label={`${t("امسح الصف", "Delete the row")} ${row.name || row.phone}`}
              title={t("امسح الصف", "Delete the row")}
              disabled={remove.isPending}
              onClick={() => remove.mutate(row.id, { onError: failed(t("مقدرتش أمسح الصف.", "Could not delete the row.")) })}
            >
              <Icon name="trash" size="sm" />
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}

/** Who holds the sheet: the manager hands it on from here. */
function Holder({ sheetId, holder, holders }: { sheetId: number; holder: CrmPerson | null; holders: CrmPerson[] }) {
  const { t, lang } = usePreferences();
  const save = useSaveCrmSheet(sheetId);
  const toasts = useToasts();
  return (
    <div className="field" style={{ maxWidth: 320 }}>
      <label htmlFor="crmSheetHolder">{t("صاحب الشيت", "Sheet holder")}</label>
      <select
        className="input"
        id="crmSheetHolder"
        value={holder?.id ?? ""}
        disabled={save.isPending}
        onChange={(event) =>
          save.mutate(
            { assigned_to: Number(event.target.value) },
            {
              onSuccess: () => toasts.push({ level: "success", title: t("الشيت اتحوّل", "The sheet was handed on") }),
              onError: (failure) => toasts.push({ level: "danger", title: refusalText(failure, lang, t("مقدرتش أحوّل الشيت.", "Could not hand the sheet on.")) }),
            },
          )
        }
      >
        {holders.map((one) => (
          <option key={one.id} value={one.id}>
            {one.name}
          </option>
        ))}
      </select>
    </div>
  );
}

/** One CRM sheet: the name, the phone, the status and the contact buttons. Nothing more, as the owner asked. */
export function CrmSheetPage() {
  const { t } = usePreferences();
  const me = useMe();
  const params = useParams();
  const id = Number(params.id) || 0;
  const allowed = me.data !== undefined && (me.data.user.role === "crm" || me.data.user.is_admin);
  const sheet = useCrmSheet(allowed ? id : 0);
  const [problem, setProblem] = useState("");

  if (me.data && !allowed) return <Navigate to="/" replace />;
  const data = sheet.data;

  return (
    <>
      <div className="page-head">
        <Link className="btn btn--sm btn--ghost" to="/crm">
          {t("شيتات CRM", "CRM sheets")}
        </Link>
        <h1>{data?.sheet.title ?? t("شيت CRM", "CRM sheet")}</h1>
        {data && <span className="page-head__sub">{data.sheet.assigned_to?.name ?? ""}</span>}
      </div>

      {data?.can_manage && (
        <>
          <Holder sheetId={id} holder={data.sheet.assigned_to} holders={data.holders} />
          <AddRows sheetId={id} onDone={() => setProblem("")} />
        </>
      )}

      {problem && (
        <div className="note note--danger" role="alert" style={{ marginBottom: 10 }}>
          <Icon name="alert" />
          <div>{problem}</div>
        </div>
      )}

      <div className="card">
        {data ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("الاسم", "Name")}</th>
                  <th>{t("رقم التليفون", "Phone")}</th>
                  <th>{t("الحالة", "Status")}</th>
                  <th>{t("التواصل", "Contact")}</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <Row key={row.id} row={row} statuses={data.statuses} canManage={data.can_manage} canContact={data.can_contact} onProblem={setProblem} />
                ))}
                {data.rows.length === 0 && (
                  <tr>
                    <td colSpan={4} className="empty">
                      <Icon name="users" size="xl" />
                      <span>{data.can_manage ? t("الشيت فاضي. ضيف صفوف من فوق.", "The sheet is empty. Add rows above.") : t("الشيت فاضي لسه.", "The sheet is empty for now.")}</span>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        ) : sheet.isError ? (
          <div className="empty" role="alert">
            <Icon name="alert" size="xl" />
            <span>{t("الشيت ده مش موجود أو مش بتاعك.", "This sheet does not exist or is not yours.")}</span>
          </div>
        ) : (
          <Loading className="empty" />
        )}
      </div>
    </>
  );
}
