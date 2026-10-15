import { useState } from "react";
import { refusalText, useDuplicates, useRemoveDuplicates, type B2bLead, type DuplicateGroup } from "../../api/b2b";
import { usePreferences } from "../../i18n/Preferences";
import { Icon } from "../Icon";
import { Loading } from "../Loading";
import { Modal } from "../Modal";
import { STATUS_AR } from "./SheetGrid";

const WHY: Record<DuplicateGroup["why"][number], [string, string]> = {
  phone: ["نفس الرقم", "Same number"],
  email: ["نفس الإيميل", "Same e-mail"],
  name: ["نفس اسم الشركة", "Same company name"],
};

/** What the person picked in one group: the row that stays, and the rows that go (every other one, unless unticked). */
interface Pick {
  keep: number;
  remove: number[];
}

const firstPick = (group: DuplicateGroup): Pick => ({ keep: group.keep, remove: group.ids.filter((id) => id !== group.keep) });

/**
 * «المكرر» on a sheet (15/10/2026): the companies that are on it more than once - the same number, e-mail or name - in
 * groups. In each group one row stays (the one with the most on it, unless the person picks another) and the ticked ones
 * go. Nothing they held is lost: their notes, history and quotations move to the row that stays, and an empty cell of it
 * takes what a copy had (`b2b.merge_duplicates`, which checks again that they are one company).
 */
