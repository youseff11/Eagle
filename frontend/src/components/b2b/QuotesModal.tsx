import { useState, type FormEvent } from "react";
import {
  refusalText,
  useCreateQuotation,
  useQuotationAction,
  useQuotations,
  useSaveQuotation,
  type Quotation,
  type QuotationStatus,
  type QuotationValues,
  type QuotationsResponse,
} from "../../api/b2b";
import { usePreferences } from "../../i18n/Preferences";
import { Icon } from "../Icon";
import { Loading } from "../Loading";
import { Modal } from "../Modal";
import { useToasts } from "../Toasts";

/** The words for where a quotation stands, and the look of its chip. */
const STATUS: Record<QuotationStatus, [string, string, string]> = {
  draft: ["مسودة", "Draft", ""],
  sent: ["اتبعت", "Sent", "chip--open"],
  accepted: ["اتقبل", "Accepted", "chip--replied"],
  rejected: ["اترفض", "Turned down", "deadline--late"],
};

export function QuoteStatus({ status }: { status: QuotationStatus }) {
  const { t } = usePreferences();
  const [ar, en, tone] = STATUS[status] ?? [status, status, ""];
  return <span className={`chip chip--sm ${tone}`.trim()}>{t(ar, en)}</span>;
}

const SERVICE_AR: Record<string, string> = {
  translation: "ترجمة",
  review: "مراجعة / تدقيق",
  certified: "ترجمة معتمدة",
  localization: "توطين (Localization)",
  transcription: "تفريغ نصي",
  dtp: "تنسيق (DTP)",
  interpreting: "ترجمة فورية",
  other: "حاجة تانية",
};
const UNIT_AR: Record<string, string> = { words: "كلمة", pages: "صفحة", hours: "ساعة", project: "المشروع كله" };

const EMPTY: QuotationValues = {
  source_lang: "",
  target_lang: "",
  service: "translation",
  unit: "words",
  quantity: 0,
  rate: "",
  discount_percent: "0",
  currency: "USD",
  deadline: "",
  payment_terms: "",
  notes: "",
};

