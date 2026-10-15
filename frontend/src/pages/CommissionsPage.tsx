import { useState, type FormEvent } from "react";
import { Navigate } from "react-router";
import { refusalText } from "../api/b2b";
import {
  useApprove,
  useCommissions,
  useCompanyRate,
  useLineRate,
  usePaid,
  usePersonRate,
  useSplit,
  useTakeBack,
  type CommissionInvoice,
  type CommissionLine,
  type CommissionsResponse,
} from "../api/commissions";
import { useMe } from "../api/queries";
import { Icon } from "../components/Icon";
import { Loading } from "../components/Loading";
import { Modal } from "../components/Modal";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

/**
 * The Sales commissions (15/10/2026, the owner's six decisions): the owner sets the company's rate and anybody's own, splits
 * a deal between the people who worked it, approves a line once the client paid its invoice in full, and marks it paid. A
 * Sales person reads their own lines, a manager their team's. Every rule is the server's (`commissions.py`).
 */

const STATUS: Record<string, [string, string]> = {
  pending: ["مستنية", "Pending"],
  approved: ["اتعتمدت", "Approved"],
  paid: ["اتصرفت", "Paid"],
  cancelled: ["اتلغت", "Cancelled"],
};
const INVOICE: Record<string, [string, string]> = {
  draft: ["مسودة", "Draft"],
  sent: ["اتبعتت", "Sent"],
  partial: ["مدفوعة جزئيًا", "Partly paid"],
  paid: ["مدفوعة", "Paid"],
  cancelled: ["اتلغت", "Cancelled"],
};

function Problem({ text }: { text: string }) {
  if (!text) return null;
  return (
    <div className="note note--danger" role="alert" style={{ margin: "10px 0" }}>
      <Icon name="alert" />
      <div>{text}</div>
    </div>
  );
}

/** A rate box and its save: an empty box means "not set here" (the person's, or the company's, counts). */
function RateBox({ label, value, onSave, busy }: { label: string; value: string | null; onSave: (rate: string) => void; busy: boolean }) {
  const { t } = usePreferences();
  const [rate, setRate] = useState(value ?? "");
  return (
    <form
      className="row row--tight"
      style={{ flexWrap: "nowrap" }}
      onSubmit={(event) => {
        event.preventDefault();
        onSave(rate.trim());
      }}
    >
      <input className="input mono" style={{ width: 90 }} inputMode="decimal" dir="ltr" aria-label={label} value={rate} placeholder="—" onChange={(event) => setRate(event.target.value)} />
      <span className="muted">%</span>
      <button className="btn btn--sm" type="submit" disabled={busy}>
        {t("احفظ", "Save")}
      </button>
    </form>
  );
}