export function Duplicates({ sheetId, leads, onClose }: { sheetId: number; leads: B2bLead[]; onClose: () => void }) {
  const { t, lang } = usePreferences();
  const found = useDuplicates(sheetId);
  const remove = useRemoveDuplicates(sheetId);
  const [picks, setPicks] = useState<Record<number, Pick>>({});
  const [problem, setProblem] = useState("");
  const [done, setDone] = useState(0);
  const byId = new Map(leads.map((lead) => [lead.id, lead]));
  const groups = (found.data?.groups ?? []).filter((group) => group.ids.every((id) => byId.has(id)));
  const pickOf = (group: DuplicateGroup) => picks[group.ids[0]] ?? firstPick(group);
  const setPick = (group: DuplicateGroup, pick: Pick) => setPicks((all) => ({ ...all, [group.ids[0]]: pick }));
  const fallback = t("مقدرتش أمسح. جرّب تاني.", "Could not delete. Try again.");

  // One group at a time, so a group that changed meanwhile stops there and the rest is left as it was.
  const run = async (chosen: DuplicateGroup[]) => {
    setProblem("");
    let removed = 0;
    for (const group of chosen) {
      const pick = pickOf(group);
      if (!pick.remove.length) continue;
      try {
        removed += (await remove.mutateAsync({ keep: pick.keep, remove: pick.remove })).removed;
      } catch (failure) {
        setProblem(refusalText(failure, lang, fallback));
        break;
      }
    }
    setDone((before) => before + removed);
    setPicks({});
  };

  const total = groups.reduce((sum, group) => sum + pickOf(group).remove.length, 0);

  return (
    <Modal title={t("الصفوف المكررة", "Duplicate rows")} icon="layers" busy={remove.isPending} wide onClose={onClose}>
      {done > 0 && (
        <div className="note note--ok" role="status" style={{ marginBottom: 12 }}>
          <Icon name="check" />
          <div>{t(`اتمسح ${done} صف مكرر، وكل اللي كان عليهم اتنقل للصف اللي فضل.`, `${done} duplicate row(s) deleted; what they held moved to the row that stayed.`)}</div>
        </div>
      )}
      {found.isError ? (
        <div className="note note--high" role="alert">
          <Icon name="alert" />
          <div>{t("حصلت مشكلة في التحميل.", "Could not load.")}</div>
        </div>
      ) : !found.data ? (
        <Loading className="empty" />
      ) : groups.length === 0 ? (
        <div className="empty">
          <Icon name="check-circle" size="xl" />
          <span>{t("مفيش صفوف مكررة في الشيت ده.", "No duplicate rows on this sheet.")}</span>
        </div>
      ) : (
        <>
          <p className="muted" style={{ marginTop: 0 }}>
            {t(
              `${groups.length} شركة متكررة. في كل مجموعة اختار الصف اللي يفضل، والمعلّم عليه «امسح» هيتمسح. ملاحظاته وسجله وعروض أسعاره بتتنقل للصف اللي فضل.`,
              `${groups.length} companies are on the sheet more than once. In each group pick the row that stays; the ticked rows are deleted. Their notes, timeline and quotations move to the row that stays.`,
            )}
          </p>
          <div className="row" style={{ marginBottom: 12 }}>
            <button className="btn btn--danger" type="button" disabled={remove.isPending || total === 0} onClick={() => void run(groups)}>
              <Icon name="trash" />
              {t("امسح كل المكرر", "Delete all duplicates")} <span className="mono">({total})</span>
            </button>
          </div>
          {problem && (
            <div className="note note--high" role="alert" style={{ marginBottom: 12 }}>
              <Icon name="alert" />
              <div>{problem}</div>
            </div>
          )}
          {groups.map((group) => {
            const pick = pickOf(group);
            return (
              <div className="card" key={group.ids[0]} data-duplicate-group={group.ids.join(",")} style={{ marginBottom: 10, padding: 12 }}>
                <div className="row row--tight" style={{ marginBottom: 8 }}>
                  {group.why.map((why) => (
                    <span key={why} className="chip chip--sm">
                      {lang === "ar" ? WHY[why][0] : WHY[why][1]}
                    </span>
                  ))}
                  <div className="grow" />
                  <button
                    className="btn btn--sm btn--danger"
                    type="button"
                    disabled={remove.isPending || pick.remove.length === 0}
                    onClick={() => void run([group])}
                  >
                    <Icon name="trash" />
                    {t("امسح", "Delete")} <span className="mono">({pick.remove.length})</span>
                  </button>
                </div>
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>{t("يفضل", "Stays")}</th>
                        <th>{t("امسح", "Delete")}</th>
                        <th>{t("الشركة", "Company")}</th>
                        <th>{t("الرقم", "Number")}</th>
                        <th>{t("الإيميل", "E-mail")}</th>
                        <th>{t("الحالة", "Status")}</th>
                        <th>{t("ملاحظات", "Notes")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {group.ids.map((id) => {
                        const lead = byId.get(id)!;
                        const keeps = pick.keep === id;
                        const goes = pick.remove.includes(id);
                        return (
                          <tr key={id} data-duplicate={id}>
                            <td>
                              <input
                                type="radio"
                                name={`keep-${group.ids[0]}`}
                                checked={keeps}
                                aria-label={t(`${lead.company_name} يفضل`, `${lead.company_name} stays`)}
                                onChange={() => setPick(group, { keep: id, remove: group.ids.filter((other) => other !== id) })}
                              />
                            </td>
                            <td>
                              <input
                                type="checkbox"
                                checked={goes}
                                disabled={keeps}
                                aria-label={t(`امسح ${lead.company_name}`, `Delete ${lead.company_name}`)}
                                onChange={(event) =>
                                  setPick(group, {
                                    keep: pick.keep,
                                    remove: event.target.checked ? [...pick.remove, id] : pick.remove.filter((other) => other !== id),
                                  })
                                }
                              />
                            </td>
                            <td>{lead.company_name}</td>
                            <td className="mono" dir="ltr">{lead.phones.join(" · ") || "—"}</td>
                            <td className="mono" dir="ltr">{lead.email || "—"}</td>
                            <td>{lang === "ar" ? STATUS_AR[lead.status] ?? lead.status : lead.status}</td>
                            <td>{lead.notes.length || "—"}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            );
          })}
        </>
      )}
    </Modal>
  );
}
