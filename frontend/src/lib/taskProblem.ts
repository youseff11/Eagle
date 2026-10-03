import { ApiError } from "../api/client";

/**
 * Why an action on a task did not happen, in the person's words.
 *
 * The old endpoints answer a refusal in one of two ways: a sentence of their own in `error` (Arabic, written for the
 * person: "upload the file first"), or a short code (`forbidden`, `bad_status`, `empty`). A sentence is shown as it
 * is; a code is turned into one. A reply that never came, or a server that failed, is not a refusal: the action may
 * have happened, so the page says it is not sure and asks again from the server.
 */
export function taskProblem(error: unknown, t: (ar: string, en: string) => string): string {
  if (error instanceof ApiError) {
    const sentence = /[^\x00-\x7f]/.test(error.code) ? error.code : error.detail;
    if (sentence) return sentence;
    switch (error.code) {
      case "forbidden":
        return t("مش من حقك تعمل ده.", "You may not do that.");
      case "bad_status":
        return t("حالة التاسك دلوقتي مش بتسمح بده.", "The task is not in a state that allows it.");
      case "empty":
        return t("اختار ملف الأول.", "Choose a file first.");
      case "no_room":
        return t("مفيش جروب مع التيم ليدر تتبعت فيه. كلّم الأوبريشن.", "There is no group with your team leader to send it to. Tell the operation.");
      case "bad_words":
        return t("اكتب رقم صحيح.", "Type a whole number.");
      case "bad_requirement":
        return t("اكتب المتطلب.", "Write the requirement.");
      case "bad_date":
        return t("الديدلاين مش مظبوط.", "That deadline is not right.");
      case "disabled":
        return t("مراجعة الـAI متوقفة من الأدمن.", "The AI check has been turned off by the admin.");
      case "csrf":
        return t("الجلسة محتاجة تتحدّث. حدّث الصفحة وجرّب تاني.", "The session needs a refresh. Reload the page and try again.");
      case "refused":
        return t("مقدرتش أعمل ده.", "That could not be done.");
      default:
        if (error.status >= 400 && error.status < 500) return t("مقدرتش أعمل ده.", "That could not be done.");
    }
  }
  return t(
    "مش متأكدين إن ده تم. حدّث الصفحة وبص على الحالة قبل ما تجرّب تاني.",
    "We are not sure that went through. Reload the page and look at the state before trying again.",
  );
}
