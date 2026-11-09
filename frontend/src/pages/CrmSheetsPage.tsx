import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router";
import { refusalText } from "../api/b2b";
import { useCreateCrmSheet, useCrmSheets, useDeleteCrmSheet, type CrmPerson, type CrmSheet } from "../api/crm";
import { useMe } from "../api/queries";
import { Confirm } from "../components/Confirm";
import { Icon } from "../components/Icon";
import { Loading } from "../components/Loading";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

/** The CRM manager's box for a new sheet: a name and who on the team gets it. */
function NewSheet({ holders }: { holders: CrmPerson[] }) {
  const { t, lang } = usePreferences();
  const navigate = useNavigate();
  const create = useCreateCrmSheet();
  const [title, setTitle] = useState("");
  const [person, setPerson] = useState("");
  const [problem, setProblem] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (create.isPending) return;
    setProblem("");
    create.mutate(
      { title: title.trim(), assigned_to: Number(person) },
      {
        onSuccess: (answer) => navigate(`/crm/${answer.sheet.id}`),
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
          <label htmlFor="crmTitle">{t("اسم الشيت", "Sheet name")}</label>
          <input
            className="input"
            id="crmTitle"
            maxLength={160}
            value={title}
            placeholder={t("مثلًا: عملاء التجمع", "e.g. New Cairo leads")}
            onChange={(event) => setTitle(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="crmHolder">{t("صاحب الشيت", "Sheet holder")}</label>
          <select className="input" id="crmHolder" value={person} onChange={(event) => setPerson(event.target.value)}>
            <option value="">{t("— اختار —", "— choose —")}</option>
            {holders.map((one) => (
              <option key={one.id} value={one.id}>
                {one.name}
              </option>
            ))}
          </select>
        </div>
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
 * The CRM sheets of the real-estate branch: a CRM person's own, or - for the CRM manager and the owner - all of them, with the
 * box that makes a new one.
 */
export function CrmSheetsPage() {
  const { t, lang } = usePreferences();
  const me = useMe();
  const allowed = me.data !== undefined && (me.data.user.role === "crm" || me.data.user.is_admin);
  const list = useCrmSheets(allowed);
  const remove = useDeleteCrmSheet();
  const toasts = useToasts();
  const [doomed, setDoomed] = useState<CrmSheet | null>(null);
  const [problem, setProblem] = useState("");

  if (me.data && !allowed) return <Navigate to="/" replace />;
  const data = list.data;
  const close = () => {
    setDoomed(null);
    setProblem("");
  };
  const deleteNow = () => {
    if (!doomed || remove.isPending) return;
    setProblem("");
    remove.mutate(doomed.id, {
      onSuccess: () => {
        toasts.push({ level: "success", title: t("الشيت اتمسح", "The sheet was deleted") });
        close();
      },
      onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش أمسح الشيت. جرّب تاني.", "Could not delete the sheet. Try again."))),
    });
  };

  return (
    <>
      <div className="page-head">
        <h1>{t("شيتات CRM", "CRM sheets")}</h1>
        <span className="page-head__sub">{t("عملاء فرع العقارات: الاسم والتليفون والحالة، والتواصل من آخر الصف.", "The real-estate branch's leads: name, phone and status, with the contact buttons at the end of the row.")}</span>
      </div>

      {data?.can_manage && <NewSheet holders={data.holders} />}

      <div className="card">
        {data ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("الشيت", "Sheet")}</th>
                  <th>{t("صاحب الشيت", "Sheet holder")}</th>
                  <th>{t("العدد", "People")}</th>
                  {data.statuses.map((status) => (
                    <th key={status.value}>{lang === "en" ? status.en : status.ar}</th>
                  ))}
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.sheets.map((sheet) => (
                  <tr key={sheet.id} data-crm-sheet={sheet.id}>
                    <td>
                      <strong>{sheet.title}</strong>
                      <div className="muted mono">{sheet.created_at}</div>
                    </td>
                    <td>{sheet.assigned_to?.name ?? "—"}</td>
                    <td className="mono">{sheet.counts.rows}</td>
                    {data.statuses.map((status) => (
                      <td key={status.value} className="mono">
                        {sheet.counts[status.value]}
                      </td>
                    ))}
                    <td>
                      <div className="row row--tight" style={{ flexWrap: "nowrap" }}>
                        <Link className="btn btn--sm" to={`/crm/${sheet.id}`}>
                          {t("افتح", "Open")}
                        </Link>
                        {data.can_manage && (
                          <button
                            className="btn btn--sm btn--ghost"
                            type="button"
                            aria-label={`${t("امسح الشيت", "Delete the sheet")} ${sheet.title}`}
                            title={t("امسح الشيت", "Delete the sheet")}
                            onClick={() => setDoomed(sheet)}
                          >
                            <Icon name="trash" size="sm" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {data.sheets.length === 0 && (
                  <tr>
                    <td colSpan={4 + data.statuses.length} className="empty">
                      <Icon name="building" size="xl" />
                      <span>
                        {data.can_manage
                          ? t("مفيش شيتات لسه. اعمل أول واحد من فوق.", "No sheets yet. Make the first one above.")
                          : t("مفيش شيتات ليك لسه. المدير هيبعتلك.", "No sheets for you yet. Your manager will send one.")}
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

      {doomed && (
        <Confirm
          title={`${t("تمسح الشيت", "Delete the sheet")} «${doomed.title}»؟`}
          body={t(`الشيت ده والـ${doomed.counts.rows} صف اللي فيه هيتمسحوا ومفيش رجوع.`, `This sheet and its ${doomed.counts.rows} rows are deleted for good.`)}
          yes={t("امسح", "Delete")}
          danger
          icon="trash"
          busy={remove.isPending}
          problem={problem}
          onYes={deleteNow}
          onNo={close}
        />
      )}
    </>
  );
}
