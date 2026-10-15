import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate } from "react-router";
import { refusalText } from "../api/b2b";
import { useDecideDiscount, usePriceList, useSaveLimits, useSavePriceList, type PriceItem, type PriceListResponse, type WaitingDiscount } from "../api/pricing";
import { useMe } from "../api/queries";
import { Icon } from "../components/Icon";
import { Loading } from "../components/Loading";
import { Modal } from "../components/Modal";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

/**
 * The price list and the discounts (15/10/2026, part 4): the list in force (every Sales person quotes from it), its older
 * versions, the limits, and the discounts waiting for this person's approval. The owner saves a new version - a version is
 * never changed - and sets the limits. Every rule is the server's (`pricing.py`).
 */

const SERVICE_AR: Record<string, string> = {
  translation: "ترجمة",
  review: "مراجعة / تدقيق",
  certified: "ترجمة معتمدة",
  localization: "توطين",
  transcription: "تفريغ نصي",
  dtp: "تنسيق (DTP)",
  interpreting: "ترجمة فورية",
  other: "حاجة تانية",
};
const UNIT_AR: Record<string, string> = { words: "كلمة", pages: "صفحة", hours: "ساعة", project: "المشروع كله" };

function Problem({ text }: { text: string }) {
  if (!text) return null;
  return (
    <div className="note note--danger" role="alert" style={{ margin: "10px 0" }}>
      <Icon name="alert" />
      <div>{text}</div>
    </div>
  );
}

