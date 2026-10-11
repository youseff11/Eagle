import { useState, type FormEvent } from "react";
import { refusalText, useSaveTarget, useTargets, type TargetMetric, type TargetProgress, type TargetRow } from "../../api/b2b";
import { usePreferences } from "../../i18n/Preferences";
import { Icon } from "../Icon";

const METRIC: Record<TargetMetric, [string, string]> = {
  new_leads: ["شركات جديدة", "New leads"],
  contacted: ["اتواصلنا معاهم", "Contacted"],
  quotations: ["عروض اتبعتت", "Quotations sent"],
  won: ["Won", "Won"],
  revenue: ["قيمة اللي اتقبل", "Accepted value"],
};
const COUNTS: TargetMetric[] = ["new_leads", "contacted", "quotations", "won"];

/** How far a person is towards one figure: done / target and a bar; no target = a dash (not 0%). */
function Progress({ figure }: { figure: TargetProgress }) {
  if (figure.target === null) return <span className="muted">—</span>;
  const percent = figure.percent ?? 0;
  const tone = percent >= 100 ? "var(--ok)" : percent < 50 ? "var(--warn)" : "var(--brand)";
  return (
    <div style={{ minWidth: 90 }}>
      <span className="mono">
        {figure.done} / {figure.target}
      </span>
      <div style={{ height: 6, borderRadius: 3, background: "var(--surface-2)", marginTop: 4 }} aria-hidden="true">
        <div style={{ width: `${Math.min(percent, 100)}%`, height: "100%", borderRadius: 3, background: tone }} />
      </div>
      <small className="muted mono">{percent}%</small>
    </div>
  );
}

/** The manager's boxes for one person's month. Empty = no target for that figure. */
function TargetForm({ row, month, currencies, onDone }: { row: TargetRow; month: string; currencies: string[]; onDone: () => void }) {
  const { t, lang } = usePreferences();
  const save = useSaveTarget();
  const first = (metric: TargetMetric) => {
    const value = row.progress[metric].target;
    return value === null ? "" : String(value);
  };
  const [values, setValues] = useState<Record<TargetMetric, string>>({
    new_leads: first("new_leads"),
    contacted: first("contacted"),
    quotations: first("quotations"),
    won: first("won"),
    revenue: first("revenue"),
  });
  const [currency, setCurrency] = useState(row.currency);
  const [problem, setProblem] = useState("");
  const count = (value: string) => (value.trim() === "" ? null : Math.max(0, Math.floor(Number(value) || 0)));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (save.isPending) return;
    setProblem("");
    save.mutate(
      {
        person: row.person.id,
        month,
        new_leads: count(values.new_leads),
        contacted: count(values.contacted),
        quotations: count(values.quotations),
        won: count(values.won),
        revenue: values.revenue.trim() === "" ? null : values.revenue.trim(),
        revenue_currency: currency,
      },
      { onSuccess: onDone, onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش أحفظ. اتأكد من الأرقام.", "Could not save. Check the figures."))) },
    );
  };

  return (
    <form onSubmit={submit} data-target-form={row.person.id}>
      <div className="row" style={{ alignItems: "flex-end" }}>
        {COUNTS.map((metric) => (
          <div className="field" style={{ margin: 0, width: 110 }} key={metric}>
            <label htmlFor={`t-${row.person.id}-${metric}`}>{t(...METRIC[metric])}</label>
            <input
              className="input mono"
              id={`t-${row.person.id}-${metric}`}
              type="number"
              min={0}
              value={values[metric]}
              onChange={(event) => setValues((before) => ({ ...before, [metric]: event.target.value }))}
            />
          </div>
        ))}
        <div className="field" style={{ margin: 0, width: 130 }}>
          <label htmlFor={`t-${row.person.id}-revenue`}>{t(...METRIC.revenue)}</label>
          <input
            className="input mono"
            id={`t-${row.person.id}-revenue`}
            inputMode="decimal"
            dir="ltr"
            value={values.revenue}
            onChange={(event) => setValues((before) => ({ ...before, revenue: event.target.value }))}
          />
        </div>
        <div className="field" style={{ margin: 0 }}>
          <label htmlFor={`t-${row.person.id}-currency`}>{t("العملة", "Currency")}</label>
          <select className="input" id={`t-${row.person.id}-currency`} value={currency} onChange={(event) => setCurrency(event.target.value)}>
            {currencies.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
        </div>
        <button className="btn btn--primary" type="submit" disabled={save.isPending}>
          <Icon name="check" />
          {t("احفظ التارجت", "Save the target")}
        </button>
        <button className="btn btn--ghost" type="button" onClick={onDone} disabled={save.isPending}>
          {t("لأ", "Cancel")}
        </button>
      </div>
      {problem && (
        <div className="note note--danger" role="alert" style={{ marginTop: 8 }}>
          <Icon name="alert" />
          <div>{problem}</div>
        </div>
      )}
    </form>
  );
}

/**
 * The month's Sales targets (the requirements' section 12): how far each person is, and - for the Sales manager and the
 * owner - the figures to set. The alerts (a target reached, under half from the 20th) are the server's.
 */
export function TargetsCard() {
  const { t } = usePreferences();
  const [month, setMonth] = useState("");
  const targets = useTargets(month);
  const [editing, setEditing] = useState<number | null>(null);
  const data = targets.data;
  if (!data) return null;
  const shownMonth = data.month;

  return (
    <div className="card" style={{ marginBottom: 14 }} id="targets">
      <div className="card__head">
        <Icon name="target" />
        <h3>{data.can_edit ? t("تارجت الفريق", "The team's targets") : t("التارجت بتاعك", "Your target")}</h3>
        <div className="grow" />
        <label className="row row--tight">
          <span className="muted">{t("الشهر", "Month")}</span>
          <input className="input" type="month" value={shownMonth} aria-label={t("الشهر", "Month")} onChange={(event) => setMonth(event.target.value)} />
        </label>
      </div>
      {data.rows.length === 0 ? (
        <p className="muted">{t("مفيش Sales.", "No Sales people.")}</p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>{t("الـSales", "Sales person")}</th>
                {data.metrics.map((metric) => (
                  <th key={metric}>{t(...METRIC[metric])}</th>
                ))}
                {data.can_edit && <th />}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) =>
                editing === row.person.id ? (
                  <tr key={row.person.id}>
                    <td>{row.person.name}</td>
                    <td colSpan={data.metrics.length + 1}>
                      <TargetForm row={row} month={shownMonth} currencies={data.currencies} onDone={() => setEditing(null)} />
                    </td>
                  </tr>
                ) : (
                  <tr key={row.person.id} data-target={row.person.id}>
                    <td>{row.person.name}</td>
                    {data.metrics.map((metric) => (
                      <td key={metric} data-metric={metric}>
                        <Progress figure={row.progress[metric]} />
                        {metric === "revenue" && row.progress.revenue.target !== null && <small className="muted"> {row.currency}</small>}
                      </td>
                    ))}
                    {data.can_edit && (
                      <td>
                        <button className="btn btn--sm" type="button" onClick={() => setEditing(row.person.id)}>
                          {t("حدد التارجت", "Set the target")}
                        </button>
                      </td>
                    )}
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted" style={{ marginTop: 8 }}>
        {t(
          "أول ما حد يوصل لتارجت بيوصله تنبيه هو والمانجر. ومن يوم 20 في الشهر، اللي لسه تحت نص التارجت بيتبلّغ مرة واحدة.",
          "Whoever reaches a target is told, and so is the manager. From the 20th, anyone still under half a target is told once.",
        )}
      </p>
    </div>
  );
}
