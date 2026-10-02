/**
 * A length of time asked for ("1 day 2 hours"), the way the classic page writes it (`ExtensionRequest.pretty_length`),
 * in the page's language. The server sends minutes; the words are the page's.
 */
export function lengthOfTime(minutes: number, t: (ar: string, en: string) => string): string {
  const total = Math.max(0, Math.floor(minutes));
  const hours = Math.floor(total / 60);
  const days = Math.floor(hours / 24);
  const parts: string[] = [];
  if (days) parts.push(`${days} ${t("يوم", days === 1 ? "day" : "days")}`);
  if (hours % 24) parts.push(`${hours % 24} ${t("ساعة", "h")}`);
  if (total % 60) parts.push(`${total % 60} ${t("دقيقة", "min")}`);
  return parts.length ? parts.join(" ") : `0 ${t("دقيقة", "min")}`;
}
