import { useState } from "react";
import { ApiError } from "../../api/client";
import { useCreateGroup, usePeople } from "../../api/queries";
import type { Role } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { suggestGroupName } from "../../lib/roles";
import { Icon } from "../Icon";
import { Modal } from "../Modal";
import { PeoplePicker } from "./PeoplePicker";

/**
 * Open an internal work group: pick the people, and name it - or leave the name and it is called for the translator
 * and the team leader among them (`suggestGroupName`; the server works the same name out when the box is left
 * empty). Nothing in a work group reaches a client. Who may open one is the server's rule (`me.chats.can_create_group`
 * only decides whether the button is drawn).
 */
export function NewGroupDialog({
  me,
  onClose,
  onCreated,
}: {
  me: { name: string; role: Role };
  onClose: () => void;
  /** The code of the group that was opened (`g12`), to open it. */
  onCreated: (code: string) => void;
}) {
  const { t } = usePreferences();
  const people = usePeople(true);
  const create = useCreateGroup();
  const [picked, setPicked] = useState<number[]>([]);
  const [typed, setTyped] = useState("");
  const [problem, setProblem] = useState("");

  // The suggestion follows what is picked until the person writes a name of their own: after that it stops
  // overwriting it, which is the whole difference between a default and a nuisance.
  const suggestion = suggestGroupName(
    me,
    (people.data?.people ?? []).filter((person) => picked.includes(person.id)),
  );
  const title = typed !== "" ? typed : suggestion;

  const save = () => {
    if (create.isPending) return;
    if (picked.length === 0) {
      setProblem(t("اختار عضو واحد على الأقل.", "Pick at least one person."));
      return;
    }
    setProblem("");
    create.mutate(
      { title: title.trim(), members: picked },
      {
        onSuccess: (answer) => onCreated(answer.code),
        onError: (error) => {
          if (error instanceof ApiError && error.detail) setProblem(error.detail);
          else if (error instanceof ApiError && error.status === 403) setProblem(t("مالكش صلاحية تعمل جروب شغل.", "You may not open a work group."));
          else setProblem(t("مقدرتش أعمل الجروب.", "Could not create the group."));
        },
      },
    );
  };

  return (
    <Modal title={t("جروب شغل جديد", "New work group")} icon="users" busy={create.isPending} onClose={onClose}>
      <p className="muted" style={{ fontSize: ".82rem" }}>
        {t("جروب داخلي: مفيش حاجة فيه بتوصل العميل.", "An internal group: nothing in it reaches a client.")}
      </p>

      {people.isPending && <div className="muted">{t("بحمّل...", "Loading...")}</div>}
      {people.isError && (
        <div className="muted" role="alert">
          {t("مش قادرين نجيب الأسامي.", "Could not load the people.")}
        </div>
      )}
      {people.data && (
        <PeoplePicker people={people.data.people} picked={picked} onChange={setPicked} label={t("الأعضاء", "Members")} />
      )}

      <div className="field" style={{ marginTop: 10 }}>
        <label htmlFor="new-group-title">{t("اسم الجروب", "Group name")}</label>
        <input
          id="new-group-title"
          className="input"
          maxLength={120}
          value={title}
          onChange={(event) => setTyped(event.target.value)}
          placeholder={t("لو سبته فاضي هيتسمى بالمترجم والليدر", "Left empty, it is named for the translator and the leader")}
        />
      </div>

      <div className="row" style={{ marginTop: 14, alignItems: "center" }}>
        <div role="alert" style={{ color: "var(--danger, #e5484d)", fontSize: ".8rem" }}>
          {problem}
        </div>
        <div className="grow" />
        <button type="button" className="btn" onClick={onClose} disabled={create.isPending}>
          {t("إلغاء", "Cancel")}
        </button>
        <button type="button" className="btn btn--primary" onClick={save} disabled={create.isPending || picked.length === 0}>
          <Icon name="plus" size="sm" />
          <span>{create.isPending ? t("بيتعمل...", "Creating...") : t("اعمل الجروب", "Create")}</span>
        </button>
      </div>
    </Modal>
  );
}
