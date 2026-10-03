import { periodLabel, periodText } from "../../lib/payroll";
import { usePreferences } from "../../i18n/Preferences";

/**
 * The month to look at: this one and the twelve before it. It changes the address, so a month is a link that can be sent.
 * The picker's choice is the month's own name (`2026-9`), the same one the doors read.
 */
export function MonthPicker({
  periods,
  year,
  month,
  onChange,
}: {
  periods: { year: number; month: number }[];
  year: number;
  month: number;
  onChange: (period: string) => void;
}) {
  const { t } = usePreferences();
  return (
    <select
      className="input"
      aria-label={t("الشهر", "Month")}
      value={periodText(year, month)}
      onChange={(event) => onChange(event.target.value)}
    >
      {periods.map((choice) => (
        <option key={periodText(choice.year, choice.month)} value={periodText(choice.year, choice.month)}>
          {periodLabel(choice.year, choice.month)}
        </option>
      ))}
    </select>
  );
}
