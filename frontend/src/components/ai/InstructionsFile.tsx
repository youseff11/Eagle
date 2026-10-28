import { useRef } from "react";
import { usePreferences } from "../../i18n/Preferences";
import { prettySize } from "../../lib/size";
import { Icon } from "../Icon";

/** Kinds the server can read the words of (`ai.text_from_bytes`), and the most it takes (`ai.INSTRUCTIONS_FILE_BYTES`). */
const ACCEPT = ".docx,.txt,.md,.csv,.json,.srt,.html,.htm";
export const INSTRUCTIONS_FILE_MAX = 2 * 1024 * 1024;

/** The other way to say what is wanted of the AI: a Word or text file with the instructions, beside the box to type them in. */
export function InstructionsFile({
  file,
  onChange,
  disabled,
  onTooBig,
}: {
  file: File | null;
  onChange: (next: File | null) => void;
  disabled?: boolean;
  onTooBig?: () => void;
}) {
  const { t } = usePreferences();
  const input = useRef<HTMLInputElement>(null);
  return (
    <div className="row row--tight mt" data-box="instructions-file">
      <input
        ref={input}
        type="file"
        hidden
        accept={ACCEPT}
        aria-label={t("ملف التعليمات", "Instructions file")}
        data-input="instructions-file"
        disabled={disabled}
        onChange={(event) => {
          const picked = event.target.files?.[0] ?? null;
          // The same file may be chosen again after it was taken off.
          event.target.value = "";
          if (!picked) return;
          if (picked.size > INSTRUCTIONS_FILE_MAX) {
            onTooBig?.();
            return;
          }
          onChange(picked);
        }}
      />
      <button className="btn btn--sm" type="button" disabled={disabled} onClick={() => input.current?.click()}>
        <Icon name="paperclip" size="sm" />
        <span>{file ? t("غيّر ملف التعليمات", "Change instructions file") : t("أو ارفع ملف تعليمات", "Or upload an instructions file")}</span>
      </button>
      {file ? (
        <>
          <Icon name="file" size="sm" />
          <span dir="auto">{file.name}</span>
          <small className="muted mono">{prettySize(file.size)}</small>
          <button className="btn btn--sm btn--ghost" type="button" disabled={disabled} aria-label={t("شيل ملف التعليمات", "Remove instructions file")} onClick={() => onChange(null)}>
            <Icon name="x" size="sm" />
          </button>
        </>
      ) : (
        <small className="muted">{t("Word أو نص، لحد 2 ميجا. بيتقري ويتضاف تحت اللي كتبته.", "Word or text, up to 2 MB. It is read and added under what you typed.")}</small>
      )}
    </div>
  );
}
