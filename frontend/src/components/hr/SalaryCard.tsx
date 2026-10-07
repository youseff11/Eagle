import { useState, type FormEvent } from "react";
import { useSaveSalary } from "../../api/accountsActions";
import { formErrors } from "../../api/adminActions";
import type { FormErrors } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { Icon } from "../Icon";
import { useToasts } from "../Toasts";

/**
 * The owner types a person's salary here, from the file: an amount and the day it starts. It goes through the same door as the
 * accounts page (append-only, a month already run keeps what it was paid), so the two never disagree.
 */
export function SalaryCard({ id, onSaved }: { id: number; onSaved: () => void }) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const save = useSaveSalary(id);
  const [amount, setAmount] = useState("");
  const [from, setFrom] = useState(() => new Date().toLocaleDateString("en-CA"));
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<FormErrors>({});
  const [failed, setFailed] = useState(false);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    setFailed(false);
    save.mutate(
      { amount, effective_from: from, note },
      {
        onSuccess: () => {
          setAmount("");
          setNote("");
          push({ level: "success", title: t("اتسجل", "Recorded") });
          onSaved();
        },
        onError: (error) => {
          const found = formErrors(error);
          if (found) setErrors(found);
          else setFailed(true);
        },
      },
    );
  };
  const problems = (name: string) =>
    errors[name]?.length ? (
      <ul className="errorlist" role="alert">
        {errors[name]!.map((message, index) => (
          <li key={index}>{message}</li>
        ))}
      </ul>
    ) : null;

  return (
    <div className="card card--flat" data-card="set-salary">
      <div className="card__head">
        <Icon name="tag" />
        <h3>{t("حدد الراتب", "Set the salary")}</h3>
      </div>
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor="set-salary-amount">{t("الراتب", "Salary")}</label>
          <input id="set-salary-amount" className="input mono" dir="ltr" inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} required />
          {problems("amount")}
        </div>
        <div className="field">
          <label htmlFor="set-salary-from">{t("ساري من", "Effective from")}</label>
          <input id="set-salary-from" className="input" type="date" value={from} onChange={(event) => setFrom(event.target.value)} required />
          {problems("effective_from")}
        </div>
        <div className="field">
          <label htmlFor="set-salary-note">{t("ملاحظة", "Note")}</label>
          <input id="set-salary-note" className="input" value={note} onChange={(event) => setNote(event.target.value)} />
        </div>
        {failed && (
          <div className="note note--high" role="alert">
            <Icon name="alert" />
            <div>{t("حصلت مشكلة، ماتسجلش.", "Something went wrong, nothing was recorded.")}</div>
          </div>
        )}
        <button className="btn btn--sm btn--block mt" type="submit" disabled={save.isPending || !amount}>
          <Icon name="check" size="sm" />
          <span>{t("سجّل", "Record")}</span>
        </button>
      </form>
    </div>
  );
}
