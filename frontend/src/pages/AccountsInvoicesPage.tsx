import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router";
import { refusalText } from "../api/b2b";
import { useInvoices, useInvoiceTask, type InvoiceStatus, type InvoicesResponse } from "../api/finance";
import { useMe } from "../api/queries";
import { Icon } from "../components/Icon";
import { Loading } from "../components/Loading";
import { Modal } from "../components/Modal";
import { usePreferences } from "../i18n/Preferences";

const STATUS: Record<InvoiceStatus, [string, string, string]> = {
  draft: ["مسودة", "Draft", ""],
  sent: ["اتبعتت", "Sent", "chip--open"],
  partial: ["اتدفع جزء", "Partly paid", "chip--open"],
  paid: ["اتدفعت", "Paid", "chip--replied"],
  cancelled: ["اتلغت", "Cancelled", ""],
};

/** Where an invoice stands; an overdue one says so in red, whatever else it is. */
export function InvoiceStatusChip({ status, overdue }: { status: InvoiceStatus; overdue: boolean }) {
  const { t } = usePreferences();
  const [ar, en, tone] = STATUS[status] ?? [status, status, ""];
  return (
    <>
      <span className={`chip chip--sm ${tone}`.trim()}>{t(ar, en)}</span>
      {overdue && <span className="chip chip--sm deadline--late">{t("متأخرة", "Overdue")}</span>}
    </>
  );
}

const FILTERS: { key: string; label: [string, string] }[] = [
  { key: "all", label: ["الكل", "All"] },
  { key: "draft", label: ["مسودات", "Drafts"] },
  { key: "open", label: ["مستنية الدفع", "Awaiting payment"] },
  { key: "overdue", label: ["متأخرة", "Overdue"] },
  { key: "paid", label: ["اتدفعت", "Paid"] },
  { key: "cancelled", label: ["اتلغت", "Cancelled"] },
];

