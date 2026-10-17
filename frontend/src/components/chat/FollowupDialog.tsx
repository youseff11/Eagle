import { useState } from "react";
import { ApiError } from "../../api/client";
import { useSendFollowup } from "../../api/queries";
import type { FollowupOffer } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { Modal } from "../Modal";
import { Icon } from "../Icon";

/** Why the server sent nothing, in words (`followup.send`'s codes). */
function refusal(code: string, t: (ar: string, en: string) => string): string {
  switch (code) {
    case "window_open":
      return t("النافذة اتفتحت: اكتب للعميل عادي.", "The window is open again: write to the client as usual.");
    case "sent_recently":
      return t("رسالة المتابعة اتبعتت في آخر 24 ساعة ولسه العميل مارّدش.", "The follow-up went in the last 24 hours and the client has not answered yet.");
    case "no_line":
      return t("مفيش رقم واتساب متحدد لصاحب المحادثة دي.", "Nobody's WhatsApp number is set for this conversation.");
    case "no_number":
      return t("العميل ده مفيش عنده رقم واتساب.", "This client has no WhatsApp number.");
    case "blocked":
      return t("العميل ده محظور.", "This client is blocked.");
    default:
      return t("الرسالة ماتبعتتش. جرّب تاني.", "The message was not sent. Try again.");
  }
}

/**
 * «رسالة متابعة»: the approved template that reopens a client chat after the 24-hour window closed. The words are
 * Meta's, fixed; only the language is picked here, Arabic or English, the one the client's number suggests first.
 */
export function FollowupDialog({ code, offer, onClose }: { code: string; offer: FollowupOffer; onClose: () => void }) {
  const { t } = usePreferences();
  const [language, setLanguage] = useState<"ar" | "en">(offer.language);
  const [problem, setProblem] = useState("");
  const send = useSendFollowup(code);

  const submit = () => {
    setProblem("");
    send.mutate(language, {
      onSuccess: (answer) => {
        if (answer.delivered) onClose();
        else setProblem(answer.error || t("واتساب رفض الرسالة.", "WhatsApp refused the message."));
      },
      onError: (error) => setProblem(refusal(error instanceof ApiError ? error.code : "", t)),
    });
  };

  return (
    <Modal title={t("رسالة متابعة", "Follow-up message")} icon="message" busy={send.isPending} onClose={onClose}>
      <p className="muted" style={{ margin: "8px 0" }}>
        {t(
          "رسالة متوافق عليها من واتساب، بتوصل للعميل حتى بعد ما النافذة تقفل، وبتبدأ عنده باسم شركته (أو «حضرتك» لو مالوش شركة). أول ما يرد تقدر تكتب له عادي.",
          "A message approved by WhatsApp that reaches the client even after the window closed; on their phone it opens with their company name (or a polite greeting when there is none). Once they answer you can write as usual.",
        )}
      </p>
      <div className="row row--tight" role="group" aria-label={t("لغة الرسالة", "Message language")}>
        {(["ar", "en"] as const).map((one) => (
          <button
            key={one}
            type="button"
            className={language === one ? "btn btn--sm btn--primary" : "btn btn--sm"}
            aria-pressed={language === one}
            onClick={() => setLanguage(one)}
            disabled={send.isPending}
          >
            {one === "ar" ? "عربي" : "English"}
          </button>
        ))}
      </div>
      <div className="note" dir={language === "ar" ? "rtl" : "ltr"} style={{ margin: "8px 0" }} data-testid="followupText">
        {offer.texts[language]}
      </div>
      {offer.sent_recently && (
        <div className="note note--warn">
          <Icon name="clock" />
          <div>{t("رسالة المتابعة اتبعتت في آخر 24 ساعة ولسه العميل مارّدش.", "The follow-up went in the last 24 hours and the client has not answered yet.")}</div>
        </div>
      )}
      {problem && (
        <div className="note note--high" role="alert">
          <Icon name="alert" />
          <div>{problem}</div>
        </div>
      )}
      <div className="row" style={{ marginTop: 14 }}>
        <div className="grow" />
        <button type="button" className="btn" onClick={onClose} disabled={send.isPending}>
          {t("إلغاء", "Cancel")}
        </button>
        <button type="button" className="btn btn--primary" onClick={submit} disabled={send.isPending || offer.sent_recently}>
          <span>{t("ابعت", "Send")}</span>
        </button>
      </div>
    </Modal>
  );
}
