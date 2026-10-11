import { useState, type FormEvent } from "react";
import { Link, Navigate, useParams } from "react-router";
import { refusalText } from "../api/b2b";
import {
  useAddCost,
  useAddPayment,
  useDeleteCost,
  useDeletePayment,
  useInvoice,
  useInvoiceAction,
  useSaveCost,
  useSaveInvoice,
  type InvoiceCost,
  type InvoiceDetail,
  type InvoiceResponse,
} from "../api/finance";
import { useMe } from "../api/queries";
import { Icon } from "../components/Icon";
import { Loading } from "../components/Loading";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";
import { InvoiceStatusChip } from "./AccountsInvoicesPage";

const COST_AR: Record<string, string> = { translator: "مترجم", reviewer: "مراجعة", dtp: "تنسيق (DTP)", other: "حاجة تانية" };

function Problem({ text }: { text: string }) {
  if (!text) return null;
  return (
    <div className="note note--danger" role="alert" style={{ margin: "10px 0" }}>
      <Icon name="alert" />
      <div>{text}</div>
    </div>
  );
}

/** A figure, or «مش متقاس» when it cannot be known yet (never a made-up zero). */
function Figure({ value, unit }: { value: string | number | null; unit?: string }) {
  const { t } = usePreferences();
  if (value === null) return <span className="muted">{t("مش متقاس", "Not measured")}</span>;
  return (
    <span className="mono">
      {value}
      {unit ? ` ${unit}` : ""}
    </span>
  );
}

