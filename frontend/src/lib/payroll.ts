/** 126 -> `2:06` (`minutes_hm` on the classic pages). */
export function minutesHm(value: number): string {
  const total = Number.isFinite(value) ? Math.trunc(value) : 0;
  const sign = total < 0 ? "-" : "";
  const abs = Math.abs(total);
  return `${sign}${Math.floor(abs / 60)}:${String(abs % 60).padStart(2, "0")}`;
}

/** `{ year: 2026, month: 9 }` -> `2026-9`: the month as the address and the doors carry it. */
export const periodText = (year: number, month: number) => `${year}-${month}`;

/** The month as a person reads it: `2026-09`. */
export const periodLabel = (year: number, month: number) => `${year}-${String(month).padStart(2, "0")}`;

/** Money is text (`"1500.00"`); is there any in it? `"0.00"` is none. A negative amount is some: it must be seen, not hidden. */
export const hasMoney = (value: string) => Number.isFinite(Number(value)) && Number(value) !== 0;
