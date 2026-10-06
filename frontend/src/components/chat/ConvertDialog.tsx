import { useState } from "react";
import type { ThreadEntry } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { newTaskUrl } from "../../lib/taskLink";
import { Icon } from "../Icon";
import { Modal } from "../Modal";

/**
 * "Turn this into a task": which of the client's files are the job, then on to the task form. `entries` is the message
 * that was pressed, or all of the files that arrived together with it (`newFilesRun`): they are all ticked, so one press
 * takes the lot. Only the ticked files reach the translator; the form checks every id against the messages again. The way
 * on is a link to the classic form's address, made from what is ticked.
 */
export function ConvertDialog({ entries, onClose }: { entries: ThreadEntry[]; onClose: () => void }) {
  const { t } = usePreferences();
  // A voice note is not a document to translate.
  const files = entries.flatMap((entry) => entry.files.filter((file) => file.id > 0 && !file.audio).map((file) => ({ file, message: entry.id })));
  const [ticked, setTicked] = useState<number[]>(files.map(({ file }) => file.id));
  const toggle = (id: number) => setTicked((now) => (now.includes(id) ? now.filter((one) => one !== id) : [...now, id]));
  // Only the messages that still have a file ticked go to the form; with none ticked it is every file of the messages, as before.
  const messages = ticked.length === 0 ? entries.map((entry) => entry.id) : [...new Set(files.filter(({ file }) => ticked.includes(file.id)).map(({ message }) => message))];
  const several = entries.length > 1;

  return (
    <Modal title={t("تحويل لتاسك", "Convert to task")} icon="arrow-right" onClose={onClose}>
      {files.length > 0 ? (
        <>
          {several && (
            <p style={{ fontSize: ".86rem" }}>
              {t(
                `العميل بعت ${files.length} ملفات ورا بعض في ${entries.length} رسايل: كلهم هيتحوّلوا لتاسك واحدة.`,
                `The client sent ${files.length} files one after the other in ${entries.length} messages: all of them become one task.`,
              )}
            </p>
          )}
          <p className="muted" style={{ fontSize: ".82rem" }}>
            {t(
              "شيل العلامة عن أي ملف مش جزء من الشغلانة — اللي متعلّم عليه بس هو اللي هيوصل المترجم.",
              "Untick anything that is not part of the job — only the ticked files reach the translator.",
            )}
          </p>
          <div className="pick" role="group" aria-label={t("الملفات", "Files")}>
            {files.map(({ file }) => (
              <label className="pick__item" key={file.id}>
                <input type="checkbox" checked={ticked.includes(file.id)} onChange={() => toggle(file.id)} />
                <Icon name="paperclip" size="sm" />
                <span>{file.name}</span>
              </label>
            ))}
          </div>
        </>
      ) : (
        <div className="muted" style={{ fontSize: ".82rem" }}>
          {t("الرسالة دي مفيهاش ملفات — هتفتح التاسك بنصها.", "This message has no files — the task opens with its text.")}
        </div>
      )}
      <div className="row" style={{ marginTop: 14, alignItems: "center" }}>
        <div className="grow" />
        <button type="button" className="btn" onClick={onClose}>
          {t("إلغاء", "Cancel")}
        </button>
        <a className="btn btn--primary" href={newTaskUrl(messages, ticked)}>
          <Icon name="arrow-right" size="sm" />
          <span>{t("كمّل", "Continue")}</span>
        </a>
      </div>
    </Modal>
  );
}
