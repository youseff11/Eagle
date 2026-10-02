import type { Person, Role } from "../api/types";

/** What each role is called, as the pages call it (`ROLE_MAP` in `eagle_tags.py`). */
export const ROLE_LABELS: Record<Role, [string, string]> = {
  admin: ["أدمن", "Admin"],
  operation: ["أوبريشن", "Operation"],
  team_lead: ["تيم ليدر", "Team leader"],
  translator: ["مترجم", "Translator"],
  hr: ["موارد بشرية", "HR"],
  reviewer: ["مراجع", "Reviewer"],
  accounting: ["حسابات", "Accounting"],
  sales: ["مبيعات", "Sales"],
};

/**
 * What a new work group is called before anybody types a name (`services.default_team_group_name`: keep the two in
 * step; the server works the same name out when the box is left empty, so this is a convenience and never the only
 * place the rule lives). "مترجم: <translator> · ليدر: <team leader>", each name labelled, and only when both are
 * known: one translator among the people picked, and a team leader - the person opening the group when that is
 * what they are, otherwise the single leader they picked. Anything ambiguous gives nothing: a wrong name is worse
 * than an empty box.
 */
export function suggestGroupName(me: { name: string; role: Role }, picked: Person[]): string {
  const translators = picked.filter((person) => person.role === "translator");
  if (translators.length !== 1) return "";
  let lead = "";
  if (me.role === "team_lead") {
    lead = me.name;
  } else {
    const leads = picked.filter((person) => person.role === "team_lead");
    if (leads.length === 1) lead = leads[0]!.name;
  }
  return lead ? `مترجم: ${translators[0]!.name} · ليدر: ${lead}` : "";
}
