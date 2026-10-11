import { useSearchParams } from "react-router";
import { usePreferences } from "../i18n/Preferences";

const pad = (value: number) => String(value).padStart(2, "0");
const iso = (day: Date) => `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** The quick periods: this month so far, last month, the last seven days. */
function periods(today: Date): { key: string; label: [string, string]; from: string; to: string }[] {
  const firstThis = new Date(today.getFullYear(), today.getMonth(), 1);
  const lastPrev = new Date(today.getFullYear(), today.getMonth(), 0);
  const firstPrev = new Date(lastPrev.getFullYear(), lastPrev.getMonth(), 1);
  const weekAgo = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 6);
  return [
    { key: "month", label: ["الشهر ده", "This month"], from: iso(firstThis), to: iso(today) },
    { key: "last", label: ["الشهر اللي فات", "Last month"], from: iso(firstPrev), to: iso(lastPrev) },
    { key: "week", label: ["آخر 7 أيام", "Last 7 days"], from: iso(weekAgo), to: iso(today) },
  ];
}

/**
 * The period a page of figures is for, kept in the address (`?from=&to=`) so a reload and a shared link keep it. Empty
 * means the server's default: this month so far.
 */
export function usePeriod(): [string, string] {
  const [params] = useSearchParams();
  const from = DAY.test(params.get("from") ?? "") ? (params.get("from") as string) : "";
  const to = DAY.test(params.get("to") ?? "") ? (params.get("to") as string) : "";
  return [from, to];
}

/** The period's controls: three quick periods and the two dates. `shown` is the period the server answered for. */
export function PeriodPicker({ shown }: { shown: { from: string; to: string } }) {
  const { t } = usePreferences();
  const [, setParams] = useSearchParams();
  const quick = periods(new Date());
  const set = (next: { from: string; to: string }) => setParams(next.from && next.to ? { from: next.from, to: next.to } : {});

  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div className="row">
        {quick.map((one) => (
          <button
            key={one.key}
            type="button"
            className={shown.from === one.from && shown.to === one.to ? "btn btn--sm btn--primary" : "btn btn--sm"}
            onClick={() => set(one.key === "month" ? { from: "", to: "" } : one)}
          >
            {t(one.label[0], one.label[1])}
          </button>
        ))}
        <div className="grow" />
        <label className="row row--tight">
          <span className="muted">{t("من", "From")}</span>
          <input className="input" type="date" value={shown.from} aria-label={t("من", "From")} onChange={(event) => set({ from: event.target.value, to: shown.to })} />
        </label>
        <label className="row row--tight">
          <span className="muted">{t("لحد", "To")}</span>
          <input className="input" type="date" value={shown.to} aria-label={t("لحد", "To")} onChange={(event) => set({ from: shown.from, to: event.target.value })} />
        </label>
      </div>
    </div>
  );
}
