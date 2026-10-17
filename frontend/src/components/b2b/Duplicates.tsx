import { useDeferredValue, useState } from "react";
import { refusalText, useDeleteLead, useDuplicates, useRemoveDuplicates, type B2bLead, type DuplicateGroup } from "../../api/b2b";
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

/** At most this many rows answer one search: past it the person types more. */
const MAX_FOUND = 50;
/** The last digits two numbers are matched on, with or without the country code (`Client.PHONE_KEY_DIGITS`). */
const PHONE_KEY_DIGITS = 9;

const digitsOf = (text: string) => text.replace(/\D+/g, "");
/** A company name as the server compares it (`b2b.name_key`): no case, no spaces, no dots or dashes. */
const nameKey = (text: string) => text.toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");

/**
 * Whether a row answers what was typed in the search (17/10/2026: «أشوف الرقم ده مكرر ولا لا»). A number is matched on its
 * digits, so "+20 101 234 5678" finds "01012345678" and a part of a number finds the whole one; anything else on the
 * company name (the way the duplicates compare it), the contact person or the e-mail.
 */
export function leadMatches(lead: B2bLead, typed: string): boolean {
  const words = typed.trim();
  const digits = digitsOf(words);
  if (digits.length >= 4 && !/\p{L}/u.test(words)) {
    const key = digits.slice(-PHONE_KEY_DIGITS);
    return lead.phones.some((number) => {
      const own = digitsOf(number);
      return own.includes(digits) || (digits.length >= PHONE_KEY_DIGITS && own.includes(key));
    });
  }
  const key = nameKey(words);
  if (!key) return false;
  const lower = words.toLocaleLowerCase();
  return nameKey(lead.company_name).includes(key) || nameKey(lead.contact_person).includes(key) || lead.email.toLocaleLowerCase().includes(lower);
}

const contacted = (lead: B2bLead) => Boolean(lead.whatsapp_at || lead.email_at || lead.call_at);

/**
 * «المكرر» on a sheet (15/10/2026): the companies that are on it more than once - the same number, e-mail or name - in
 * groups. In each group one row stays (the one with the most on it, unless the person picks another) and the ticked ones
 * go. Nothing they held is lost: their notes, history and quotations move to the row that stays, and an empty cell of it
 * takes what a copy had (`b2b.merge_duplicates`, which checks again that they are one company).
 *
 * The search on top (17/10/2026) answers «is this number or name on the sheet twice?»: every row it finds says whether it
 * is in a group, and a row that is not a copy can be deleted from there too (a company found later to be no translation
 * work) - through the same door as «امسح الصف» on the row, so a company already contacted is kept (mark it Lost).
 */