/** The figures of a quotation, and the total they make (the server writes the real one, to the cent). */
function QuoteForm({ data, quote, onDone }: { data: QuotationsResponse; quote: Quotation | null; onDone: () => void }) {
  const { t, lang } = usePreferences();
  const create = useCreateQuotation(data.lead.id);
  const save = useSaveQuotation();
  const [values, setValues] = useState<QuotationValues>(() => {
    if (!quote) return { ...EMPTY, source_lang: "EN", target_lang: "AR" };
    const { source_lang, target_lang, service, unit, quantity, rate, discount_percent, currency, deadline, payment_terms, notes } = quote;
    return { source_lang, target_lang, service, unit, quantity, rate, discount_percent, currency, deadline, payment_terms, notes };
  });
  const [problem, setProblem] = useState("");
  const busy = create.isPending || save.isPending;
  const set = <K extends keyof QuotationValues>(name: K, value: QuotationValues[K]) => setValues((before) => ({ ...before, [name]: value }));
  const rate = Number(values.rate);
  const discount = Number(values.discount_percent || "0");
  const shown = Number.isFinite(rate) && Number.isFinite(discount) ? ((values.quantity || 0) * rate * (100 - discount)) / 100 : 0;
  const choiceWord = (value: string, words: Record<string, string>, english: string) => (lang === "ar" ? (words[value] ?? english) : english);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setProblem("");
    const onError = (failure: unknown) => setProblem(refusalText(failure, lang, t("مقدرتش أحفظ. اتأكد من الأرقام.", "Could not save. Check the figures.")));
    if (quote) save.mutate({ id: quote.id, values }, { onSuccess: onDone, onError });
    else create.mutate(values, { onSuccess: onDone, onError });
  };

  return (
    <form onSubmit={submit} data-quote-form={quote?.code ?? "new"}>
      <div className="grid grid--main">
        <div className="field">
          <label htmlFor="q-source">{t("من لغة", "From")}</label>
          <input className="input" id="q-source" list="q-languages" maxLength={40} value={values.source_lang} onChange={(event) => set("source_lang", event.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="q-target">{t("للغة", "To")}</label>
          <input className="input" id="q-target" list="q-languages" maxLength={40} value={values.target_lang} onChange={(event) => set("target_lang", event.target.value)} />
        </div>
        <datalist id="q-languages">
          {data.languages.map((one) => (
            <option key={one.code} value={one.code}>
              {lang === "ar" ? one.ar : one.en}
            </option>
          ))}
        </datalist>
        <div className="field">
          <label htmlFor="q-service">{t("الخدمة", "Service")}</label>
          <select className="input" id="q-service" value={values.service} onChange={(event) => set("service", event.target.value)}>
            {data.services.map((one) => (
              <option key={one.value} value={one.value}>
                {choiceWord(one.value, SERVICE_AR, one.label)}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="q-unit">{t("بالـ", "Priced by")}</label>
          <select className="input" id="q-unit" value={values.unit} onChange={(event) => set("unit", event.target.value)}>
            {data.units.map((one) => (
              <option key={one.value} value={one.value}>
                {choiceWord(one.value, UNIT_AR, one.label)}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="q-quantity">{t("الكمية", "Quantity")}</label>
          <input
            className="input mono"
            id="q-quantity"
            type="number"
            min={1}
            value={values.quantity || ""}
            onChange={(event) => set("quantity", Math.max(0, Math.floor(Number(event.target.value) || 0)))}
          />
        </div>
        <div className="field">
          <label htmlFor="q-rate">{t("سعر الوحدة", "Unit rate")}</label>
          <input className="input mono" id="q-rate" inputMode="decimal" dir="ltr" maxLength={20} value={values.rate} placeholder="0.08" onChange={(event) => set("rate", event.target.value.trim())} />
        </div>
        <div className="field">
          <label htmlFor="q-discount">{t("الخصم %", "Discount %")}</label>
          <input className="input mono" id="q-discount" inputMode="decimal" dir="ltr" maxLength={6} value={values.discount_percent} onChange={(event) => set("discount_percent", event.target.value.trim())} />
        </div>
        <div className="field">
          <label htmlFor="q-currency">{t("العملة", "Currency")}</label>
          <select className="input" id="q-currency" value={values.currency} onChange={(event) => set("currency", event.target.value)}>
            {data.currencies.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="q-deadline">{t("الديدلاين", "Deadline")}</label>
          <input className="input" id="q-deadline" type="date" value={values.deadline} onChange={(event) => set("deadline", event.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="q-terms">{t("شروط الدفع", "Payment terms")}</label>
          <input className="input" id="q-terms" maxLength={250} value={values.payment_terms} placeholder="50% upfront, 50% on delivery" onChange={(event) => set("payment_terms", event.target.value)} />
        </div>
      </div>
      <div className="field">
        <label htmlFor="q-notes">{t("كلام للشركة تحت الأرقام (اختياري، بالإنجليزي)", "Words to the company under the figures (optional)")}</label>
        <textarea className="input" id="q-notes" dir="ltr" rows={3} maxLength={4000} value={values.notes} onChange={(event) => set("notes", event.target.value)} />
      </div>
      <div className="row">
        <strong>{t("الإجمالي تقريبًا", "Total, about")}</strong>
        <span className="mono" data-quote-total>
          {shown.toFixed(2)} {values.currency}
        </span>
        <div className="grow" />
        <button className="btn btn--primary" type="submit" disabled={busy}>
          <Icon name="check" />
          {quote ? t("احفظ المسودة", "Save the draft") : t("اعمل المسودة", "Make the draft")}
        </button>
      </div>
      {problem && (
        <div className="note note--danger" role="alert" style={{ marginTop: 10 }}>
          <Icon name="alert" />
          <div>{problem}</div>
        </div>
      )}
    </form>
  );
}

/**
 * A company's quotations: the history (every one kept as the company saw it), a new one, and what may be done to each - a
 * draft is changed, sent or deleted; a sent one is copied (that is how a price changes) or answered: accepted or turned
 * down. Accepted makes the company Won and tells the operation to make the task. The server decides who may do what
 * (`can_make`, `can_decide`); this draws the answer.
 */
export function QuotesModal({ leadId, onClose }: { leadId: number; onClose: () => void }) {
  const { t, lang } = usePreferences();
  const toasts = useToasts();
  const list = useQuotations(leadId);
  const act = useQuotationAction();
  const [editing, setEditing] = useState<Quotation | "new" | null>(null);
  const [problem, setProblem] = useState("");
  const data = list.data;

  const run = (quote: Quotation, action: "send" | "copy" | "delete" | "decide", accepted?: boolean) => {
    if (act.isPending) return;
    setProblem("");
    act.mutate(
      { id: quote.id, action, accepted },
      {
        onSuccess: (answer) => {
          const said: Record<string, [string, string]> = {
            send: ["العرض اتبعت بالإيميل", "The quotation was e-mailed"],
            copy: ["اتعملت نسخة جديدة مسودة", "A new draft copy was made"],
            delete: ["المسودة اتمسحت", "The draft was deleted"],
            decide: accepted ? ["اتسجّل إن العرض اتقبل، والأوبريشن اتبلّغ يعمل التاسك", "Recorded as accepted; the operation was told to make the task"] : ["اتسجّل إن العرض اترفض", "Recorded as turned down"],
          };
          const [ar, en] = said[action] ?? ["تمام", "Done"];
          toasts.push({ level: "success", title: t(ar, en) });
          if (action === "copy") setEditing(answer.quotation);
        },
        onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش. جرّب تاني.", "Could not. Try again."))),
      },
    );
  };

  return (
    <Modal title={data ? `${t("عروض الأسعار", "Quotations")} · ${data.lead.company_name}` : t("عروض الأسعار", "Quotations")} icon="file" busy={act.isPending} wide onClose={onClose}>
      {!data ? (
        list.isError ? (
          <div className="note note--danger" role="alert">
            <Icon name="alert" />
            <div>{t("حصلت مشكلة في التحميل.", "Could not load.")}</div>
          </div>
        ) : (
          <Loading className="empty" />
        )
      ) : editing ? (
        <>
          <button className="btn btn--sm btn--ghost" type="button" onClick={() => setEditing(null)} style={{ marginBottom: 8 }}>
            {t("رجوع للعروض", "Back to the quotations")}
          </button>
          <QuoteForm data={data} quote={editing === "new" ? null : editing} onDone={() => setEditing(null)} />
        </>
      ) : (
        <>
          {data.can_make && (
            <button className="btn btn--primary" type="button" onClick={() => setEditing("new")} style={{ marginBottom: 10 }}>
              <Icon name="plus" />
              {t("عرض سعر جديد", "New quotation")}
            </button>
          )}
          {data.can_make && !data.lead.email && (
            <div className="note note--info" style={{ marginBottom: 10 }}>
              <Icon name="info" />
              <div>{t("الشركة مالهاش إيميل في الشيت: العرض بيتبعت بالإيميل، فضيفه الأول.", "The company has no e-mail on the sheet: quotations go by e-mail, so add one first.")}</div>
            </div>
          )}
          {problem && (
            <div className="note note--danger" role="alert" style={{ marginBottom: 10 }}>
              <Icon name="alert" />
              <div>{problem}</div>
            </div>
          )}
          {data.quotations.length === 0 ? (
            <div className="empty">
              <Icon name="file" size="xl" />
              <span>{t("مفيش عروض أسعار لسه.", "No quotations yet.")}</span>
            </div>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("العرض", "Quotation")}</th>
                    <th>{t("اللغتين", "Pair")}</th>
                    <th>{t("الكمية", "Quantity")}</th>
                    <th>{t("الإجمالي", "Total")}</th>
                    <th>{t("الحالة", "Status")}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.quotations.map((quote) => (
                    <tr key={quote.id} data-quotation={quote.code}>
                      <td>
                        <strong className="mono">{quote.code}</strong>
                        <div className="muted mono">{quote.sent_at || quote.created_at}</div>
                      </td>
                      <td className="mono">
                        {quote.source_lang} &gt; {quote.target_lang}
                      </td>
                      <td className="mono">
                        {quote.quantity.toLocaleString()} {lang === "ar" ? (UNIT_AR[quote.unit] ?? quote.unit) : quote.unit}
                      </td>
                      <td className="mono">
                        {quote.total} {quote.currency}
                      </td>
                      <td>
                        <QuoteStatus status={quote.status} />
                        {quote.task && <div className="muted mono">{quote.task}</div>}
                      </td>
                      <td>
                        <div className="row row--tight" style={{ flexWrap: "nowrap" }}>
                          {data.can_make && quote.status === "draft" && (
                            <>
                              <button className="btn btn--sm btn--primary" type="button" disabled={act.isPending || !data.lead.email} onClick={() => run(quote, "send")}>
                                <Icon name="send" />
                                {t("ابعته", "Send it")}
                              </button>
                              <button className="btn btn--sm" type="button" onClick={() => setEditing(quote)}>
                                {t("عدّل", "Edit")}
                              </button>
                              <button className="icon-btn" type="button" title={t("امسح المسودة", "Delete the draft")} aria-label={t("امسح المسودة", "Delete the draft")} onClick={() => run(quote, "delete")}>
                                <Icon name="trash" />
                              </button>
                            </>
                          )}
                          {data.can_decide && quote.status === "sent" && (
                            <>
                              <button className="btn btn--sm btn--ok" type="button" disabled={act.isPending} onClick={() => run(quote, "decide", true)}>
                                {t("اتقبل", "Accepted")}
                              </button>
                              <button className="btn btn--sm btn--danger" type="button" disabled={act.isPending} onClick={() => run(quote, "decide", false)}>
                                {t("اترفض", "Turned down")}
                              </button>
                            </>
                          )}
                          {data.can_make && quote.status !== "draft" && (
                            <button className="btn btn--sm" type="button" disabled={act.isPending} onClick={() => run(quote, "copy")}>
                              {t("نسخة جديدة", "New copy")}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="muted" style={{ marginTop: 10 }}>
            {t(
              "العرض اللي اتبعت مابيتغيّرش: لو السعر اتغيّر اعمل «نسخة جديدة» وابعتها. أول ما تدوس «اتقبل» الشركة بتبقى Won والأوبريشن بيوصله تنبيه يعمل التاسك.",
              "A sent quotation is never changed: if the price changes, make a «New copy» and send it. Press «Accepted» and the company is Won and the operation is told to make the task.",
            )}
          </p>
        </>
      )}
    </Modal>
  );
}
