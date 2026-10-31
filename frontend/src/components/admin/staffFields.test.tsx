import { renderHook, act } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { FormField } from "../../api/types";
import { staffFields, useFormEdits } from "./DjangoForm";

const field = (name: string, kind: FormField["kind"], value?: FormField["value"], extra: Partial<FormField> = {}): FormField => ({
  name,
  label: name,
  kind,
  required: false,
  help: "",
  disabled: false,
  ltr: false,
  value,
  ...extra,
});

const ROLES = ["admin", "operation", "team_lead", "translator", "hr", "reviewer", "accounting", "sales", "support"].map((value) => ({ value, label: value }));

const form = (role: string, extra: Record<string, FormField["value"]> = {}): FormField[] => [
  field("first_name", "text", "Sara"),
  field("role", "select", role, { choices: ROLES }),
  field("team_lead", "select", "", { choices: [{ value: "", label: "none" }] }),
  field("translator_level", "select", "", { choices: [{ value: "", label: "none" }, { value: "junior", label: "Junior" }] }),
  field("cost_per_250", "number", extra.cost_per_250 ?? ""),
  field("client_identity_access", "checkbox", extra.client_identity_access ?? false),
  field("is_sales_manager", "checkbox", false),
  field("sales_track", "select", extra.sales_track ?? "b2b", { choices: [{ value: "b2b", label: "B2B" }, { value: "b2c_field", label: "Field" }] }),
  field("mail_alias", "select", extra.mail_alias ?? "", { choices: [{ value: "", label: "none" }, { value: "a@x.com", label: "a" }] }),
  field("wa_phone_number_id", "select", "", { choices: [{ value: "", label: "none" }] }),
  field("attendance_manager", "checkbox", false),
  field("attendance_enabled", "checkbox", true),
  field("schedule_kind", "select", "fixed", { choices: [{ value: "fixed", label: "Fixed" }] }),
  field("work_mode", "select", "hybrid", { choices: [{ value: "hybrid", label: "Hybrid" }] }),
  field("rating", "number", "5"),
  field("employment_type", "select", "full_time", { choices: [{ value: "full_time", label: "Full" }] }),
];

const shownFor = (role: string) => {
  const fields = form(role);
  const { result } = renderHook(() => {
    const edits = useFormEdits(fields);
    return { edits, staff: staffFields(fields, edits) };
  });
  return result.current.staff.shown.map((one) => one.name);
};

describe("staffFields: each role sees its own settings", () => {
  it("a translator: leader, level, price; not Sales, mail or number", () => {
    const names = shownFor("translator");
    expect(names).toEqual(expect.arrayContaining(["team_lead", "translator_level", "cost_per_250", "attendance_enabled", "schedule_kind"]));
    for (const gone of ["sales_track", "is_sales_manager", "mail_alias", "wa_phone_number_id", "client_identity_access"]) expect(names).not.toContain(gone);
  });

  it("a team leader: price but no leader or level", () => {
    const names = shownFor("team_lead");
    expect(names).toContain("cost_per_250");
    for (const gone of ["team_lead", "translator_level", "sales_track", "mail_alias"]) expect(names).not.toContain(gone);
  });

  it("Sales: track, manager mark, mail, number, identity; no translator settings", () => {
    const names = shownFor("sales");
    expect(names).toEqual(expect.arrayContaining(["sales_track", "is_sales_manager", "mail_alias", "wa_phone_number_id", "client_identity_access"]));
    for (const gone of ["team_lead", "translator_level", "cost_per_250"]) expect(names).not.toContain(gone);
  });

  it("operation: mail and number only", () => {
    const names = shownFor("operation");
    expect(names).toEqual(expect.arrayContaining(["mail_alias", "wa_phone_number_id"]));
    for (const gone of ["sales_track", "is_sales_manager", "client_identity_access", "cost_per_250", "team_lead"]) expect(names).not.toContain(gone);
  });

  it("accounting: identity access, nothing of Sales, mail or translators", () => {
    const names = shownFor("accounting");
    expect(names).toContain("client_identity_access");
    for (const gone of ["sales_track", "mail_alias", "cost_per_250", "team_lead"]) expect(names).not.toContain(gone);
  });

  it("HR: no role-specific boxes and no attendance-manager flag (the role has it)", () => {
    const names = shownFor("hr");
    for (const gone of ["attendance_manager", "mail_alias", "sales_track", "cost_per_250", "client_identity_access", "team_lead"]) expect(names).not.toContain(gone);
    expect(names).toContain("attendance_enabled");
  });

  it("the owner and technical support: no attendance, roster, work mode or rating boxes", () => {
    for (const role of ["admin", "support"]) {
      const names = shownFor(role);
      for (const gone of ["attendance_enabled", "attendance_manager", "schedule_kind", "work_mode", "rating", "mail_alias", "cost_per_250"]) expect(names).not.toContain(gone);
      expect(names).toEqual(expect.arrayContaining(["first_name", "role", "employment_type"]));
    }
  });

  it("changing the role away empties what the new role refuses, and drops what was typed in a hidden box", () => {
    const fields = form("sales", { sales_track: "b2c_field", mail_alias: "a@x.com", client_identity_access: true });
    const { result } = renderHook(() => {
      const edits = useFormEdits(fields);
      return { edits, staff: staffFields(fields, edits) };
    });
    act(() => result.current.edits.set("role", "translator"));
    const carried = result.current.staff.carried;
    expect(carried).toMatchObject({ role: "translator", sales_track: "b2b", mail_alias: "", client_identity_access: false });
    expect(carried).not.toHaveProperty("attendance_enabled");
    act(() => result.current.edits.set("cost_per_250", "12"));
    act(() => result.current.edits.set("role", "hr"));
    expect(result.current.staff.carried).not.toHaveProperty("cost_per_250");
  });

  it("with no role change, nothing stored is cleared", () => {
    const fields = form("hr", { mail_alias: "a@x.com" });
    const { result } = renderHook(() => {
      const edits = useFormEdits(fields);
      return { edits, staff: staffFields(fields, edits) };
    });
    act(() => result.current.edits.set("first_name", "Mona"));
    expect(result.current.staff.carried).toEqual({ first_name: "Mona" });
  });
});
