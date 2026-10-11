import { useChatLines, usePickChatLine } from "../../api/queries";
import type { ChatLineChoice } from "../../api/types";
import { useToasts } from "../Toasts";
import { usePreferences } from "../../i18n/Preferences";

/**
 * The admin's switch above the client list: every line, the company's number, or one person's (`lines.view_q`). It only
 * narrows the list - a chat opened by its address stays whole - and it is kept on the account, so it is still there tomorrow.
 */
export function LinePicker() {
  const { t } = usePreferences();
  const { push } = useToasts();
  const query = useChatLines();
  const pick = usePickChatLine();
  const data = query.data;
  // Nothing to choose until somebody holds a number of their own ("every number" and "the company's" are always there).
  if (!Array.isArray(data?.lines) || data.lines.length <= 2) return null;

  const label = (line: ChatLineChoice) => {
    if (line.kind === "all") return t("كل الأرقام", "Every number");
    if (line.kind === "company") return t("رقم الشركة", "The company number");
    const name = `${line.name ?? ""}${line.number ? ` · ${line.number}` : ""}`;
    return line.active === false ? `${name} (${t("مش شغال", "inactive")})` : name;
  };

  return (
    <div className="cchat__line" style={{ padding: "8px 12px 0" }}>
      <select
        className="input"
        aria-label={t("شاتات رقم", "Chats of the number")}
        value={pick.isPending ? (pick.variables ?? data.current) : data.current}
        disabled={pick.isPending}
        onChange={(event) =>
          pick.mutate(event.target.value, {
            onError: () => push({ level: "danger", title: t("مقدرتش أغيّر الرقم.", "Could not switch the number.") }),
          })
        }
      >
        {data.lines.map((line) => (
          <option key={line.key} value={line.key}>
            {label(line)}
          </option>
        ))}
      </select>
    </div>
  );
}
