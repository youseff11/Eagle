import type { PartJson } from "../api/types";
import { usePreferences } from "../i18n/Preferences";
import { Icon } from "./Icon";

/** A page range as people read it: `3-9`, or the one page. */
export function pagesOf(part: Pick<PartJson, "page_from" | "page_to">) {
  if (part.page_from === null) return "";
  return part.page_to === null || part.page_to === part.page_from ? String(part.page_from) : `${part.page_from}-${part.page_to}`;
}

/**
 * What this translator was given of the task (07/10/2026): the language pair (the operation's, 08/10/2026), which pages when the task is
 * shared between several translators (the leader's), and how many words once the leader has written them at the review. It is theirs to
 * read and nothing for them to type: the words are what the month's production is counted from, and they are the leader's number.
 * Nothing is drawn for a task that was given whole with nothing said.
 */
export function PartBox({ part, handedIn = false }: { part: PartJson | null; handedIn?: boolean }) {
  const { t } = usePreferences();
  if (!part) return null;
  const pages = pagesOf(part);
  return (
    <div className="card card--flat" data-box="my-part" style={{ textAlign: "start", padding: "10px 14px", marginTop: 10 }}>
      <div className="row row--tight">
        <Icon name="target" size="sm" />
        <strong>{t("المطلوب منك", "Your part")}</strong>
        {handedIn && <span className="badge badge--ok">{t("سلّمت جزءك", "Handed in")}</span>}
      </div>
      <div className="kv">
        <span>{t("الترجمة", "Translation")}</span>
        <strong className="mono" dir="ltr">
          {part.source_lang || "—"} → {part.target_lang || "—"}
        </strong>
      </div>
      {part.words > 0 && (
        <div className="kv">
          <span>{t("عدد الكلمات", "Words")}</span>
          <strong className="mono">{part.words.toLocaleString("en")}</strong>
        </div>
      )}
      {pages && (
        <div className="kv">
          <span>{t("الصفحات", "Pages")}</span>
          <strong className="mono">{pages}</strong>
        </div>
      )}
    </div>
  );
}