/** Invoice by hand a delivered task with no quotation behind it: the amount and the currency. */
function InvoiceTask({ task, currencies, onClose }: { task: InvoicesResponse["uninvoiced"][number]; currencies: string[]; onClose: () => void }) {
  const { t, lang } = usePreferences();
  const navigate = useNavigate();
  const make = useInvoiceTask();
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState(currencies[0] ?? "USD");
  const [problem, setProblem] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (make.isPending) return;
    setProblem("");
    make.mutate(
      { code: task.code, amount: amount.trim(), currency },
      {
        onSuccess: (answer) => navigate(`/accounts/invoices/${answer.invoice.id}`),
        onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش أعمل الفاتورة. اتأكد من المبلغ.", "Could not make the invoice. Check the amount."))),
      },
    );
  };

  return (
    <Modal title={`${t("فاتورة لـ", "Invoice for ")}${task.code}`} icon="file" busy={make.isPending} onClose={onClose}>
      <form onSubmit={submit}>
        <p className="muted">
          {t("العميل", "Client")} <span className="mono">{task.client_code}</span> · {task.title}
        </p>
        <div className="row">
          <div className="field grow">
            <label htmlFor="inv-amount">{t("المبلغ", "Amount")}</label>
            <input className="input mono" id="inv-amount" inputMode="decimal" dir="ltr" maxLength={20} value={amount} onChange={(event) => setAmount(event.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="inv-currency">{t("العملة", "Currency")}</label>
            <select className="input" id="inv-currency" value={currency} onChange={(event) => setCurrency(event.target.value)}>
              {currencies.map((code) => (
                <option key={code} value={code}>
                  {code}
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
        <button className="btn btn--primary" type="submit" disabled={make.isPending || !amount.trim()}>
          <Icon name="plus" />
          {t("اعمل الفاتورة", "Make the invoice")}
        </button>
      </form>
    </Modal>
  );
}

/**
 * The client invoices (Accounting's and the owner's): what is owed per currency, the invoices by where they stand, and the
 * delivered tasks with no invoice yet. Codes only: the client's name is on the invoice's own page, for who may see it.
 */
export function AccountsInvoicesPage() {
  const { t } = usePreferences();
  const me = useMe();
  const [params, setParams] = useSearchParams();
  const asked = params.get("show") ?? "all";
  const show = FILTERS.some((one) => one.key === asked) ? asked : "all";
  const allowed = me.data !== undefined && (me.data.user.role === "accounting" || me.data.user.is_admin);
  const list = useInvoices(show, allowed);
  const [invoicing, setInvoicing] = useState<InvoicesResponse["uninvoiced"][number] | null>(null);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  const data = list.data;

  return (
    <>
      <div className="page-head">
        <h1>{t("فواتير العملاء", "Client invoices")}</h1>
        <span className="page-head__sub">
          {t(
            "الفاتورة بتتعمل مسودة لوحدها لما تاسك جاية من عرض سعر تتسلّم. راجعها وابعتها وسجّل الدفع.",
            "An invoice is drafted by itself when a task made from a quotation is delivered. Check it, send it, and record what is paid.",
          )}
        </span>
      </div>

      {data && Object.keys(data.owed).length > 0 && (
        <div className="grid grid--4" style={{ marginBottom: 14 }}>
          {Object.entries(data.owed).map(([currency, amount]) => (
            <div className="kpi kpi--warn" key={currency} data-owed={currency}>
              <div className="kpi__value mono">
                {Number(amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} {currency}
              </div>
              <div className="kpi__label">{t("لسه ماتدفعش", "Still owed")}</div>
            </div>
          ))}
        </div>
      )}

      <div className="card" style={{ marginBottom: 14 }}>
        <div className="row" style={{ marginBottom: 12 }} role="group" aria-label={t("اعرض", "Show")}>
          {FILTERS.map((one) => (
            <button
              key={one.key}
              type="button"
              className={one.key === show ? "btn btn--sm btn--primary" : "btn btn--sm"}
              aria-pressed={one.key === show}
              onClick={() => setParams(one.key === "all" ? {} : { show: one.key })}
            >
              {t(one.label[0], one.label[1])}
            </button>
          ))}
        </div>
        {data ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("الفاتورة", "Invoice")}</th>
                  <th>{t("العميل", "Client")}</th>
                  <th>{t("التاسك", "Task")}</th>
                  <th>{t("المبلغ", "Amount")}</th>
                  <th>{t("الباقي", "Left")}</th>
                  <th>{t("الميعاد", "Due")}</th>
                  <th>{t("الحالة", "Status")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.invoices.map((row) => (
                  <tr key={row.id} data-invoice={row.code}>
                    <td>
                      <strong className="mono">{row.code}</strong>
                      {row.sales && <div className="muted">{row.sales}</div>}
                    </td>
                    <td className="mono">{row.client_code}</td>
                    <td className="mono">{row.task || "—"}</td>
                    <td className="mono">
                      {row.amount} {row.currency}
                    </td>
                    <td className="mono">{row.status === "cancelled" ? "—" : `${row.left} ${row.currency}`}</td>
                    <td className={row.overdue ? "mono deadline--late" : "mono"}>{row.due_date || "—"}</td>
                    <td>
                      <InvoiceStatusChip status={row.status} overdue={row.overdue} />
                    </td>
                    <td>
                      <Link className="btn btn--sm" to={`/accounts/invoices/${row.id}`}>
                        {t("افتح", "Open")}
                      </Link>
                    </td>
                  </tr>
                ))}
                {data.invoices.length === 0 && (
                  <tr>
                    <td colSpan={8} className="empty">
                      <Icon name="file" size="xl" />
                      <span>{t("مفيش فواتير هنا.", "No invoices here.")}</span>
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

      {data && data.uninvoiced.length > 0 && (
        <div className="card" id="uninvoiced">
          <div className="card__head">
            <Icon name="layers" />
            <h3>{t("تاسكات اتسلّمت ومالهاش فاتورة", "Delivered tasks with no invoice")}</h3>
            <span className="chip chip--sm mono">{data.uninvoiced.length}</span>
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("التاسك", "Task")}</th>
                  <th>{t("العميل", "Client")}</th>
                  <th>{t("الكلمات", "Words")}</th>
                  <th>{t("اتسلّمت", "Delivered")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.uninvoiced.map((task) => (
                  <tr key={task.code} data-uninvoiced={task.code}>
                    <td>
                      <strong className="mono">{task.code}</strong>
                      <div className="muted">{task.title}</div>
                    </td>
                    <td className="mono">{task.client_code}</td>
                    <td className="mono">{task.words || "—"}</td>
                    <td className="mono">{task.delivered_at}</td>
                    <td>
                      <button className="btn btn--sm" type="button" onClick={() => setInvoicing(task)}>
                        <Icon name="plus" />
                        {t("اعمل فاتورة", "Make an invoice")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {invoicing && data && <InvoiceTask task={invoicing} currencies={data.currencies} onClose={() => setInvoicing(null)} />}
    </>
  );
}
