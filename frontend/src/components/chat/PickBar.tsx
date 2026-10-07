import { usePreferences } from "../../i18n/Preferences";
import { newTaskUrl } from "../../lib/taskLink";
import { Icon } from "../Icon";

function isoDay(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

/** "Today", "Yesterday", or day/month/year, for a day written as the server writes it (`2026-10-01`). */
export function dayLabel(day: string, t: (ar: string, en: string) => string, now = new Date()): string {
  if (day === isoDay(now)) return t("النهارده", "Today");
  if (day === isoDay(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1))) return t("امبارح", "Yesterday");
  const bits = day.split("-");
  return bits.length === 3 ? `${bits[2]}/${bits[1]}/${bits[0]}` : day;
}

/**
 * The bar that replaces the box to write in while files are being picked: how many, which day, "select all", and
 * where they go - into another conversation, or into one task (a link to the task form, with the messages they are
 * in, the files that were ticked, and the messages ticked to be its details).
 */
export function PickBar({
  count,
  days,
  day,
  allIn,
  messages,
  files,
  texts,
  onDay,
  onAll,
  onCancel,
  onForward,
}: {
  count: number;
  days: { date: string; count: number }[];
  day: string;
  allIn: boolean;
  messages: number[];
  files: number[];
  /** The messages ticked to be written in the task's details. */
  texts: number[];
  onDay: (day: string) => void;
  onAll: () => void;
  onCancel: () => void;
  onForward: () => void;
}) {
  const { t } = usePreferences();
  return (
    <div className="cchat__pickbar" role="toolbar" aria-label={t("تحديد ملفات", "Select files")}>
      <Icon name="paperclip" size="sm" />
      <span aria-live="polite">
        <b className="mono">{count}</b> {t("ملف متحدد", "selected")}
        {texts.length > 0 && (
          <>
            {" + "}
            <b className="mono">{texts.length}</b> {t("رسالة للتفاصيل", "for the details")}
          </>
        )}
      </span>
      <select className="input cchat__pickday" value={day} onChange={(event) => onDay(event.target.value)} aria-label={t("ملفات يوم معيّن", "Files from one day")}>
        <option value="">{t("كل الأيام", "All days")}</option>
        {days.map((one) => (
          <option key={one.date} value={one.date}>
            {dayLabel(one.date, t)} ({one.count})
          </option>
        ))}
      </select>
      <button type="button" className="btn btn--sm btn--ghost" onClick={onAll}>
        {allIn ? t("شيل الكل", "Clear all") : t("تحديد الكل", "Select all")}
      </button>
      <span className="grow" />
      <button type="button" className="btn btn--sm" onClick={onCancel}>
        {t("إلغاء", "Cancel")}
      </button>
      <button type="button" className="btn btn--sm" disabled={count === 0} onClick={onForward}>
        <Icon name="forward" size="sm" />
        <span>{t("تحويل لشات", "Forward")}</span>
      </button>
      {count === 0 && texts.length === 0 ? (
        <button type="button" className="btn btn--sm btn--primary" disabled>
          <Icon name="arrow-right" size="sm" />
          <span>{t("تحويل لتاسك", "Convert to task")}</span>
        </button>
      ) : (
        <a className="btn btn--sm btn--primary" href={newTaskUrl(messages, files, texts)}>
          <Icon name="arrow-right" size="sm" />
          <span>{t("تحويل لتاسك", "Convert to task")}</span>
        </a>
      )}
    </div>
  );
}
