import { useState, type FormEvent } from "react";
import { ApiError } from "../../api/client";
import { useSetIncentive } from "../../api/hrActions";
import { usePreferences } from "../../i18n/Preferences";
import { Icon } from "../Icon";
import { useToasts } from "../Toasts";

/**
 * «الحوافز»: a sum the owner types by hand for one person, added to their pay every month until he changes it. It is not a rule and
 * nothing earns it: the salary plan holds the rules, this is a figure written on the file. Zero takes it off. A month that was already
 * run keeps what it was paid; the next run reads the figure that is here.
 */
export function IncentiveCard({ id, current }: { id: number; current: string }) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const save = useSetIncentive(id);
  const [amount, setAmount] = useState<string | null>(null);
  const [problem, setProblem] = useState("");
  const shown = amount ?? current;
  const changed = amount !== null && amount.trim() !== "" && Number(amount) !== Number(current);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!changed || save.isPending) return;
    setProblem("");
    save.mutate(amount!.trim(), {
      onSuccess: () => {
        setAmount(null);
        push({ level: "success", title: t("اتسجل", "Recorded") });
      },
      onError: (error) =>
        setProblem(
          error instanceof ApiError && error.code === "bad_amount"
            ? t("اكتب رقم من غير سالب، وبحد أقصى رقمين بعد العلامة العشرية.", "Type a number with no minus sign and at most two decimals.")
            : t("حصلت مشكلة، ماتسجلش.", "Something went wrong, nothing was recorded."),
        ),
    });
  };

  return (
    <div className="card card--flat" data-card="incentive">
      <div className="card__head">
        <Icon name="star" />
        <h3>{t("الحوافز (زيادة مرتب)", "Incentive (pay raise)")}</h3>
      </div>
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor="incentive-amount">{t("المبلغ الشهري", "Monthly amount")}</label>
          <input
            id="incentive-amount"
            className="input mono"
            dir="ltr"
            inputMode="decimal"
            value={shown}
            onChange={(event) => setAmount(event.target.value)}
          />
          <small className="muted">
            {t(
              "بتتضاف على مرتبه كل شهر لحد ما تغيّرها. بالإيد، مفيش قاعدة بتحسبها. صفر بيشيلها.",
              "Added to their pay every month until you change it. By hand: no rule works it out. Zero takes it off.",
            )}
          </small>
        </div>
        {problem && (
          <div className="note note--high" role="alert">
            <Icon name="alert" />
            <div>{problem}</div>
          </div>
        )}
        <button className="btn btn--sm btn--block mt" type="submit" disabled={save.isPending || !changed}>
          <Icon name="check" size="sm" />
          <span>{t("سجّل", "Record")}</span>
        </button>
      </form>
    </div>
  );
}
