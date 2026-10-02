import { useState } from "react";
import { ApiError } from "../../api/client";
import { useAddMembers } from "../../api/queries";
import type { Person } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { Icon } from "../Icon";
import { Modal } from "../Modal";
import { PeoplePicker } from "./PeoplePicker";

/**
 * Add people to a group. The list is the server's (`members.addable`: nobody already in, and no translator for a room
 * that reaches a client); what it still refuses - somebody who may not see the task the room belongs to - comes back
 * in words and is shown. A partial result (some added, some left out) is a success that says who was left out.
 */
export function AddMembersDialog({
  room,
  code,
  addable,
  reachesClient,
  onClose,
  onDone,
}: {
  room: number;
  code: string;
  addable: Person[];
  /** Whoever is added here can write to the client: said so, as the classic page does. */
  reachesClient: boolean;
  onClose: () => void;
  /** Somebody was added; the reason some were not, if any. */
  onDone: (left: string) => void;
}) {
  const { t } = usePreferences();
  const add = useAddMembers(room, code);
  const [picked, setPicked] = useState<number[]>([]);
  const [problem, setProblem] = useState("");

  const save = () => {
    if (add.isPending) return;
    if (picked.length === 0) {
      setProblem(t("اختار حد الأول.", "Pick somebody first."));
      return;
    }
    setProblem("");
    add.mutate(picked, {
      onSuccess: (answer) => onDone(answer.message),
      onError: (error) => {
        if (error instanceof ApiError && error.detail) setProblem(error.detail);
        else if (error instanceof ApiError && error.status === 403) setProblem(t("مالكش صلاحية تضيف أعضاء.", "You may not add members."));
        else setProblem(t("مقدرتش أضيف.", "Could not add them."));
      },
    });
  };

  return (
    <Modal title={t("ضيف أعضاء للجروب", "Add members")} icon="user-check" busy={add.isPending} onClose={onClose}>
      {reachesClient && (
        <p className="muted" style={{ fontSize: ".82rem" }}>
          {t("اللي هتضيفه هيقدر يكتب للعميل على واتساب من الجروب ده.", "Anyone you add can write to the client on WhatsApp from this group.")}
        </p>
      )}
      <PeoplePicker people={addable} picked={picked} onChange={setPicked} label={t("الأعضاء الجداد", "New members")} />
      <div className="row" style={{ marginTop: 14, alignItems: "center" }}>
        <div role="alert" style={{ color: "var(--danger, #e5484d)", fontSize: ".8rem" }}>
          {problem}
        </div>
        <div className="grow" />
        <button type="button" className="btn" onClick={onClose} disabled={add.isPending}>
          {t("إلغاء", "Cancel")}
        </button>
        <button type="button" className="btn btn--primary" onClick={save} disabled={add.isPending || picked.length === 0}>
          <Icon name="plus" size="sm" />
          <span>{add.isPending ? t("بيتضاف...", "Adding...") : t("ضيف", "Add")}</span>
        </button>
      </div>
    </Modal>
  );
}
