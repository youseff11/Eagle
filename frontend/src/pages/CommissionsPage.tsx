import { useState, type FormEvent, type ReactNode } from "react";
import { Navigate } from "react-router";
import { refusalText } from "../api/b2b";
import {
  useApprove,
  useCancelDeal,
  useCommissions,
  useCompanyRate,
  useDealOfInvoice,
  usePaid,
  usePersonRate,
  useReportPayment,
  useSetDeal,
  useTakeBack,
  useWithdrawDeal,
  type ClientPaidState,
  type CommissionsResponse,
  type Deal,
} from "../api/commissions";
import { useMe } from "../api/queries";
import { Confirm } from "../components/Confirm";
import { Icon } from "../components/Icon";
import { Loading } from "../components/Loading";
import { Modal } from "../components/Modal";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

/**
 * The Sales commissions, per deal (15/10/2026; per deal since 21/10/2026, the owner's change). A company a Sales person
 * moved to «تم التعاقد» shows here by itself with what the deal was about; the owner corrects its value, links its invoice,
 * and gives each person on it their own percent of the value. A line is approved once the client paid the deal's invoice in
 * full, then marked paid. A Sales person reads their own lines, a manager their team's. Every rule is the server's
 * (`commissions.py`).
 */

const STATUS: Record<string, [string, string]> = {
  pending: ["مستنية", "Pending"],
  approved: ["اتعتمدت", "Approved"],
  paid: ["اتصرفت", "Paid"],
  cancelled: ["اتلغت", "Cancelled"],
};
const STAGE: Record<string, [string, string]> = {
  waiting: ["مستنية العميل يدفع", "Waiting for the client to pay"],
  due: ["مستحقة", "Due"],
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

/** The owner's rates: the company's, and each Sales person's own (empty = the company's). What a deal's person starts
 * from when the owner sets no percent on the deal itself. */
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
        <span className="muted">
          {t(
            "من قيمة الصفقة. دي اللي بتتحسب لو ماحددتش نسبة على الصفقة نفسها، ونسبة الموظف لو فاضية بتتحسب بالعامة.",
            "Of the deal's value. They count when no percent is set on the deal itself; an empty personal rate uses the company's.",
          )}
        </span>
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

/** The owner sets up a deal: its value and currency, its invoice, and who earned a commission on it at what percent. */
function DealForm({ deal, data, onClose }: { deal: Deal; data: CommissionsResponse; onClose: () => void }) {
  const { t, lang } = usePreferences();
  const save = useSetDeal();
  const [value, setValue] = useState(deal.value ?? "");
  const [currency, setCurrency] = useState(deal.currency || "EGP");
  const [invoice, setInvoice] = useState(deal.invoice ? String(deal.invoice.id) : "");
  const [rows, setRows] = useState(() =>
    deal.lines.filter((line) => line.status !== "cancelled").length
      ? deal.lines.filter((line) => line.status !== "cancelled").map((line) => ({ person: String(line.person.id), rate: line.own_rate && line.rate ? String(Number(line.rate)) : "" }))
      : [{ person: deal.owner ? String(deal.owner.id) : "", rate: "" }],
  );
  const [problem, setProblem] = useState("");
  const invoices = [...(deal.invoice ? [deal.invoice] : []), ...data.uncovered];
  const total = rows.reduce((sum, row) => sum + (Number(row.rate) || 0), 0);
  const set = (at: number, key: "person" | "rate", text: string) => setRows((before) => before.map((row, index) => (index === at ? { ...row, [key]: text } : row)));
  /** What a person counts at when no percent is written on the deal: their own, else the company's. */
  const fallback = (id: string) => {
    const person = data.people.find((one) => String(one.id) === id);
    const rate = person?.rate ?? data.company_rate;
    return rate ? `${Number(rate)}` : "—";
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (save.isPending) return;
    if (rows.some((row) => !row.person)) {
      setProblem(t("اختار الـSales في كل سطر.", "Choose the Sales person on every line."));
      return;
    }
    save.mutate(
      {
        id: deal.id,
        changes: {
          value: value.trim(),
          currency,
          invoice: invoice ? Number(invoice) : null,
          people: rows.map((row) => ({ person: Number(row.person), rate: row.rate.trim() })),
        },
      },
      { onSuccess: onClose, onError: (failure) => setProblem(refusalText(failure, lang, t("الصفقة ماتحفظتش.", "The deal was not saved."))) },
    );
  };

  return (
    <Modal title={`${t("ظبّط الصفقة", "Set up the deal")} · ${deal.company.name || deal.code}`} icon="pen" busy={save.isPending} wide onClose={onClose}>
      <form onSubmit={submit}>
        <div className="row" style={{ marginBottom: 10 }}>
          <label className="grow">
            <span className="muted">{t("قيمة الصفقة", "Deal value")}</span>
            <input className="input mono" dir="ltr" inputMode="decimal" aria-label={t("قيمة الصفقة", "Deal value")} value={value} placeholder="—" onChange={(event) => setValue(event.target.value)} />
          </label>
          <label>
            <span className="muted">{t("العملة", "Currency")}</span>
            <select className="input" aria-label={t("العملة", "Currency")} value={currency} onChange={(event) => setCurrency(event.target.value)}>
              {data.currencies.map((code) => (
                <option key={code} value={code}>
                  {code}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label style={{ display: "block", marginBottom: 12 }}>
          <span className="muted">{t("الفاتورة (العمولة بتستحق لما تتدفع كلها)", "The invoice (the commission is due once it is paid in full)")}</span>
          <select className="input" aria-label={t("الفاتورة", "Invoice")} value={invoice} onChange={(event) => setInvoice(event.target.value)}>
            <option value="">{t("— لسه مفيش فاتورة —", "— no invoice yet —")}</option>
            {invoices.map((one) => (
              <option key={one.id} value={one.id}>
                {one.code} · {one.client_code} · {one.amount} {one.currency}
              </option>
            ))}
          </select>
        </label>

        <strong>{t("مين اشتغل على الصفقة وعمولته", "Who worked the deal, and their commission")}</strong>
        <div className="muted" style={{ margin: "4px 0 8px" }}>
          {t("كل واحد نسبته من قيمة الصفقة كلها. لو سيبتها فاضية بتتحسب بنسبته هو أو النسبة العامة.", "Each one's percent of the deal's whole value. Left empty, it counts at their own rate or the company's.")}
        </div>
        {rows.map((row, index) => (
          <div className="row row--tight" key={index} style={{ marginBottom: 8 }}>
            <select className="input grow" aria-label={`${t("الـSales", "Sales person")} ${index + 1}`} value={row.person} onChange={(event) => set(index, "person", event.target.value)}>
              <option value="">{t("— اختار —", "— choose —")}</option>
              {data.people.map((one) => (
                <option key={one.id} value={one.id}>
                  {one.name}
                </option>
              ))}
            </select>
            <input
              className="input mono"
              style={{ width: 90 }}
              dir="ltr"
              inputMode="decimal"
              aria-label={`${t("العمولة", "Commission")} ${index + 1}`}
              value={row.rate}
              placeholder={fallback(row.person)}
              onChange={(event) => set(index, "rate", event.target.value)}
            />
            <span className="muted">%</span>
            {rows.length > 1 && (
              <button className="btn btn--sm btn--ghost" type="button" aria-label={t("شيل السطر", "Remove the line")} onClick={() => setRows((before) => before.filter((_row, at) => at !== index))}>
                <Icon name="x" size="sm" />
              </button>
            )}
          </div>
        ))}
        <div className="row">
          <button className="btn btn--sm" type="button" onClick={() => setRows((before) => [...before, { person: "", rate: "" }])}>
            <Icon name="plus" size="sm" />
            {t("ضيف Sales", "Add a Sales person")}
          </button>
          <div className="grow" />
          <span className={total > 100 ? "mono deadline--late" : "mono"}>
            {t("مجموع النسب", "Rates total")} {total}%
          </span>
        </div>
        <Problem text={problem} />
        <button className="btn btn--primary" type="submit" disabled={save.isPending} style={{ marginTop: 10 }}>
          <Icon name="check" />
          {t("احفظ الصفقة", "Save the deal")}
        </button>
      </form>
    </Modal>
  );
}

const CLIENT_PAID: Record<ClientPaidState, [string, string]> = {
  none: ["لسه مادفعش", "Has not paid yet"],
  partial: ["دفع جزء", "Paid in part"],
  full: ["دفع كله", "Paid in full"],
};

/** The Sales person says the company pulled out of the contract: the deal is cancelled and the owner is told. */
function WithdrawForm({ deal, onClose }: { deal: Deal; onClose: () => void }) {
  const { t, lang } = usePreferences();
  const withdraw = useWithdrawDeal();
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState("");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (withdraw.isPending) return;
    withdraw.mutate(
      { id: deal.id, reason: reason.trim() },
      { onSuccess: onClose, onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش. جرّب تاني.", "Could not do it. Try again."))) },
    );
  };
  return (
    <Modal title={`${t("الشركة لغت التعاقد", "The company withdrew")} · ${deal.company.name || deal.code}`} icon="x" busy={withdraw.isPending} onClose={onClose}>
      <form onSubmit={submit}>
        <div className="note note--warn" style={{ marginBottom: 10 }}>
          <Icon name="alert" />
          <div>{t("الصفقة وعمولتك عليها هيتلغوا (بيفضلوا متسجّلين عند المالك) وهيوصله تنبيه.", "The deal and your commission on it are cancelled (the owner keeps the record) and the owner is notified.")}</div>
        </div>
        <label style={{ display: "block" }}>
          <span className="muted">{t("السبب (اختياري)", "Reason (optional)")}</span>
          <input className="input" maxLength={250} aria-label={t("السبب", "Reason")} value={reason} onChange={(event) => setReason(event.target.value)} />
        </label>
        <Problem text={problem} />
        <button className="btn btn--danger" type="submit" disabled={withdraw.isPending} style={{ marginTop: 10 }}>
          <Icon name="x" />
          {t("أكّد إن الشركة لغت", "Confirm the company withdrew")}
        </button>
      </form>
    </Modal>
  );
}

/** The Sales person writes down what the client paid: not at all, a part (how much), or all of it. The owner is told. */
function PaymentForm({ deal, onClose }: { deal: Deal; onClose: () => void }) {
  const { t, lang } = usePreferences();
  const report = useReportPayment();
  const before = deal.client_paid;
  const [state, setState] = useState<ClientPaidState>(before.state || "none");
  const [amount, setAmount] = useState(before.amount ?? "");
  const [note, setNote] = useState(before.note);
  const [problem, setProblem] = useState("");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (report.isPending) return;
    report.mutate(
      { id: deal.id, state, amount: state === "none" ? "" : amount.trim(), note: note.trim() },
      { onSuccess: onClose, onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش. جرّب تاني.", "Could not do it. Try again."))) },
    );
  };
  return (
    <Modal title={`${t("دفع العميل", "The client's payment")} · ${deal.company.name || deal.code}`} icon="chart" busy={report.isPending} onClose={onClose}>
      <form onSubmit={submit}>
        <div className="row row--tight" role="radiogroup" aria-label={t("العميل دفع؟", "Did the client pay?")} style={{ marginBottom: 10 }}>
          {(Object.keys(CLIENT_PAID) as ClientPaidState[]).map((key) => (
            <button key={key} type="button" role="radio" aria-checked={state === key} className={state === key ? "btn btn--sm btn--primary" : "btn btn--sm"} onClick={() => setState(key)}>
              {t(...CLIENT_PAID[key])}
            </button>
          ))}
        </div>
        {state !== "none" && (
          <label style={{ display: "block", marginBottom: 10 }}>
            <span className="muted">
              {state === "partial" ? t("دفع كام", "Amount paid") : t("المبلغ (اختياري)", "Amount (optional)")} · {deal.currency || ""}
            </span>
            <input className="input mono" dir="ltr" inputMode="decimal" aria-label={t("المبلغ المدفوع", "Amount paid")} value={amount} placeholder="—" onChange={(event) => setAmount(event.target.value)} />
          </label>
        )}
        <label style={{ display: "block" }}>
          <span className="muted">{t("ملاحظة (اختياري)", "Note (optional)")}</span>
          <input className="input" maxLength={250} aria-label={t("ملاحظة", "Note")} value={note} onChange={(event) => setNote(event.target.value)} />
        </label>
        <div className="muted" style={{ marginTop: 8 }}>
          {t("ده بلاغ للمالك. العمولة بتستحق لما الحسابات تسجّل دفع الفاتورة كلها.", "This is a report to the owner. The commission is due once Accounting records the whole invoice as paid.")}
        </div>
        <Problem text={problem} />
        <button className="btn btn--primary" type="submit" disabled={report.isPending} style={{ marginTop: 10 }}>
          <Icon name="check" />
          {t("ابعت للمالك", "Send to the owner")}
        </button>
      </form>
    </Modal>
  );
}

/** A label and its value, drawn only when there is a value. */
function Fact({ label, children }: { label: string; children: ReactNode }) {
  if (children === "" || children === null || children === undefined) return null;
  return (
    <div className="kv">
      <span>{label}</span>
      <strong>{children}</strong>
    </div>
  );
}

function DealCard({
  deal,
  owner,
  onEdit,
  onCancel,
  onWithdraw,
  onPayment,
}: {
  deal: Deal;
  owner: boolean;
  onEdit: () => void;
  onCancel: () => void;
  onWithdraw: () => void;
  onPayment: () => void;
}) {
  const { t, lang } = usePreferences();
  const toasts = useToasts();
  const approve = useApprove();
  const paid = usePaid();
  const takeBack = useTakeBack();
  const failed = (failure: unknown) => toasts.push({ level: "danger", title: refusalText(failure, lang, t("مقدرتش. جرّب تاني.", "Could not do it. Try again.")) });
  const company = deal.company;
  const quote = deal.quotation;
  const open = deal.status === "open";
  const decided = deal.lines.some((line) => line.status === "approved" || line.status === "paid");
  const place = [company.governorate, company.country].filter(Boolean).join(" · ");

  return (
    <div className="card" style={{ marginBottom: 14 }} data-deal={deal.id}>
      <div className="card__head">
        <Icon name="building" />
        <h3>{company.name || t("صفقة من فاتورة", "A deal from an invoice")}</h3>
        <span className="mono muted">{deal.code}</span>
        <span className="chip chip--sm">{deal.market === "b2c" ? "B2C" : "B2B"}</span>
        <span className={deal.stage === "due" ? "chip chip--sm chip--open" : deal.stage === "paid" ? "chip chip--sm chip--replied" : "chip chip--sm"} data-deal-stage={deal.stage}>
          {t(...(STAGE[deal.stage] ?? [deal.stage, deal.stage]))}
        </span>
        <div className="grow" />
        <strong className="mono" data-deal-value>
          {deal.value ? `${deal.value} ${deal.currency}` : <span className="muted">{t("لسه مفيش قيمة", "No value yet")}</span>}
        </strong>
      </div>

      <div className="grid grid--2" style={{ marginBottom: 12 }}>
        <div>
          <Fact label={t("قفلها", "Closed by")}>{deal.owner?.name}</Fact>
          <Fact label={t("يوم التعاقد", "Contracted on")}>{deal.won_at}</Fact>
          <Fact label={t("المسؤول", "Contact")}>{[company.contact_person, company.position].filter(Boolean).join(" · ")}</Fact>
          <Fact label={t("المكان", "Place")}>{place}</Fact>
          <Fact label={t("المجال", "Industry")}>{company.industry}</Fact>
          <Fact label={t("الخدمات", "Services")}>{company.services}</Fact>
          <Fact label={t("اللغات", "Languages")}>{company.languages}</Fact>
          <Fact label={t("المصدر", "Source")}>{company.source}</Fact>
          <Fact label={t("الشيت", "Sheet")}>{company.sheet}</Fact>
          <Fact label={t("كود العميل", "Client code")}>{deal.client_code}</Fact>
        </div>
        <div>
          {quote ? (
            <>
              <Fact label={t("عرض السعر", "Quotation")}>
                <span className="mono">{quote.code}</span>
              </Fact>
              <Fact label={t("الشغل", "Work")}>
                {quote.service} · {quote.source_lang} &gt; {quote.target_lang}
              </Fact>
              <Fact label={t("الكمية والسعر", "Size and price")}>
                <span className="mono">
                  {quote.quantity.toLocaleString()} {quote.unit} × {quote.rate} {quote.currency}
                </span>
              </Fact>
              {Number(quote.discount) > 0 && <Fact label={t("الخصم", "Discount")}>{`${Number(quote.discount)}%`}</Fact>}
              <Fact label={t("إجمالي العرض", "Quotation total")}>
                <span className="mono">
                  {quote.total} {quote.currency}
                </span>
              </Fact>
              <Fact label={t("الديدلاين", "Deadline")}>{quote.deadline}</Fact>
              <Fact label={t("شروط الدفع", "Payment terms")}>{quote.payment_terms}</Fact>
            </>
          ) : (
            <Fact label={t("قيمة الصفقة في الشيت", "Deal value on the sheet")}>{company.sheet_value ? <span className="mono">{company.sheet_value}</span> : null}</Fact>
          )}
          <Fact label={t("الفاتورة", "Invoice")}>
            {deal.invoice ? (
              <span>
                <span className="mono">{deal.invoice.code}</span> <span className="mono muted">{deal.invoice.amount} {deal.invoice.currency}</span>{" "}
                <span className={deal.paid ? "chip chip--sm chip--replied" : "chip chip--sm"}>{t(...(INVOICE[deal.invoice.status] ?? [deal.invoice.status, deal.invoice.status]))}</span>
              </span>
            ) : (
              <span className="muted">{t("لسه مفيش", "None yet")}</span>
            )}
          </Fact>
          {deal.value_by_hand && <Fact label={t("القيمة", "Value")}>{t("المالك عدّلها", "Corrected by the owner")}</Fact>}
          {deal.client_paid.state && (
            <Fact label={t("دفع العميل", "Client payment")}>
              <span data-client-paid={deal.client_paid.state}>
                {t(...CLIENT_PAID[deal.client_paid.state])}
                {deal.client_paid.amount ? ` · ${deal.client_paid.amount} ${deal.currency}` : ""}
              </span>
              <span className="muted">
                {" "}
                {[deal.client_paid.by?.name, deal.client_paid.at, deal.client_paid.note].filter(Boolean).join(" · ")}
              </span>
            </Fact>
          )}
          {deal.status === "cancelled" && <Fact label={t("سبب الإلغاء", "Cancel reason")}>{deal.cancel_reason}</Fact>}
        </div>
      </div>

      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>{t("الـSales", "Sales person")}</th>
              <th>{t("النسبة", "Rate")}</th>
              <th>{t("العمولة", "Commission")}</th>
              <th>{t("بالجنيه", "In EGP")}</th>
              <th>{t("الحالة", "Status")}</th>
              {owner && <th />}
            </tr>
          </thead>
          <tbody>
            {deal.lines.map((line) => (
              <tr key={line.id} data-line={line.id}>
                <td>
                  {line.person.name} <span className="mono muted">{line.code}</span>
                </td>
                <td className="mono">
                  {line.rate ? `${Number(line.rate)}%` : <span className="muted">{t("مفيش نسبة", "No rate")}</span>}
                  {line.rate && !line.own_rate && line.status === "pending" && <span className="muted"> {t("(العامة)", "(default)")}</span>}
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
                      {line.status === "pending" && deal.paid && (
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
                    </div>
                  </td>
                )}
              </tr>
            ))}
            {deal.lines.length === 0 && (
              <tr>
                <td colSpan={owner ? 6 : 5} className="empty">
                  {t("لسه محدش عليها. اضغط «ظبّط الصفقة» واختار مين.", "Nobody is on it yet. Press «Set up the deal» and choose who.")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {!owner && open && (
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn btn--sm btn--primary" type="button" onClick={onPayment}>
            <Icon name="chart" size="sm" />
            {t("سجّل دفع العميل", "Record the client's payment")}
          </button>
          <div className="grow" />
          {!decided && (
            <button className="btn btn--sm btn--danger" type="button" onClick={onWithdraw}>
              <Icon name="x" size="sm" />
              {t("الشركة لغت التعاقد", "The company withdrew")}
            </button>
          )}
        </div>
      )}
      {owner && open && !decided && (
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn btn--sm btn--primary" type="button" onClick={onEdit}>
            <Icon name="pen" size="sm" />
            {t("ظبّط الصفقة", "Set up the deal")}
          </button>
          <div className="grow" />
          <button className="btn btn--sm btn--ghost" type="button" onClick={onCancel}>
            <Icon name="x" size="sm" />
            {t("الغي الصفقة", "Cancel the deal")}
          </button>
        </div>
      )}
    </div>
  );
}

export function CommissionsPage() {
  const { t, lang } = usePreferences();
  const me = useMe();
  const toasts = useToasts();
  const user = me.data?.user;
  const allowed = Boolean(user && (user.is_admin || user.role === "sales"));
  const [stage, setStage] = useState("");
  const list = useCommissions(stage, allowed);
  const fromInvoice = useDealOfInvoice();
  const cancel = useCancelDeal();
  const [editing, setEditing] = useState<number | null>(null);
  const [cancelling, setCancelling] = useState<Deal | null>(null);
  const [withdrawing, setWithdrawing] = useState<number | null>(null);
  const [reporting, setReporting] = useState<number | null>(null);
  const [problem, setProblem] = useState("");

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
  const editingDeal = data.deals.find((deal) => deal.id === editing);
  const withdrawingDeal = data.deals.find((deal) => deal.id === withdrawing);
  const reportingDeal = data.deals.find((deal) => deal.id === reporting);
  // A company that pulled out leaves the Sales person's list (the owner keeps it; «اتلغت» in the filter shows it).
  const shown = owner || stage ? data.deals : data.deals.filter((deal) => deal.status !== "cancelled");
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
            "كل صفقة الـSales يقفلها «تم التعاقد» بتظهر هنا بتفاصيلها. العمولة نسبة من قيمة الصفقة لكل واحد، وبتستحق لما العميل يدفع الفاتورة كلها. المالك بس اللي بيحددها ويعتمدها ويصرفها.",
            "Every deal a Sales person closes («Contracted») shows here with its details. The commission is each person's percent of the deal's value, due once the client pays the whole invoice. Only the owner sets, approves and pays it.",
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
              `${data.totals.unknown} عمولة لسه مالهاش رقم بالجنيه (مفيش قيمة للصفقة أو نسبة أو سعر صرف) ومش محسوبة فوق.`,
              `${data.totals.unknown} commissions have no figure in EGP yet (no deal value, rate or exchange rate) and are not counted above.`,
            )}
          </div>
        </div>
      )}

      {owner && <Rates data={data} />}

      {owner && data.uncovered.length > 0 && (
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="card__head">
            <Icon name="file" />
            <h3>{t("فواتير مش على صفقة", "Invoices on no deal")}</h3>
            <span className="muted">
              {t("اربطها بصفقتها من «ظبّط الصفقة»، أو لو اتباعت من غير شيت اضغط «اعمل صفقة منها».", "Link one to its deal under «Set up the deal», or if it was sold off the sheets press «Make a deal of it».")}
            </span>
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
                <button
                  className="btn btn--sm"
                  type="button"
                  disabled={fromInvoice.isPending}
                  onClick={() => fromInvoice.mutate(invoice.id, { onSuccess: (made) => setEditing(made.deal.id), onError: failed })}
                >
                  <Icon name="plus" size="sm" />
                  {t("اعمل صفقة منها", "Make a deal of it")}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="row" style={{ marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>{t("الصفقات", "Deals")}</h2>
        <div className="grow" />
        <select className="input" style={{ width: "auto" }} aria-label={t("اعرض", "Show")} value={stage} onChange={(event) => setStage(event.target.value)}>
          <option value="">{t("كل الصفقات", "All deals")}</option>
          {Object.entries(STAGE).map(([value, words]) => (
            <option key={value} value={value}>
              {t(...words)}
            </option>
          ))}
        </select>
      </div>

      {shown.map((deal) => (
        <DealCard
          key={deal.id}
          deal={deal}
          owner={owner}
          onEdit={() => setEditing(deal.id)}
          onCancel={() => setCancelling(deal)}
          onWithdraw={() => setWithdrawing(deal.id)}
          onPayment={() => setReporting(deal.id)}
        />
      ))}
      {shown.length === 0 && (
        <div className="card empty">
          <Icon name="star" size="xl" />
          <span>{t("مفيش صفقات لسه. أول ما حد من الـSales يقفل صفقة «تم التعاقد» هتظهر هنا.", "No deals yet. The moment a Sales person closes one («Contracted») it shows here.")}</span>
        </div>
      )}

      {editingDeal && <DealForm deal={editingDeal} data={data} onClose={() => setEditing(null)} />}
      {withdrawingDeal && <WithdrawForm deal={withdrawingDeal} onClose={() => setWithdrawing(null)} />}
      {reportingDeal && <PaymentForm deal={reportingDeal} onClose={() => setReporting(null)} />}
      {cancelling && (
        <Confirm
          title={t("الغي الصفقة", "Cancel the deal")}
          body={t("الصفقة وعمولاتها هيتلغوا (بيفضلوا متسجّلين). استخدمها لو الشركة اتعلّمت «تم التعاقد» بالغلط.", "The deal and its commissions are cancelled (and kept). Use it when the company was marked Contracted by mistake.")}
          yes={t("الغي الصفقة", "Cancel the deal")}
          danger
          busy={cancel.isPending}
          problem={problem}
          onYes={() =>
            cancel.mutate(cancelling.id, {
              onSuccess: () => {
                setCancelling(null);
                setProblem("");
              },
              onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش. جرّب تاني.", "Could not do it. Try again."))),
            })
          }
          onNo={() => {
            setCancelling(null);
            setProblem("");
          }}
        />
      )}
    </>
  );
}
