import { usePreferences } from "../../i18n/Preferences";
import { Icon } from "../Icon";

/**
 * The marks under a message of ours: one grey check (it left), two grey (it reached the phone), two
 * blue (it was read - by the client, or by everyone else in the room), a warning (it failed).
 *
 * The same rule as `templates/ops/_ticks.html` and `ticksHtml` in chat.js.
 */
export function Ticks({
  status,
  receipt,
  mine,
  seenBy = [],
}: {
  status: string;
  receipt: string;
  mine: boolean;
  seenBy?: string[];
}) {
  const { t, lang } = usePreferences();
  const who = seenBy.join(lang === "ar" ? "، " : ", ");
  const seen = who ? `${t("شافها: ", "Seen by: ")}${who}` : "";

  if (status === "failed") return <Icon name="alert" size="sm" />;
  if (receipt === "read") {
    return (
      <span className="tick tick--read" title={seen || t("اتقرت", "Read")}>
        <Icon name="check-double" size="sm" />
      </span>
    );
  }
  if (receipt === "delivered") {
    return (
      <span className="tick" title={t("وصلت", "Delivered")}>
        <Icon name="check-double" size="sm" />
      </span>
    );
  }
  if (status === "sent" || mine) {
    return (
      <span className="tick" title={seen || t("اتبعتت", "Sent")}>
        <Icon name="check" size="sm" />
      </span>
    );
  }
  return null;
}