/** The invoice's figures and words. The amount and the currency only while it is a draft. */
function InvoiceForm({ invoice, currencies }: { invoice: InvoiceDetail; currencies: string[] }) {
  const { t, lang } = usePreferences();
  const toasts = useToasts();
  const save = useSaveInvoice(invoice.id);
  const draft = invoice.status === "draft";
  const closed = invoice.status === "cancelled";
  const [values, setValues] = useState({
    amount: invoice.amount,
    currency: invoice.currency,
    egp_rate: invoice.egp_rate,
    due_date: invoice.due_date,
    payment_terms: invoice.payment_terms,
    notes: invoice.notes,
  });
  const [problem, setProblem] = useState("");
  const set = (name: keyof typeof values, value: string) => setValues((before) => ({ ...before, [name]: value }));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (save.isPending || closed) return;
    setProblem("");
    save.mutate(values, {
      onSuccess: () => toasts.push({ level: "success", title: t("اتحفظ", "Saved") }),
      onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش أحفظ. اتأكد من الأرقام.", "Could not save. Check the figures."))),
    });
  };

  return (
    <form className="card" onSubmit={submit}>
      <div className="card__head">
        <Icon name="pen" />
        <h3>{t("الفاتورة", "The invoice")}</h3>
      </div>
      <div className="grid grid--main">
        <div className="field">
          <label htmlFor="i-amount">{t("المبلغ", "Amount")}</label>
          <input className="input mono" id="i-amount" inputMode="decimal" dir="ltr" maxLength={20} disabled={!draft} value={values.amount} onChange={(event) => set("amount", event.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="i-currency">{t("العملة", "Currency")}</label>
          <select className="input" id="i-currency" disabled={!draft} value={values.currency} onChange={(event) => set("currency", event.target.value)}>
            {currencies.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="i-rate">{t("سعر الصرف (كام جنيه للوحدة)", "Exchange rate (EGP per unit)")}</label>
          <input className="input mono" id="i-rate" inputMode="decimal" dir="ltr" maxLength={20} disabled={closed || values.currency === "EGP"} value={values.currency === "EGP" ? "1" : values.egp_rate} onChange={(event) => set("egp_rate", event.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="i-due">{t("ميعاد الدفع", "Due date")}</label>
          <input className="input" id="i-due" type="date" disabled={closed} value={values.due_date} onChange={(event) => set("due_date", event.target.value)} />
        </div>
      </div>
      <div className="field">
        <label htmlFor="i-terms">{t("شروط الدفع", "Payment terms")}</label>
        <input className="input" id="i-terms" maxLength={250} disabled={closed} value={values.payment_terms} onChange={(event) => set("payment_terms", event.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="i-notes">{t("كلام للعميل تحت الأرقام (إزاي يدفع، بيانات البنك)", "Words to the client under the figures (how to pay, bank details)")}</label>
        <textarea className="input" id="i-notes" dir="ltr" rows={3} maxLength={4000} disabled={closed} value={values.notes} onChange={(event) => set("notes", event.target.value)} />
      </div>
      <Problem text={problem} />
      {!closed && (
        <button className="btn" type="submit" disabled={save.isPending}>
          <Icon name="check" />
          {t("احفظ", "Save")}
        </button>
      )}
    </form>
  );
}

function Payments({ invoice }: { invoice: InvoiceDetail }) {
  const { t, lang } = usePreferences();
  const add = useAddPayment(invoice.id);
  const remove = useDeletePayment();
  const [amount, setAmount] = useState("");
  const [paidOn, setPaidOn] = useState("");
  const [method, setMethod] = useState("");
  const [problem, setProblem] = useState("");
  const open = invoice.status === "sent" || invoice.status === "partial";

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (add.isPending) return;
    setProblem("");
    add.mutate(
      { amount: amount.trim(), paid_on: paidOn, method: method.trim(), note: "" },
      {
        onSuccess: () => {
          setAmount("");
          setMethod("");
        },
        onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش أسجّل الدفع.", "Could not record the payment."))),
      },
    );
  };

  return (
    <div className="card">
      <div className="card__head">
        <Icon name="check-circle" />
        <h3>{t("الدفع", "Payments")}</h3>
        <span className="mono muted">
          {invoice.paid} / {invoice.amount} {invoice.currency}
        </span>
      </div>
      {invoice.payments.length > 0 ? (
        <table className="table">
          <tbody>
            {invoice.payments.map((payment) => (
              <tr key={payment.id} data-payment={payment.id}>
                <td className="mono">{payment.paid_on}</td>
                <td className="mono">
                  {payment.amount} {invoice.currency}
                </td>
                <td>{payment.method || "—"}</td>
                <td className="muted">{payment.by}</td>
                <td>
                  <button className="icon-btn" type="button" title={t("امسح الدفع ده (لو اتسجّل غلط)", "Remove this payment (if it was a mistake)")} aria-label={t("امسح الدفع", "Remove the payment")} onClick={() => remove.mutate(payment.id)}>
                    <Icon name="trash" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="muted">{t("لسه مفيش دفع.", "Nothing paid yet.")}</p>
      )}
      {open ? (
        <form className="row" onSubmit={submit} style={{ marginTop: 10, alignItems: "flex-end" }}>
          <div className="field" style={{ margin: 0 }}>
            <label htmlFor="p-amount">{t("المبلغ اللي اتدفع", "Amount paid")}</label>
            <input className="input mono" id="p-amount" inputMode="decimal" dir="ltr" maxLength={20} value={amount} placeholder={invoice.left} onChange={(event) => setAmount(event.target.value)} />
          </div>
          <div className="field" style={{ margin: 0 }}>
            <label htmlFor="p-date">{t("يوم الدفع", "Paid on")}</label>
            <input className="input" id="p-date" type="date" value={paidOn} onChange={(event) => setPaidOn(event.target.value)} />
          </div>
          <div className="field grow" style={{ margin: 0 }}>
            <label htmlFor="p-method">{t("الطريقة", "Method")}</label>
            <input className="input" id="p-method" maxLength={80} value={method} placeholder="Wise, PayPal, Bank" onChange={(event) => setMethod(event.target.value)} />
          </div>
          <button className="btn btn--primary" type="submit" disabled={add.isPending || !amount.trim()}>
            <Icon name="plus" />
            {t("سجّل الدفع", "Record the payment")}
          </button>
        </form>
      ) : (
        invoice.status === "draft" && <p className="muted">{t("الدفع بيتسجّل بعد ما الفاتورة تتبعت.", "Payments are recorded once the invoice is sent.")}</p>
      )}
      <Problem text={problem} />
    </div>
  );
}

function CostRow({ cost }: { cost: InvoiceCost }) {
  const { t, lang } = usePreferences();
  const save = useSaveCost();
  const remove = useDeleteCost();
  const [amount, setAmount] = useState(cost.amount ?? "");
  const kind = lang === "ar" ? (COST_AR[cost.kind] ?? cost.kind) : cost.kind;
  return (
    <tr data-cost={cost.id}>
      <td>
        {kind}
        {cost.person && <div className="muted">{cost.person}</div>}
        {cost.description && <div className="muted">{cost.description}</div>}
      </td>
      <td className="mono">
        {cost.words != null ? `${cost.words.toLocaleString()} ${t("كلمة", "words")}` : "—"}
        {cost.rate_per_250 && <div className="muted">{t(`${cost.rate_per_250} للـ250`, `${cost.rate_per_250} per 250`)}</div>}
      </td>
      <td>
        <div className="row row--tight" style={{ flexWrap: "nowrap" }}>
          <input
            className="input mono"
            style={{ width: 110 }}
            inputMode="decimal"
            dir="ltr"
            aria-label={t("المبلغ بالجنيه", "Amount in EGP")}
            value={amount}
            placeholder={t("مش متقاس", "Not measured")}
            onChange={(event) => setAmount(event.target.value)}
          />
          <button className="btn btn--sm" type="button" disabled={save.isPending || amount === (cost.amount ?? "")} onClick={() => save.mutate({ costId: cost.id, amount: amount.trim(), description: cost.description })}>
            {t("احفظ", "Save")}
          </button>
          <button className="icon-btn" type="button" title={t("امسح التكلفة", "Delete the cost")} aria-label={t("امسح التكلفة", "Delete the cost")} onClick={() => remove.mutate(cost.id)}>
            <Icon name="trash" />
          </button>
        </div>
      </td>
    </tr>
  );
}

function Costs({ invoice, kinds }: { invoice: InvoiceDetail; kinds: InvoiceResponse["cost_kinds"] }) {
  const { t, lang } = usePreferences();
  const add = useAddCost(invoice.id);
  const [kind, setKind] = useState("reviewer");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [problem, setProblem] = useState("");
  const { profit } = invoice;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (add.isPending) return;
    setProblem("");
    add.mutate(
      { kind, amount: amount.trim(), description: description.trim() },
      {
        onSuccess: () => {
          setAmount("");
          setDescription("");
        },
        onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش أضيف التكلفة.", "Could not add the cost."))),
      },
    );
  };

  return (
    <div className="card">
      <div className="card__head">
        <Icon name="chart" />
        <h3>{t("التكلفة والربح (بالجنيه)", "Cost and profit (EGP)")}</h3>
      </div>
      <div className="grid grid--4" style={{ marginBottom: 12 }}>
        <div className="kpi" data-profit="price">
          <div className="kpi__value">
            <Figure value={profit.price_egp} />
          </div>
          <div className="kpi__label">{t("سعر العميل بالجنيه", "Client price in EGP")}</div>
        </div>
        <div className="kpi" data-profit="costs">
          <div className="kpi__value">
            <Figure value={profit.costs} />
          </div>
          <div className="kpi__label">{t("التكلفة", "Costs")}</div>
        </div>
        <div className={profit.profit !== null && Number(profit.profit) < 0 ? "kpi kpi--danger" : "kpi kpi--ok"} data-profit="profit">
          <div className="kpi__value">
            <Figure value={profit.profit} />
          </div>
          <div className="kpi__label">{t("الربح", "Profit")}</div>
        </div>
        <div className="kpi" data-profit="margin">
          <div className="kpi__value">
            <Figure value={profit.margin} unit="%" />
          </div>
          <div className="kpi__label">{t("نسبة الربح", "Margin")}</div>
        </div>
      </div>
      {invoice.task ? (
        <>
          <table className="table">
            <tbody>
              {invoice.costs.map((cost) => (
                <CostRow key={`${cost.id}-${cost.amount}`} cost={cost} />
              ))}
              {invoice.costs.length === 0 && (
                <tr>
                  <td className="muted">{t("لسه مفيش تكاليف.", "No costs yet.")}</td>
                </tr>
              )}
            </tbody>
          </table>
          <form className="row" onSubmit={submit} style={{ marginTop: 10, alignItems: "flex-end" }}>
            <div className="field" style={{ margin: 0 }}>
              <label htmlFor="c-kind">{t("تكلفة تانية", "Another cost")}</label>
              <select className="input" id="c-kind" value={kind} onChange={(event) => setKind(event.target.value)}>
                {kinds.map((one) => (
                  <option key={one.value} value={one.value}>
                    {lang === "ar" ? (COST_AR[one.value] ?? one.label) : one.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field" style={{ margin: 0 }}>
              <label htmlFor="c-amount">{t("المبلغ بالجنيه", "Amount in EGP")}</label>
              <input className="input mono" id="c-amount" inputMode="decimal" dir="ltr" maxLength={20} value={amount} onChange={(event) => setAmount(event.target.value)} />
            </div>
            <div className="field grow" style={{ margin: 0 }}>
              <label htmlFor="c-what">{t("إيه هي (اختياري)", "What it is (optional)")}</label>
              <input className="input" id="c-what" maxLength={200} value={description} onChange={(event) => setDescription(event.target.value)} />
            </div>
            <button className="btn" type="submit" disabled={add.isPending || !amount.trim()}>
              <Icon name="plus" />
              {t("ضيف", "Add")}
            </button>
          </form>
          <Problem text={problem} />
          <p className="muted" style={{ marginTop: 10 }}>
            {t(
              "تكلفة المترجم بتتحسب لوحدها لما التاسك تتسلّم: كلماته ÷ 250 × السعر المتفق عليه معاه (من صفحة الموظف). مترجم مالوش سعر بيبان «مش متقاس» لحد ما تكتب المبلغ.",
              "A translator's cost is worked out when the task is delivered: their words ÷ 250 × the price agreed with them (on the employee page). One with no agreed price reads «Not measured» until you type the amount.",
            )}
          </p>
        </>
      ) : (
        <p className="muted">{t("الفاتورة دي مالهاش تاسك.", "This invoice has no task.")}</p>
      )}
    </div>
  );
}

/** One client invoice: its figures, sending it, the payments, and what the project cost and earned. */
export function AccountsInvoicePage() {
  const { t, lang } = usePreferences();
  const toasts = useToasts();
  const me = useMe();
  const { id } = useParams();
  const invoiceId = /^\d{1,9}$/.test(id ?? "") ? Number(id) : 0;
  const allowed = me.data !== undefined && (me.data.user.role === "accounting" || me.data.user.is_admin);
  const detail = useInvoice(allowed ? invoiceId : 0);
  const act = useInvoiceAction(invoiceId);
  const [problem, setProblem] = useState("");

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!invoiceId) return <Navigate to="/accounts/invoices" replace />;
  if (detail.isError) {
    return (
      <div className="card empty" role="alert">
        <Icon name="alert" size="xl" />
        <span>{t("الفاتورة دي مش موجودة.", "This invoice does not exist.")}</span>
      </div>
    );
  }
  const data = detail.data;
  if (!data) return <Loading />;
  const invoice = data.invoice;
  const client = invoice.client;

  const run = (action: "send" | "cancel") => {
    if (act.isPending) return;
    setProblem("");
    act.mutate(action, {
      onSuccess: () => toasts.push({ level: "success", title: action === "send" ? t("الفاتورة اتبعتت للعميل", "The invoice was sent to the client") : t("الفاتورة اتلغت", "The invoice was cancelled") }),
      onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش. جرّب تاني.", "Could not. Try again."))),
    });
  };

  return (
    <>
      <div className="page-head">
        <h1 className="mono">{invoice.code}</h1>
        <span className="page-head__sub">
          <InvoiceStatusChip status={invoice.status} overdue={invoice.overdue} />{" "}
          {t("العميل", "Client")} <span className="mono">{client.code}</span>
          {client.company || client.name ? ` · ${client.company || client.name}` : ""}
          {invoice.task && (
            <>
              {" · "}
              <Link className="mono" to={`/tasks/${encodeURIComponent(invoice.task)}`}>
                {invoice.task}
              </Link>
            </>
          )}
          {invoice.quotation && <span className="mono"> · {invoice.quotation}</span>}
          {invoice.sales && ` · ${invoice.sales}`}
        </span>
      </div>

      <div className="row" style={{ marginBottom: 14 }}>
        <Link className="btn btn--sm btn--ghost" to="/accounts/invoices">
          {t("كل الفواتير", "All invoices")}
        </Link>
        <div className="grow" />
        {invoice.status === "draft" && (
          <button className="btn btn--primary" type="button" disabled={act.isPending} onClick={() => run("send")}>
            <Icon name="send" />
            {t("ابعت الفاتورة للعميل", "Send the invoice to the client")}
          </button>
        )}
        {invoice.status !== "cancelled" && invoice.payments.length === 0 && (
          <button className="btn btn--danger" type="button" disabled={act.isPending} onClick={() => run("cancel")}>
            {t("الغي الفاتورة", "Cancel the invoice")}
          </button>
        )}
      </div>
      <Problem text={problem} />
      {invoice.status === "draft" && (
        <div className="note note--info" style={{ marginBottom: 14 }}>
          <Icon name="info" />
          <div>
            {t(
              "بتتبعت بالإيميل من ميل الشركة، وردّ العميل بيروح للـSales اللي باع. اكتب سعر الصرف الأول.",
              "It goes by e-mail from the company mailbox, and the client's answer goes to the Sales person who sold it. Write the exchange rate first.",
            )}
          </div>
        </div>
      )}

      <div className="grid grid--2">
        <InvoiceForm key={`${invoice.id}-${invoice.status}`} invoice={invoice} currencies={data.currencies} />
        <Payments invoice={invoice} />
      </div>
      <div style={{ marginTop: 14 }}>
        <Costs invoice={invoice} kinds={data.cost_kinds} />
      </div>
    </>
  );
}
