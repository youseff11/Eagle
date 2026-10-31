import { useCallback, useMemo, useState } from "react";
import type { FormChanges } from "../../api/adminActions";
import type { FormErrors, FormField, FormValue } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";

/** Same value, where `null` (clear a stored secret) is not the same as an empty box (leave it alone). */
const sameValue = (a: FormValue | undefined, b: FormValue | undefined) =>
  a === null || b === null ? a === b : JSON.stringify(a ?? "") === JSON.stringify(b ?? "");

/** What the server says a field holds now. A secret is never sent, so it starts empty. */
function startOf(field: FormField): FormValue {
  if (field.kind === "password") return "";
  if (field.kind === "checkbox") return field.value === true;
  if (field.kind === "multi") return Array.isArray(field.value) ? field.value : [];
  return field.value === undefined || field.value === null ? "" : String(field.value);
}

/**
 * What has been typed into a form, kept apart from what the server sent: a save carries only the fields that differ, so a
 * field nobody touched (and a stored secret above all) keeps its stored value, and a box put back as it was is no change.
 */
export function useFormEdits(fields: FormField[] | undefined) {
  const [edited, setEdited] = useState<FormChanges>({});
  const byName = useMemo(() => new Map((fields ?? []).map((field) => [field.name, field])), [fields]);

  const set = useCallback(
    (name: string, value: FormValue) => {
      const field = byName.get(name);
      setEdited((previous) => {
        const next = { ...previous };
        if (field && sameValue(value, startOf(field))) delete next[name];
        else next[name] = value;
        return next;
      });
    },
    [byName],
  );
  const valueOf = useCallback(
    (field: FormField): FormValue => (field.name in edited ? (edited[field.name] as FormValue) : startOf(field)),
    [edited],
  );
  const reset = useCallback(() => setEdited({}), []);
  return { edited, set, valueOf, reset, dirty: Object.keys(edited).length > 0 };
}

/** Roles that do not clock in, have no roster and no pay: the owner and technical support (`User.follows_company_rules`). */
const OUTSIDE_RULES = ["admin", "support"];
const ALL_ROLES = ["admin", "operation", "team_lead", "translator", "hr", "reviewer", "accounting", "sales", "support"];
const INSIDE_RULES = ALL_ROLES.filter((role) => !OUTSIDE_RULES.includes(role));

/**
 * The staff form's fields that mean something for some roles only, with those roles: a field not named here is for everyone.
 * Same lists as the server's (`MAIL_ALIAS_ROLES`, `WA_LINE_ROLES`, `COST_RATE_ROLES`, `IDENTITY_GRANTABLE_ROLES` and the
 * checks in `StaffEditForm.clean`), which refuse these fields on any other role.
 */
const FIELD_ROLES: Record<string, string[]> = {
  team_lead: ["translator"],
  translator_level: ["translator"],
  cost_per_250: ["translator", "team_lead"],
  client_identity_access: ["sales", "accounting"],
  is_sales_manager: ["sales"],
  sales_track: ["sales"],
  mail_alias: ["operation", "sales"],
  wa_phone_number_id: ["operation", "sales"],
  // HR and the owner run the attendance board by their role; the flag is how anybody else is given it.
  attendance_manager: INSIDE_RULES.filter((role) => role !== "hr"),
  attendance_enabled: INSIDE_RULES,
  schedule_kind: INSIDE_RULES,
  work_mode: INSIDE_RULES,
  rating: INSIDE_RULES,
};

/** The ones the server refuses on a role that has none (`StaffEditForm.clean`): the only ones emptied when the role changes away. */
const REFUSED_ELSEWHERE = ["translator_level", "cost_per_250", "client_identity_access", "is_sales_manager", "sales_track", "mail_alias", "wa_phone_number_id"];

/** What a field says "none" with once its role no longer has it: the first choice of a list (the blank, or the default one). */
function emptied(field: FormField): FormValue {
  if (field.kind === "checkbox") return false;
  if (field.kind === "multi") return [];
  if (field.kind === "select") return field.choices?.[0]?.value ?? "";
  return "";
}

/**
 * A staff form with only the fields the role in the role box has: a translator sees the translator's, a leader the leader's,
 * Sales the Sales'. The ones left out are also left out of what a save carries, so a value typed and then abandoned by changing
 * the role never reaches the server. When the role itself is being changed, a hidden field the server refuses on the new role
 * and that holds something is carried emptied: nobody could see its box to clear it.
 */
export function staffFields(fields: FormField[], edits: ReturnType<typeof useFormEdits>) {
  const roleField = fields.find((field) => field.name === "role");
  const role = roleField ? String(edits.valueOf(roleField)) : null;
  const hidden = (field: FormField) => role !== null && field.name in FIELD_ROLES && !FIELD_ROLES[field.name]!.includes(role);
  const shown = fields.filter((field) => !hidden(field));
  const hiddenNames = new Set(fields.filter(hidden).map((field) => field.name));
  const carried: Record<string, FormValue> = Object.fromEntries(Object.entries(edits.edited).filter(([name]) => !hiddenNames.has(name)));
  if (roleField && "role" in edits.edited) {
    for (const field of fields) {
      if (!hiddenNames.has(field.name) || !REFUSED_ELSEWHERE.includes(field.name) || field.disabled) continue;
      const empty = emptied(field);
      if (!sameValue(startOf(field), empty)) carried[field.name] = empty;
    }
  }
  return { shown, carried };
}