/** The owner's table: every line of the list in force, changed, added or taken off, saved as the next version. */
function Editor({ data, onDone }: { data: PriceListResponse; onDone: () => void }) {
  const { t, lang } = usePreferences();
  const save = useSavePriceList();
  const blank: PriceItem = { service: "translation", unit: "words", currency: "USD", pair: "", rate: "" };
  const [rows, setRows] = useState<PriceItem[]>(() => (data.list?.items.length ? data.list.items.map((item) => ({ ...item })) : [blank]));
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState("");
  const set = (at: number, key: keyof PriceItem, value: string) => setRows((before) => before.map((row, index) => (index === at ? { ...row, [key]: value } : row)));
  const word = (words: Record<string, string>, value: string, label: string) => (lang === "ar" ? (words[value] ?? label) : label);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (save.isPending) return;
    setProblem("");
    save.mutate(
      { note: note.trim(), items: rows.map((row) => ({ ...row, pair: row.pair.trim(), rate: row.rate.trim() })) },
      { onSuccess: onDone, onError: (failure) => setProblem(refusalText(failure, lang, t("القايمة ماتحفظتش.", "The list was not saved."))) },
    );
  };

  return (
    <form className="card" onSubmit={submit} style={{ marginBottom: 14 }}>
      <div className="card__head">
        <Icon name="pen" />
        <h3>{t("عدّل القايمة", "Edit the list")}</h3>
        <span className="muted">{t("الحفظ بيعمل إصدار جديد، والقديم بيفضل زي ما هو.", "Saving makes a new version; the old one stays as it was.")}</span>
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>{t("الخدمة", "Service")}</th>
              <th>{t("الوحدة", "Unit")}</th>
              <th>{t("العملة", "Currency")}</th>
              <th>{t("زوج اللغات", "Pair")}</th>
              <th>{t("السعر", "Price")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index} data-price-row={index}>
                <td>
                  <select className="input" aria-label={`${t("الخدمة", "Service")} ${index + 1}`} value={row.service} onChange={(event) => set(index, "service", event.target.value)}>
                    {data.services.map((one) => (
                      <option key={one.value} value={one.value}>
                        {word(SERVICE_AR, one.value, one.label)}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <select className="input" aria-label={`${t("الوحدة", "Unit")} ${index + 1}`} value={row.unit} onChange={(event) => set(index, "unit", event.target.value)}>
                    {data.units.map((one) => (
                      <option key={one.value} value={one.value}>
                        {word(UNIT_AR, one.value, one.label)}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <select className="input" aria-label={`${t("العملة", "Currency")} ${index + 1}`} value={row.currency} onChange={(event) => set(index, "currency", event.target.value)}>
                    {data.currencies.map((one) => (
                      <option key={one} value={one}>
                        {one}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <input className="input mono" dir="ltr" maxLength={20} placeholder={t("أي زوج", "Any pair")} aria-label={`${t("زوج اللغات", "Pair")} ${index + 1}`} value={row.pair} onChange={(event) => set(index, "pair", event.target.value)} />
                </td>
                <td>
                  <input className="input mono" dir="ltr" inputMode="decimal" style={{ width: 110 }} aria-label={`${t("السعر", "Price")} ${index + 1}`} value={row.rate} onChange={(event) => set(index, "rate", event.target.value)} />
                </td>
                <td>
                  {rows.length > 1 && (
                    <button className="btn btn--sm btn--ghost" type="button" aria-label={t("شيل السطر", "Remove the line")} onClick={() => setRows((before) => before.filter((_row, at) => at !== index))}>
                      <Icon name="x" size="sm" />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row" style={{ margin: "10px 0" }}>
        <button className="btn btn--sm" type="button" onClick={() => setRows((before) => [...before, { ...blank }])}>
          <Icon name="plus" size="sm" />
          {t("ضيف سعر", "Add a price")}
        </button>
        <input className="input grow" maxLength={250} placeholder={t("ملاحظة على الإصدار (اختياري)", "A note on the version (optional)")} aria-label={t("ملاحظة على الإصدار", "Version note")} value={note} onChange={(event) => setNote(event.target.value)} />
      </div>
      <small className="muted">{t("زوج اللغات يتكتب زي EN>AR، ولو فاضي السعر لأي زوج.", "Write the pair like EN>AR; empty is a price for any pair.")}</small>
      <Problem text={problem} />
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn btn--primary" type="submit" disabled={save.isPending}>
          <Icon name="check" />
          {t("احفظ كإصدار جديد", "Save as a new version")}
        </button>
        <button className="btn btn--ghost" type="button" onClick={onDone}>
          {t("إلغاء", "Cancel")}
        </button>
      </div>
    </form>
  );
}

/** How far under the list each may go: the owner changes them, everybody else reads them. */
function Limits({ data }: { data: PriceListResponse }) {
  const { t, lang } = usePreferences();
  const toasts = useToasts();
  const save = useSaveLimits();
  const [sales, setSales] = useState(String(Number(data.limits.sales)));
  const [manager, setManager] = useState(String(Number(data.limits.manager)));
  useEffect(() => {
    setSales(String(Number(data.limits.sales)));
    setManager(String(Number(data.limits.manager)));
  }, [data.limits.sales, data.limits.manager]);

  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div className="card__head">
        <Icon name="sliders" />
        <h3>{t("حدود الخصم", "Discount limits")}</h3>
        <span className="muted">{t("الخصم بيتحسب على سعر القايمة: السعر الأقل منها بيتحسب خصم برضه.", "The discount is measured against the list: a lower price counts as discount too.")}</span>
      </div>
      {data.can_edit ? (
        <form
          className="row"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate(
              { sales: sales.trim(), manager: manager.trim() },
              {
                onSuccess: () => toasts.push({ level: "success", title: t("الحدود اتحفظت", "The limits were saved") }),
                onError: (failure) => toasts.push({ level: "danger", title: refusalText(failure, lang, t("الحدود ماتحفظتش.", "The limits were not saved.")) }),
              },
            );
          }}
        >
          <label htmlFor="limitSales">{t("حد الـSales", "Sales person's limit")}</label>
          <input className="input mono" id="limitSales" dir="ltr" style={{ width: 80 }} value={sales} onChange={(event) => setSales(event.target.value)} />
          <span className="muted">%</span>
          <label htmlFor="limitManager">{t("حد المانجر", "Manager's limit")}</label>
          <input className="input mono" id="limitManager" dir="ltr" style={{ width: 80 }} value={manager} onChange={(event) => setManager(event.target.value)} />
          <span className="muted">%</span>
          <button className="btn btn--sm" type="submit" disabled={save.isPending}>
            {t("احفظ الحدود", "Save the limits")}
          </button>
        </form>
      ) : (
        <div className="row">
          <span>
            {t("حد الـSales", "Sales person's limit")} <span className="mono">{Number(data.limits.sales)}%</span>
          </span>
          <span>
            {t("حد المانجر", "Manager's limit")} <span className="mono">{Number(data.limits.manager)}%</span>
          </span>
          <span className="muted">
            {t("حدك انت", "Your limit")} <span className="mono">{Number(data.limits.mine)}%</span>
          </span>
        </div>
      )}
    </div>
  );
}

/** A waiting discount turned down: with why. */
function Reject({ quote, onClose }: { quote: WaitingDiscount; onClose: () => void }) {
  const { t, lang } = usePreferences();
  const decide = useDecideDiscount();
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState("");
  return (
    <Modal title={`${t("ارفض الخصم", "Turn the discount down")} · ${quote.code}`} icon="x" busy={decide.isPending} onClose={onClose}>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!note.trim()) {
            setProblem(t("اكتب سبب الرفض.", "Write why it is turned down."));
            return;
          }
          decide.mutate(
            { id: quote.id, approved: false, note: note.trim() },
            { onSuccess: onClose, onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش. جرّب تاني.", "Could not. Try again."))) },
          );
        }}
      >
        <div className="field">
          <label htmlFor="rejectNote">{t("سبب الرفض", "Why it is turned down")}</label>
          <textarea className="input" id="rejectNote" rows={2} maxLength={250} value={note} onChange={(event) => setNote(event.target.value)} />
        </div>
        <Problem text={problem} />
        <button className="btn btn--danger" type="submit" disabled={decide.isPending}>
          <Icon name="x" />
          {t("ارفض الخصم", "Turn the discount down")}
        </button>
      </form>
    </Modal>
  );
}

export function PriceListPage() {
  const { t, lang } = usePreferences();
  const me = useMe();
  const toasts = useToasts();
  const user = me.data?.user;
  const allowed = Boolean(user && (user.is_admin || user.role === "sales"));
  const [version, setVersion] = useState("");
  const list = usePriceList(version, allowed);
  const decide = useDecideDiscount();
  const [editing, setEditing] = useState(false);
  const [rejecting, setRejecting] = useState<WaitingDiscount | null>(null);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  const data = list.data;
  if (list.isError) {
    return (
      <div className="card empty" role="alert">
        <Icon name="alert" size="xl" />
        <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
      </div>
    );
  }
  if (!data) return <Loading />;
  const shown = data.list;
  const old = shown !== null && data.current !== null && shown.version !== data.current;

  return (
    <>
      <div className="page-head">
        <h1>{t("قايمة الأسعار", "Price list")}</h1>
        <span className="page-head__sub">
          {t(
            "الأسعار اللي بنعمل منها عروض الأسعار. كل عرض بيتسجّل عليه الإصدار اللي اتسعّر منه، والخصم الأكبر من حدك محتاج اعتماد قبل ما يتبعت.",
            "The prices quotations are made from. Each quotation keeps the version it was priced from, and a discount beyond your limit needs an approval before it is sent.",
          )}
        </span>
      </div>

      {data.waiting.length > 0 && (
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="card__head">
            <Icon name="bell" />
            <h3>{t("خصومات مستنية اعتمادك", "Discounts waiting for your approval")}</h3>
            <span className="chip chip--sm mono">{data.waiting.length}</span>
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("العرض", "Quotation")}</th>
                  <th>{t("الـSales", "Sales person")}</th>
                  <th>{t("السعر", "Price")}</th>
                  <th>{t("سعر القايمة", "List price")}</th>
                  <th>{t("تحت القايمة", "Under the list")}</th>
                  <th>{t("الإجمالي", "Total")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.waiting.map((quote) => (
                  <tr key={quote.id} data-waiting={quote.code}>
                    <td>
                      <span className="mono">{quote.code}</span>
                      <div className="muted">{quote.company_name}</div>
                    </td>
                    <td>{quote.person}</td>
                    <td className="mono">
                      {quote.rate} {quote.currency}
                      {Number(quote.discount_percent) > 0 && <span className="muted"> − {quote.discount_percent}%</span>}
                    </td>
                    <td className="mono">{quote.list_rate ? `${quote.list_rate} (v${quote.version})` : t("مش في القايمة", "Not on the list")}</td>
                    <td className="mono deadline--late">{Number(quote.effective_discount)}%</td>
                    <td className="mono">
                      {quote.total} {quote.currency}
                    </td>
                    <td>
                      <div className="row row--tight" style={{ flexWrap: "nowrap" }}>
                        <button
                          className="btn btn--sm btn--primary"
                          type="button"
                          disabled={decide.isPending}
                          onClick={() =>
                            decide.mutate(
                              { id: quote.id, approved: true, note: "" },
                              {
                                onSuccess: () => toasts.push({ level: "success", title: t("الخصم اتعتمد", "The discount was approved") }),
                                onError: (failure) => toasts.push({ level: "danger", title: refusalText(failure, lang, t("مقدرتش. جرّب تاني.", "Could not. Try again.")) }),
                              },
                            )
                          }
                        >
                          {t("اعتمد الخصم", "Approve the discount")}
                        </button>
                        <button className="btn btn--sm btn--danger" type="button" onClick={() => setRejecting(quote)}>
                          {t("ارفض", "Turn down")}
                        </button>
                        <Link className="btn btn--sm btn--ghost" to={`/leads/${quote.sheet}`}>
                          {t("افتح الشيت", "Open the sheet")}
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <Limits data={data} />

      {editing ? (
        <Editor data={data} onDone={() => setEditing(false)} />
      ) : (
        <div className="card">
          <div className="card__head">
            <Icon name="list-checks" />
            <h3>
              {shown ? t(`الإصدار ${shown.version}`, `Version ${shown.version}`) : t("لسه مفيش قايمة أسعار", "No price list yet")}
            </h3>
            {shown && <span className="muted mono">{shown.created_at}</span>}
            {old && <span className="chip chip--sm chip--open">{t("إصدار قديم", "An old version")}</span>}
            <div className="grow" />
            {data.versions.length > 1 && (
              <select className="input" style={{ width: "auto" }} aria-label={t("الإصدار", "Version")} value={version || String(data.current ?? "")} onChange={(event) => setVersion(event.target.value)}>
                {data.versions.map((one) => (
                  <option key={one.version} value={one.version}>
                    {t(`الإصدار ${one.version}`, `Version ${one.version}`)} · {one.created_at}
                  </option>
                ))}
              </select>
            )}
            {data.can_edit && !old && (
              <button className="btn btn--sm btn--primary" type="button" onClick={() => setEditing(true)}>
                <Icon name="pen" size="sm" />
                {shown ? t("عدّل القايمة", "Edit the list") : t("اعمل القايمة", "Make the list")}
              </button>
            )}
          </div>
          {shown?.note && <p className="muted">{shown.note}</p>}
          {shown ? (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("الخدمة", "Service")}</th>
                    <th>{t("الوحدة", "Unit")}</th>
                    <th>{t("زوج اللغات", "Pair")}</th>
                    <th>{t("السعر", "Price")}</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.items.map((item, index) => (
                    <tr key={index} data-price={`${item.service}-${item.unit}-${item.currency}-${item.pair}`}>
                      <td>{lang === "ar" ? (SERVICE_AR[item.service] ?? item.service) : item.service}</td>
                      <td>{lang === "ar" ? (UNIT_AR[item.unit] ?? item.unit) : item.unit}</td>
                      <td className="mono">{item.pair || <span className="muted">{t("أي زوج", "Any pair")}</span>}</td>
                      <td className="mono">
                        {item.rate} {item.currency}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="empty">
              <Icon name="list-checks" size="xl" />
              <span>{data.can_edit ? t("اعمل أول قايمة أسعار من الزرار اللي فوق.", "Make the first price list with the button above.") : t("المالك لسه ماعملش قايمة الأسعار.", "The owner has not made the price list yet.")}</span>
            </div>
          )}
        </div>
      )}

      {rejecting && <Reject quote={rejecting} onClose={() => setRejecting(null)} />}
    </>
  );
}
