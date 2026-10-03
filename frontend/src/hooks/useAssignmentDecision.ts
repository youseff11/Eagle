import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router";
import { api } from "../api/client";
import { qk } from "../api/keys";
import type { Role } from "../api/types";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";
import { navigation } from "../lib/navigation";
import { safeInternalPath } from "../lib/safeUrl";
import { taskProblem } from "../lib/taskProblem";

/** What a hand-off is, for the two things that can be done with it. */
export interface Handoff {
  id: number;
  role: Role;
  taskCode: string;
  /** The classic task page, where a person whose screen is not in this app goes after accepting. */
  taskUrl: string;
}

/**
 * Answering a hand-off, the way the classic accept screen does - the same two endpoints, the same words.
 *
 *  - accept: `ok` moves the task and goes to it (a translator's own page is a route of this app; anybody else's
 *    is the classic address). `ok: false` is "too late": the window ran out, or somebody else answered. The
 *    exception is `reason: "accepted"` - this person has already accepted it (a second tab, a double press),
 *    which is what they wanted, not a failure.
 *  - decline: a reason is required, here before anything is sent as well as on the server.
 *
 * A reply that never came is not a refusal: the answer may have gone through, so the hand-off stays on screen
 * and the next beat tells the truth. `onAnswered` is called when the hand-off is no longer waiting, whichever way.
 */
export function useAssignmentDecision(handoff: Handoff, onAnswered: () => void) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);

  const settled = () => {
    // Nothing is waiting any more: the popup goes at once, the page and the desk read the new state.
    client.setQueryData(qk.pending, null);
    void client.invalidateQueries({ queryKey: qk.assignment(handoff.id) });
    void client.invalidateQueries({ queryKey: qk.translatorHome });
    onAnswered();
  };

  const accept = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const answer = await api<{ ok: boolean; reason?: string }>(`/api/assignments/${handoff.id}/accept/`, { form: {} });
      if (answer.ok || answer.reason === "accepted") {
        push({ level: "success", title: t("تم الاستلام", "Accepted") });
        settled();
        if (handoff.role === "translator") navigate(`/tasks/${encodeURIComponent(handoff.taskCode)}`);
        else navigation.assign(safeInternalPath(handoff.taskUrl) ?? "/");
        return;
      }
      push({ level: "danger", title: t("الوقت خلص", "Too late"), body: t("التاسك رجعت لمين بعتها.", "The task went back to the sender.") });
      settled();
    } catch (error) {
      push({ level: "warning", title: t("مش متأكدين إن الاستلام تم", "We are not sure it went through"), body: taskProblem(error, t) });
    } finally {
      setBusy(false);
    }
  };

  /** Returns `false` when the reason is missing (nothing was sent). */
  const decline = async (reason: string): Promise<boolean> => {
    const why = reason.trim();
    if (!why) {
      push({
        level: "warning",
        title: t("اكتب سبب الرفض", "Say why"),
        body: t("اللي بعتلك محتاج يعرف يعمل إيه بعد كده.", "The sender needs to know what to do next."),
      });
      return false;
    }
    if (busy) return true;
    setBusy(true);
    try {
      await api<{ ok: boolean }>(`/api/assignments/${handoff.id}/decline/`, { form: { reason: why } });
      push({ level: "success", title: t("اتبعت الرفض", "Declined") });
      settled();
    } catch (error) {
      push({ level: "danger", title: t("مقدرتش أرفض", "Could not decline"), body: taskProblem(error, t) });
    } finally {
      setBusy(false);
    }
    return true;
  };

  return { busy, accept, decline };
}
