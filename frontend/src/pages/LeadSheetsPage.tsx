import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router";
import { refusalText, useB2bFollowUps, useB2bSheets, useCreateSheet, useDeleteAnySheet, type B2bPerson, type B2bSheet, type Market } from "../api/b2b";
import { Confirm } from "../components/Confirm";
import { useToasts } from "../components/Toasts";
import { useMe } from "../api/queries";
import { FollowUpBadge } from "../components/b2b/FollowUpBadge";
import { Icon } from "../components/Icon";
import { Loading } from "../components/Loading";
import { usePreferences } from "../i18n/Preferences";

/** The manager's box for a new sheet: a name, the Sales person who gets it, and what the manager wants from it. */
function NewSheet({ sales, market }: { sales: B2bPerson[]; market: Market }) {
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
      { title: title.trim(), note: note.trim(), assigned_to: Number(person), market },
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
            placeholder={market === "b2c" ? t("مثلًا: شركات المعادي", "e.g. Companies in Maadi") : t("مثلًا: شركات ترجمة ألمانيا", "e.g. Translation agencies, Germany")}
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

/** The follow-ups due today or late: the Sales person's own, or the whole team's for the manager (with whose they are). */
function FollowUps({ team, market }: { team: boolean; market: Market }) {
  const { t } = usePreferences();
  const list = useB2bFollowUps(true, market);
  const items = list.data?.items ?? [];
  if (!list.data || items.length === 0) return null;
  const late = items.filter((item) => item.follow_up === "overdue").length;

  return (
    <div className="card" id="follow-ups" style={{ marginBottom: 14 }}>
      <div className="card__head">
        <Icon name="calendar" />
        <h3>{team ? t("متابعات الفريق النهارده والمتأخرة", "The team's follow-ups: today and overdue") : t("متابعاتك النهارده والمتأخرة", "Your follow-ups: today and overdue")}</h3>
        <span className="chip chip--sm mono">{items.length}</span>
        {late > 0 && <span className="chip chip--sm deadline--late">{t(`${late} متأخرة`, `${late} overdue`)}</span>}
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>{t("الشركة", "Company")}</th>
              <th>{t("الشيت", "Sheet")}</th>
              {team && <th>{t("الـSales", "Sales person")}</th>}
              <th>{t("المتابعة", "Follow-up")}</th>
              <th>{t("آخر تواصل منّا", "Our last outreach")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id} data-follow-up-row={item.id}>
                <td>
                  <strong>{item.company_name}</strong>
                  {item.contact_person && <div className="muted">{item.contact_person}</div>}
                </td>
                <td>{item.sheet.title}</td>
                {team && <td>{item.sales?.name ?? "—"}</td>}
                <td>
                  <FollowUpBadge date={item.next_follow_up} state={item.follow_up} />
                </td>
                <td className="mono">{item.last_outreach_at || "—"}</td>
                <td>
                  <Link className="btn btn--sm" to={`/leads/${item.sheet.id}`}>
                    {t("افتح الشيت", "Open the sheet")}
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/**
 * The B2B company sheets: a Sales person's own, or - for the Sales manager and the owner - all of them, with the box that
 * makes a new one. Titles and counts only: the companies are on the sheet's own page.
 */
export function LeadSheetsPage({ market = "b2b" }: { market?: Market }) {
  const { t, lang } = usePreferences();
  const me = useMe();
  const allowed = me.data !== undefined && (me.data.user.role === "sales" || me.data.user.is_admin);
  const list = useB2bSheets(allowed, market);
  const remove = useDeleteAnySheet();
  const toasts = useToasts();
  const [doomed, setDoomed] = useState<B2bSheet | null>(null);
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
        {/* The team is the server's answer: a Sales person always reads their own team's sheets, whatever the address. */}
        {(data?.market ?? market) === "b2c" ? (
          <>
            <h1>{t("شيتات B2C", "B2C sheets")}</h1>
            <span className="page-head__sub">
              {t(
                "الشركات جوه مصر. الأونلاين بيتواصل بالتليفون والرسايل، والميداني بينزلها ويأكد الزيارة من «الزيارات».",
                "The companies inside Egypt. Online Sales reach them by phone and messages; field Sales visit them and confirm each visit on «Visits».",
              )}
            </span>
          </>
        ) : (
          <>
            <h1>{t("شيتات الشركات", "Company sheets")}</h1>
            <span className="page-head__sub">
              {t(
                "الشركات اللي بنتواصل معاها (B2B). الواتساب والإيميل اللي بيتبعتوا من الشيت بيتعلّموا لوحدهم، والمكالمة بتتسجّل بإيدك.",
                "The companies we reach out to (B2B). WhatsApp and e-mail sent from a sheet are marked by themselves; a call is logged by hand.",
              )}
            </span>
          </>
        )}
      </div>

      {data && <FollowUps team={data.can_manage} market={data.market} />}

      {data?.can_manage && <NewSheet sales={data.sales} market={data.market} />}

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
                      <div className="row row--tight" style={{ flexWrap: "nowrap" }}>
                        <Link className="btn btn--sm" to={`/leads/${sheet.id}`}>
                          {t("افتح", "Open")}
                        </Link>
                        {data.can_manage && (
                          <button
                            className="btn btn--sm btn--ghost"
                            type="button"
                            aria-label={`${t("امسح الشيت", "Delete the sheet")} ${sheet.title}`}
                            title={
                              sheet.contacted > 0
                                ? t("فيه شركات في الشيت ده اتواصلنا معاها، فمش هيتمسح.", "Some companies on this sheet were contacted, so it is kept.")
                                : t("امسح الشيت", "Delete the sheet")
                            }
                            disabled={sheet.contacted > 0}
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

      {doomed && (
        <Confirm
          title={`${t("تمسح الشيت", "Delete the sheet")} «${doomed.title}»؟`}
          body={t(
            `الشيت ده والـ${doomed.rows} شركة اللي فيه هيتمسحوا ومفيش رجوع. الشيت اللي فيه شركة اتواصلنا معاها مابيتمسحش.`,
            `This sheet and its ${doomed.rows} companies are deleted for good. A sheet with a contacted company is kept.`,
          )}
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
