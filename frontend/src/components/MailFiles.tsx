import type { MailFile } from "../api/types";
import { usePreferences } from "../i18n/Preferences";
import { safeInternalPath } from "../lib/safeUrl";
import { VoiceNote } from "./chat/VoiceNote";
import { Icon } from "./Icon";

/** The files of a letter or of our reply: a voice note plays, anything else opens from this site (`/files/...`). */
export function MailFiles({ files }: { files: MailFile[] }) {
  const { t } = usePreferences();
  if (files.length === 0) return null;
  return (
    <div className="files">
      {files.map((file) => {
        // The server wrote the address; it is followed only if it is a path on this site.
        const url = safeInternalPath(file.url);
        if (file.audio && url) return <VoiceNote key={file.id} url={url} length={file.length} />;
        const label = (
          <>
            <Icon name="paperclip" size="sm" />
            {file.name}
          </>
        );
        return url ? (
          <a key={file.id} className="file-pill" href={url} target="_blank" rel="noopener noreferrer" title={file.size}>
            {label}
          </a>
        ) : (
          <span key={file.id} className="file-pill" title={t("الملف مش متاح", "The file is not available")}>
            {label}
          </span>
        );
      })}
    </div>
  );
}