/** The owner's rates: the company's, and each Sales person's own (empty = the company's). */
function Rates({ data }: { data: CommissionsResponse }) {
  const { t, lang } = usePreferences();
  const toasts = useToasts();
  const company = useCompanyRate();
  const person = usePersonRate();
  const done = { onSuccess: () => toasts.push({ level: "success" as const, title: t("النسبة اتحفظت", "The rate was saved") }), onError: (failure: unknown) => toasts.push({ level: "danger" as const, title: refusalText(failure, lang, t("النسبة ماتحفظتش.", "The rate was not saved.")) }) };
  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div className="card__head">
        <Icon name="sliders" />
        <h3>{t("نسب العمولة", "Commission rates")}</h3>
        <span className="muted">{t("على إجمالي الفاتورة. نسبة الموظف لو فاضية بتتحسب بالنسبة العامة.", "On the invoice's whole amount. An empty personal rate uses the company's.")}</span>
      </div>
      <div className="row" style={{ marginBottom: 10 }}>
        <strong>{t("النسبة العامة", "Company rate")}</strong>
        <RateBox label={t("النسبة العامة", "Company rate")} value={data.company_rate} busy={company.isPending} onSave={(rate) => company.mutate(rate, done)} />
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>{t("الـSales", "Sales person")}</th>
              <th>{t("نسبته هو", "Their own rate")}</th>
            </tr>
          </thead>
          <tbody>
            {data.people.map((one) => (
              <tr key={one.id} data-person={one.id}>
                <td>
                  {one.name} <span className="muted">{one.track === "b2b" ? "B2B" : "B2C"}</span>
                </td>
                <td>
                  <RateBox label={`${t("نسبة", "Rate of")} ${one.name}`} value={one.rate} busy={person.isPending} onSave={(rate) => person.mutate({ id: one.id, rate }, done)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Who worked the deal, and each one's part: the parts add up to 100. */
function Split({ invoice, lines, people, onClose }: { invoice: CommissionInvoice; lines: CommissionLine[]; people: CommissionsResponse["people"]; onClose: () => void }) {
  const { t, lang } = usePreferences();
  const split = useSplit();
  const [rows, setRows] = useState(() => (lines.length ? lines.map((line) => ({ person: String(line.person.id), share: String(Number(line.share)) })) : [{ person: "", share: "100" }]));
  const [problem, setProblem] = useState("");
  const total = rows.reduce((sum, row) => sum + (Number(row.share) || 0), 0);
  const set = (at: number, key: "person" | "share", value: string) => setRows((before) => before.map((row, index) => (index === at ? { ...row, [key]: value } : row)));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (split.isPending) return;
    if (rows.some((row) => !row.person)) {
      setProblem(t("اختار الشخص في كل سطر.", "Choose the person on every line."));
      return;
    }
    split.mutate(
      { invoice: invoice.id, shares: rows.map((row) => ({ person: Number(row.person), share: row.share.trim() })) },
      { onSuccess: onClose, onError: (failure) => setProblem(refusalText(failure, lang, t("التقسيم ماتحفظش.", "The split was not saved."))) },
    );
  };

  return (
    <Modal title={`${t("قسّم العمولة", "Split the commission")} · ${invoice.code}`} icon="users" busy={split.isPending} onClose={onClose}>
      <form onSubmit={submit}>
        {rows.map((row, index) => (
          <div className="row row--tight" key={index} style={{ marginBottom: 8 }}>
            <select className="input grow" aria-label={`${t("الشخص", "Person")} ${index + 1}`} value={row.person} onChange={(event) => set(index, "person", event.target.value)}>
              <option value="">{t("— اختار —", "— choose —")}</option>
              {people.map((one) => (
                <option key={one.id} value={one.id}>
                  {one.name}
                </option>
              ))}
            </select>
            <input className="input mono" style={{ width: 80 }} dir="ltr" inputMode="decimal" aria-label={`${t("النصيب", "Share")} ${index + 1}`} value={row.share} onChange={(event) => set(index, "share", event.target.value)} />
            <span className="muted">%</span>
            {rows.length > 1 && (
              <button className="btn btn--sm btn--ghost" type="button" aria-label={t("شيل السطر", "Remove the line")} onClick={() => setRows((before) => before.filter((_row, at) => at !== index))}>
                <Icon name="x" size="sm" />
              </button>
            )}
          </div>
        ))}
        <div className="row">
          <button className="btn btn--sm" type="button" onClick={() => setRows((before) => [...before, { person: "", share: "" }])}>
            <Icon name="plus" size="sm" />
            {t("ضيف شخص", "Add a person")}
          </button>
          <div className="grow" />
          <span className={total === 100 ? "mono" : "mono deadline--late"}>
            {t("المجموع", "Total")} {total}%
          </span>
        </div>
        <Problem text={problem} />
        <button className="btn btn--primary" type="submit" disabled={split.isPending} style={{ marginTop: 10 }}>
          <Icon name="check" />
          {t("احفظ التقسيم", "Save the split")}
        </button>
      </form>
    </Modal>
  );
}

export function CommissionsPage() {
  const { t, lang } = usePreferences();
  const me = useMe();
  const toasts = useToasts();
  const user = me.data?.user;
  const allowed = Boolean(user && (user.is_admin || user.role === "sales"));
  const [status, setStatus] = useState("");
  const list = useCommissions(status, allowed);
  const approve = useApprove();
  const paid = usePaid();
  const takeBack = useTakeBack();
  const lineRate = useLineRate();
  const [splitting, setSplitting] = useState<CommissionInvoice | null>(null);

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
  const failed = (failure: unknown) => toasts.push({ level: "danger", title: refusalText(failure, lang, t("مقدرتش. جرّب تاني.", "Could not do it. Try again.")) });
  const owner = data.can_manage;
  const tiles: { key: keyof CommissionsResponse["totals"]; ar: string; en: string; tone?: string }[] = [
    { key: "waiting", ar: "مستنية العميل يدفع", en: "Waiting for the client to pay" },
    { key: "due", ar: "مستحقة (العميل دفع)", en: "Due (the client paid)", tone: "kpi--warn" },
    { key: "approved", ar: "اتعتمدت ولسه ماتصرفتش", en: "Approved, not paid yet" },
    { key: "paid", ar: "اتصرفت", en: "Paid", tone: "kpi--ok" },
  ];

  return (
    <>
      <div className="page-head">
        <h1>{owner ? t("العمولات", "Commissions") : t("عمولاتي", "My commissions")}</h1>
        <span className="page-head__sub">
          {t(
            "العمولة على إجمالي الفاتورة، وبتستحق لما العميل يدفع الفاتورة كلها. المالك بس اللي بيعتمدها ويصرفها.",
            "A commission is on the invoice's whole amount and is due once the client pays the whole invoice. Only the owner approves and pays it.",
          )}
        </span>
      </div>

      <div className="grid grid--4" style={{ marginBottom: 14 }}>
        {tiles.map((tile) => (
          <div key={tile.key} className={tile.tone && Number(data.totals[tile.key]) > 0 ? `kpi ${tile.tone}` : "kpi"} data-total={tile.key}>
            <div className="kpi__value mono">{data.totals[tile.key]}</div>
            <div className="kpi__label">
              {t(tile.ar, tile.en)} · {t("جنيه", "EGP")}
            </div>
          </div>
        ))}
      </div>
      {data.totals.unknown > 0 && (
        <div className="note note--info" style={{ marginBottom: 14 }}>
          <Icon name="info" />
          <div>
            {t(
              `${data.totals.unknown} عمولة لسه مالهاش رقم بالجنيه (مفيش نسبة أو سعر صرف) ومش محسوبة فوق.`,
              `${data.totals.unknown} commissions have no figure in EGP yet (no rate or exchange rate) and are not counted above.`,
            )}
          </div>
        </div>
      )}

      {owner && <Rates data={data} />}

      {owner && data.uncovered.length > 0 && (
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="card__head">
            <Icon name="file" />
            <h3>{t("فواتير من غير عمولة", "Invoices with no commission")}</h3>
            <span className="muted">{t("لو حد باعها، اضغط «قسّم» واختار مين.", "If somebody sold it, press «Split» and choose who.")}</span>
          </div>
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {data.uncovered.map((invoice) => (
              <li key={invoice.id} className="row row--tight" style={{ padding: "6px 0" }} data-uncovered={invoice.id}>
                <span className="mono">{invoice.code}</span>
                <span className="mono muted">{invoice.client_code}</span>
                <span className="mono">
                  {invoice.amount} {invoice.currency}
                </span>
                <div className="grow" />
                <button className="btn btn--sm" type="button" onClick={() => setSplitting(invoice)}>
                  <Icon name="users" size="sm" />
                  {t("قسّم", "Split")}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="card">
        <div className="row" style={{ marginBottom: 12 }}>
          <div className="grow" />
          <select className="input" style={{ width: "auto" }} aria-label={t("اعرض", "Show")} value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">{t("كل العمولات", "All commissions")}</option>
            {Object.entries(STATUS).map(([value, words]) => (
              <option key={value} value={value}>
                {t(...words)}
              </option>
            ))}
          </select>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>{t("العمولة", "Commission")}</th>
                <th>{t("الفاتورة", "Invoice")}</th>
                <th>{t("الـSales", "Sales person")}</th>
                <th>{t("النصيب", "Share")}</th>
                <th>{t("النسبة", "Rate")}</th>
                <th>{t("المبلغ", "Amount")}</th>
                <th>{t("بالجنيه", "In EGP")}</th>
                <th>{t("الحالة", "Status")}</th>
                {owner && <th />}
              </tr>
            </thead>
            <tbody>
              {data.lines.map((line) => (
                <tr key={line.id} data-line={line.id}>
                  <td className="mono">{line.code}</td>
                  <td>
                    <span className="mono">{line.invoice.code}</span> <span className="mono muted">{line.invoice.client_code}</span>
                    <div className={line.due ? "chip chip--sm chip--replied" : "chip chip--sm"}>{t(...(INVOICE[line.invoice.status] ?? [line.invoice.status, line.invoice.status]))}</div>
                  </td>
                  <td>{line.person.name}</td>
                  <td className="mono">{Number(line.share)}%</td>
                  <td>
                    {owner && line.status === "pending" ? (
                      <RateBox label={`${t("نسبة", "Rate of")} ${line.code}`} value={line.own_rate ? line.rate : null} busy={lineRate.isPending} onSave={(rate) => lineRate.mutate({ id: line.id, rate }, { onError: failed })} />
                    ) : null}
                    <span className="mono">{line.rate ? `${Number(line.rate)}%` : <span className="muted">{t("مفيش نسبة", "No rate")}</span>}</span>
                  </td>
                  <td className="mono">{line.amount ? `${line.amount} ${line.currency}` : "—"}</td>
                  <td className="mono">{line.amount_egp ?? "—"}</td>
                  <td>
                    <span className="chip chip--sm" data-line-status={line.status}>
                      {t(...(STATUS[line.status] ?? [line.status, line.status]))}
                    </span>
                    {line.paid_at && <div className="mono muted">{line.paid_at}</div>}
                  </td>
                  {owner && (
                    <td>
                      <div className="row row--tight" style={{ flexWrap: "nowrap" }}>
                        {line.status === "pending" && line.due && (
                          <button className="btn btn--sm btn--primary" type="button" disabled={approve.isPending} onClick={() => approve.mutate(line.id, { onError: failed })}>
                            {t("اعتمد", "Approve")}
                          </button>
                        )}
                        {line.status === "approved" && (
                          <>
                            <button className="btn btn--sm btn--primary" type="button" disabled={paid.isPending} onClick={() => paid.mutate(line.id, { onError: failed })}>
                              {t("اتصرفت", "Paid")}
                            </button>
                            <button className="btn btn--sm btn--ghost" type="button" disabled={takeBack.isPending} onClick={() => takeBack.mutate(line.id, { onError: failed })}>
                              {t("رجّعها", "Take back")}
                            </button>
                          </>
                        )}
                        {line.status === "pending" && (
                          <button className="btn btn--sm" type="button" onClick={() => setSplitting(line.invoice)}>
                            {t("قسّم", "Split")}
                          </button>
                        )}
                      </div>
                    </td>
                  )}
                </tr>
              ))}
              {data.lines.length === 0 && (
                <tr>
                  <td colSpan={owner ? 9 : 8} className="empty">
                    {t("مفيش عمولات لسه.", "No commissions yet.")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {splitting && (
        <Split
          invoice={splitting}
          lines={data.lines.filter((line) => line.invoice.id === splitting.id && line.status !== "cancelled")}
          people={data.people}
          onClose={() => setSplitting(null)}
        />
      )}
    </>
  );
}
