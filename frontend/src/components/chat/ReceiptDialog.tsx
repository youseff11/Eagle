import { useState } from "react";
import { ApiError } from "../../api/client";
import { useConfirmReceipt } from "../../api/queries";
import type { ThreadEntry } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { Icon } from "../Icon";
import { Modal } from "../Modal";

/**
 * «استلمت»: the one button under a client's message that sends something. It asks first - the client gets a reply
 * saying their message arrived - and then says what happened. Who may, and which messages (the line this person
 * works, nothing the rate rule hides), is the server's; its reason is shown when it refuses. When nothing came
 * back the receipt may be out already, so it says so instead of offering to send it again.
 */
export function ReceiptDialog({ entry, code, onClose }: { entry: ThreadEntry; code: string; onClose: () => void }) {
  const { t } = usePreferences();
  const confirm = useConfirmReceipt(code);
  const [problem, setProblem] = useState("");

  const send = () => {
    if (confirm.isPending) return;
    setProblem("");
    confirm.mutate(entry.id, {
      onSuccess: onClose,
      onError: (error) => {
        if (error instanceof ApiError && error.detail) setProblem(error.detail);
        else if (error instanceof ApiError && error.status < 500) setProblem(t("مش ممكن.", "Not possible."));
        else setProblem(t("مش متأكدين إن الرد وصل. بص على المحادثة قبل ما تبعت تاني.", "We are not sure the receipt went out. Look at the conversation before sending it again."));
      },
    });
  };

  return (
    <Modal title={t("استلمت", "Received")} icon="check" busy={confirm.isPending} onClose={onClose}>
      <p>{t("هيتبعت للعميل رد فيه كلمة confirmed. تمام؟", "The client will receive a reply saying “confirmed”. Go ahead?")}</p>
      <div className="row" style={{ marginTop: 14, alignItems: "center" }}>
        <div role="alert" style={{ color: "var(--danger, #e5484d)", fontSize: ".8rem" }}>
          {problem}
        </div>
        <div className="grow" />
        <button type="button" className="btn" onClick={onClose} disabled={confirm.isPending}>
          {t("إلغاء", "Cancel")}
        </button>
        <button type="button" className="btn btn--primary" onClick={send} disabled={confirm.isPending}>
          <Icon name="check" size="sm" />
          <span>{confirm.isPending ? t("بيتبعت...", "Sending...") : t("تمام", "Yes")}</span>
        </button>
      </div>
    </Modal>
  );
}