export function Duplicates({ sheetId, leads, onClose }: { sheetId: number; leads: B2bLead[]; onClose: () => void }) {
  const { t, lang } = usePreferences();
  const found = useDuplicates(sheetId);
  const remove = useRemoveDuplicates(sheetId);
  const drop = useDeleteLead();
  const [picks, setPicks] = useState<Record<number, Pick>>({});
  const [problem, setProblem] = useState("");
  const [done, setDone] = useState(0);
  const [search, setSearch] = useState("");
  const typed = useDeferredValue(search);
  const [confirming, setConfirming] = useState(0);
  const [dropped, setDropped] = useState("");
  const byId = new Map(leads.map((lead) => [lead.id, lead]));
  const groups = (found.data?.groups ?? []).filter((group) => group.ids.every((id) => byId.has(id)));
  const groupOf = new Map(groups.flatMap((group) => group.ids.map((id) => [id, group] as const)));
  const pickOf = (group: DuplicateGroup) => picks[group.ids[0]] ?? firstPick(group);
  const setPick = (group: DuplicateGroup, pick: Pick) => setPicks((all) => ({ ...all, [group.ids[0]]: pick }));
  const fallback = t("مقدرتش أمسح. جرّب تاني.", "Could not delete. Try again.");
  const busy = remove.isPending || drop.isPending;

  const searching = typed.trim() !== "";
  const matched = searching ? leads.filter((lead) => leadMatches(lead, typed)) : [];
  const matchedIds = new Set(matched.map((lead) => lead.id));
  // While searching, only the groups of the rows found are shown, under them.
  const shownGroups = searching ? groups.filter((group) => group.ids.some((id) => matchedIds.has(id))) : groups;

  // One group at a time, so a group that changed meanwhile stops there and the rest is left as it was.
  const run = async (chosen: DuplicateGroup[]) => {
    setProblem("");
    setDropped("");
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

  const deleteRow = (lead: B2bLead) => {
    if (busy) return;
    setProblem("");
    drop.mutate(lead.id, {
      onSuccess: () => {
        setConfirming(0);
        setDropped(lead.company_name);
      },
      onError: (failure) => {
        setConfirming(0);
        setProblem(refusalText(failure, lang, fallback));
      },
    });
  };

  const total = groups.reduce((sum, group) => sum + pickOf(group).remove.length, 0);

  const groupCard = (group: DuplicateGroup) => {
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
          <button className="btn btn--sm btn--danger" type="button" disabled={busy || pick.remove.length === 0} onClick={() => void run([group])}>
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
  };

  // The delete cell of a row the search found: a copy is merged in its group below; a contacted company is kept (the
  // server refuses it too); any other row goes after a second press.
  const deleteCell = (lead: B2bLead) => {
    if (groupOf.has(lead.id)) return <span className="muted">{t("امسحه من مجموعته تحت", "Delete it in its group below")}</span>;
    if (contacted(lead)) return <span className="muted">{t("اتواصلنا معاها: غيّر حالتها لـLost", "Contacted: set it to Lost")}</span>;
    if (confirming === lead.id) {
      return (
        <div className="row row--tight">
          <button className="btn btn--sm btn--danger" type="button" disabled={busy} onClick={() => deleteRow(lead)}>
            <Icon name="trash" />
            {t("أكّد المسح", "Confirm delete")}
          </button>
          <button className="btn btn--sm" type="button" disabled={busy} onClick={() => setConfirming(0)}>
            {t("لأ", "No")}
          </button>
        </div>
      );
    }
    return (
      <button
        className="btn btn--sm btn--danger"
        type="button"
        disabled={busy}
        aria-label={t(`امسح الصف ${lead.company_name}`, `Delete the row ${lead.company_name}`)}
        onClick={() => setConfirming(lead.id)}
      >
        <Icon name="trash" />
        {t("امسح الصف", "Delete the row")}
      </button>
    );
  };

  return (
    <Modal title={t("الصفوف المكررة", "Duplicate rows")} icon="layers" busy={busy} wide onClose={onClose}>
      <div className="field-icon" style={{ marginBottom: 12 }}>
        <Icon name="search" className="ic--lead" />
        <input
          className="input"
          value={search}
          maxLength={100}
          placeholder={t("ابحث برقم أو اسم شركة: مكرر ولا لا؟", "Search a number or a company name: is it there twice?")}
          aria-label={t("ابحث في الشيت", "Search the sheet")}
          onChange={(event) => {
            setSearch(event.target.value);
            setConfirming(0);
          }}
        />
      </div>
      {done > 0 && (
        <div className="note note--ok" role="status" style={{ marginBottom: 12 }}>
          <Icon name="check" />
          <div>{t(`اتمسح ${done} صف مكرر، وكل اللي كان عليهم اتنقل للصف اللي فضل.`, `${done} duplicate row(s) deleted; what they held moved to the row that stayed.`)}</div>
        </div>
      )}
      {dropped && (
        <div className="note note--ok" role="status" style={{ marginBottom: 12 }}>
          <Icon name="check" />
          <div>{t(`اتمسح صف «${dropped}».`, `The row “${dropped}” was deleted.`)}</div>
        </div>
      )}
      {problem && (
        <div className="note note--high" role="alert" style={{ marginBottom: 12 }}>
          <Icon name="alert" />
          <div>{problem}</div>
        </div>
      )}
      {found.isError ? (
        <div className="note note--high" role="alert">
          <Icon name="alert" />
          <div>{t("حصلت مشكلة في التحميل.", "Could not load.")}</div>
        </div>
      ) : !found.data ? (
        <Loading className="empty" />
      ) : searching ? (
        <>
          {matched.length === 0 ? (
            <div className="empty">
              <Icon name="search" size="xl" />
              <span>{t(`مفيش صف فيه «${typed.trim()}» في الشيت ده.`, `No row on this sheet has “${typed.trim()}”.`)}</span>
            </div>
          ) : (
            <>
              <p className="muted" style={{ marginTop: 0 }}>
                {matched.length > MAX_FOUND
                  ? t(`لقيت ${matched.length} صف، ظاهر أول ${MAX_FOUND}. اكتب أكتر.`, `${matched.length} rows found, the first ${MAX_FOUND} shown. Type more.`)
                  : t(`لقيت ${matched.length} صف.`, `${matched.length} row(s) found.`)}
              </p>
              <div className="table-wrap" style={{ marginBottom: 12 }}>
                <table className="table">
                  <thead>
                    <tr>
                      <th>{t("الشركة", "Company")}</th>
                      <th>{t("الرقم", "Number")}</th>
                      <th>{t("الإيميل", "E-mail")}</th>
                      <th>{t("الحالة", "Status")}</th>
                      <th>{t("مكرر؟", "Twice?")}</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {matched.slice(0, MAX_FOUND).map((lead) => {
                      const group = groupOf.get(lead.id);
                      return (
                        <tr key={lead.id} data-found={lead.id}>
                          <td>{lead.company_name}</td>
                          <td className="mono" dir="ltr">{lead.phones.join(" · ") || "—"}</td>
                          <td className="mono" dir="ltr">{lead.email || "—"}</td>
                          <td>{lang === "ar" ? STATUS_AR[lead.status] ?? lead.status : lead.status}</td>
                          <td>
                            {group ? (
                              <span className="badge badge--wait">{t(`مكرر · ${group.ids.length} صفوف`, `Twice · ${group.ids.length} rows`)}</span>
                            ) : (
                              <span className="badge badge--ok">{t("مش مكرر", "Not twice")}</span>
                            )}
                          </td>
                          <td>{deleteCell(lead)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}
          {shownGroups.map(groupCard)}
        </>
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
            <button className="btn btn--danger" type="button" disabled={busy || total === 0} onClick={() => void run(groups)}>
              <Icon name="trash" />
              {t("امسح كل المكرر", "Delete all duplicates")} <span className="mono">({total})</span>
            </button>
          </div>
          {groups.map(groupCard)}
        </>
      )}
    </Modal>
  );
}
