/**
 * "باقي يومين و3 ساعات" until a deadline - or how late it already is - from the moment the server wrote
 * (an ISO time), worked out in the browser so it keeps moving between polls. The same words, and the same
 * rule for which parts are left out, as the classic accept screen (`deadlineLeft` in the old classic app.js, now deleted).
 */
export function deadlineLeft(
  iso: string,
  now: number,
  t: (ar: string, en: string) => string,
): { text: string; late: boolean } {
  if (!iso) return { text: "", late: false };
  const ms = new Date(iso).getTime() - now;
  if (Number.isNaN(ms)) return { text: "", late: false };
  const late = ms < 0;
  const minutes = Math.floor(Math.abs(ms) / 60000);
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const mins = minutes % 60;
  const ar: string[] = [];
  const en: string[] = [];
  if (days) {
    ar.push(`${days} يوم`);
    en.push(`${days} ${days === 1 ? "day" : "days"}`);
  }
  if (hours) {
    ar.push(`${hours} ساعة`);
    en.push(`${hours} ${hours === 1 ? "hour" : "hours"}`);
  }
  // Minutes only matter when no whole day is left (or when there is nothing else to say).
  if (!days && (mins || !hours)) {
    ar.push(`${mins} دقيقة`);
    en.push(`${mins} ${mins === 1 ? "minute" : "minutes"}`);
  }
  const span = t(ar.join(" و"), en.join(" "));
  return {
    late,
    text: late ? t(`الديدلاين فات من ${span}`, `Deadline passed ${span} ago`) : t(`باقي ${span} على الديدلاين`, `${span} left until the deadline`),
  };
}
