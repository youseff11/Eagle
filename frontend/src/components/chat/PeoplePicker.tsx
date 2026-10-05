import { useState } from "react";
import type { Person } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { ROLE_LABELS } from "../../lib/roles";
import { Avatar } from "../Avatar";

/**
 * A list of people to tick, with a search box: one row each, with their role beside the name so two people of the
 * same name are told apart. What is ticked is a set of ids the page keeps (`picked`); the list only draws it.
 */
export function PeoplePicker({
  people,
  picked,
  onChange,
  label,
}: {
  people: Person[];
  picked: number[];
  onChange: (next: number[]) => void;
  label: string;
}) {
  const { t } = usePreferences();
  const [query, setQuery] = useState("");
  const needle = query.trim().toLowerCase();
  const shown = people.filter((person) => !needle || person.name.toLowerCase().includes(needle));

  const toggle = (id: number) => onChange(picked.includes(id) ? picked.filter((one) => one !== id) : [...picked, id]);

  return (
    <>
      <input
        className="input"
        type="search"
        autoComplete="off"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={t("دوّر بالاسم...", "Search by name...")}
        aria-label={t("دوّر", "Search")}
      />
      <div className="fwd-list" role="group" aria-label={label}>
        {people.length === 0 && <div className="muted">{t("مفيش حد يتضاف.", "Nobody left to add.")}</div>}
        {people.length > 0 && shown.length === 0 && <div className="muted">{t("مفيش نتايج.", "Nothing matches.")}</div>}
        {shown.map((person) => {
          const on = picked.includes(person.id);
          return (
            <label className={`fwd-row${on ? " is-on" : ""}`} key={person.id}>
              <input type="checkbox" checked={on} onChange={() => toggle(person.id)} />
              <Avatar src={person.avatar} initials={person.initials} tone="staff" />
              <span className="fwd-row__body">
                <b>{person.name}</b>
                <span className="muted">{t(...(ROLE_LABELS[person.role] ?? [person.role, person.role]))}</span>
              </span>
            </label>
          );
        })}
      </div>
    </>
  );
}