function Errors({ messages, id }: { messages?: string[]; id: string }) {
  if (!messages || messages.length === 0) return null;
  return (
    <ul className="errorlist" id={id} role="alert">
      {messages.map((message, index) => (
        <li key={index}>{message}</li>
      ))}
    </ul>
  );
}

function Control({
  field,
  value,
  onChange,
  describedBy,
  id,
}: {
  field: FormField;
  value: FormValue;
  onChange: (value: FormValue) => void;
  describedBy?: string;
  id: string;
}) {
  const { t, lang } = usePreferences();
  const common = { id, disabled: field.disabled, "aria-describedby": describedBy, dir: field.ltr ? ("ltr" as const) : undefined };

  switch (field.kind) {
    case "checkbox":
      return <input {...common} type="checkbox" checked={value === true} onChange={(event) => onChange(event.target.checked)} />;
    case "select":
      return (
        <select {...common} className="input" value={typeof value === "string" ? value : ""} onChange={(event) => onChange(event.target.value)}>
          {(field.choices ?? []).map((choice) => (
            <option key={choice.value} value={choice.value}>
              {(lang === "ar" ? choice.label_ar : choice.label_en) ?? choice.label}
            </option>
          ))}
        </select>
      );
    case "multi": {
      const chosen = Array.isArray(value) ? value : [];
      return (
        <div className="row row--tight" style={{ flexWrap: "wrap" }} id={id}>
          {(field.choices ?? []).map((choice) => (
            <label key={choice.value} className="chip" style={{ cursor: "pointer" }}>
              <input
                type="checkbox"
                disabled={field.disabled}
                checked={chosen.includes(choice.value)}
                onChange={(event) =>
                  onChange(event.target.checked ? [...chosen, choice.value] : chosen.filter((item) => item !== choice.value))
                }
              />
              <span>{choice.label}</span>
            </label>
          ))}
        </div>
      );
    }
    case "password": {
      const cleared = value === null;
      return (
        <>
          <input
            {...common}
            type="password"
            className="input"
            dir="ltr"
            autoComplete="new-password"
            disabled={field.disabled || cleared}
            value={typeof value === "string" ? value : ""}
            placeholder={field.saved ? t("محفوظ — سيبه فاضي عشان يفضل زي ما هو", "Saved - leave empty to keep it") : ""}
            onChange={(event) => onChange(event.target.value)}
          />
          {field.saved && (
            <label className="helptext" style={{ cursor: "pointer" }}>
              <input type="checkbox" checked={cleared} onChange={(event) => onChange(event.target.checked ? null : "")} />{" "}
              {t("امسح القيمة المحفوظة", "Clear the saved value")}
            </label>
          )}
        </>
      );
    }
    case "textarea":
      return (
        <textarea
          {...common}
          className="input"
          rows={Number(field.rows) || 3}
          maxLength={Number(field.maxlength) || undefined}
          placeholder={field.placeholder}
          value={typeof value === "string" ? value : ""}
          onChange={(event) => onChange(event.target.value)}
        />
      );
    default: {
      const INPUT_TYPES: Partial<Record<FormField["kind"], string>> = { number: "number", email: "email", time: "time", date: "date", datetime: "datetime-local" };
      const type = INPUT_TYPES[field.kind] ?? "text";
      return (
        <input
          {...common}
          type={type}
          className="input"
          min={field.min}
          max={field.max}
          step={field.step}
          maxLength={Number(field.maxlength) || undefined}
          placeholder={field.placeholder}
          value={typeof value === "string" ? value : ""}
          onChange={(event) => onChange(event.target.value)}
        />
      );
    }
  }
}

/**
 * The fields of a Django form, drawn from what the server says they are (`api_forms.describe`) with the form's own labels,
 * hints and messages (or the bilingual ones the server laid over them). The rules are the form's: this draws, it does not
 * decide. A box that is ticked or not is drawn as the classic pages draw it: the box, then its words.
 */
export function DjangoForm({
  fields,
  edits,
  errors = {},
  prefix = "f",
}: {
  fields: FormField[];
  edits: ReturnType<typeof useFormEdits>;
  errors?: FormErrors;
  /** Keeps two forms on one page from sharing ids. */
  prefix?: string;
}) {
  const { lang } = usePreferences();
  return (
    <>
      {errors.__all__ && <Errors messages={errors.__all__} id={`${prefix}-all`} />}
      <div className="form-grid">
        {fields.map((field) => {
          const id = `${prefix}-${field.name}`;
          const problems = errors[field.name];
          const label = (lang === "ar" ? field.label_ar : field.label_en) ?? field.label;
          const hint = (lang === "ar" ? field.hint_ar : field.hint_en) ?? field.help;
          const control = (
            <Control
              field={field}
              id={id}
              value={edits.valueOf(field)}
              onChange={(value) => edits.set(field.name, value)}
              describedBy={problems?.length ? `${id}-errors` : undefined}
            />
          );
          return (
            <div className="field" key={field.name} data-field={field.name}>
              {field.kind === "checkbox" ? (
                <label className="switch" htmlFor={id}>
                  {control}
                  <span>{label}</span>
                </label>
              ) : (
                <>
                  <label htmlFor={id}>{label}</label>
                  {control}
                </>
              )}
              <Errors messages={problems} id={`${id}-errors`} />
              {hint && <span className="helptext">{hint}</span>}
            </div>
          );
        })}
      </div>
    </>
  );
}
