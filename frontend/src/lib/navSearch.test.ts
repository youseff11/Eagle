import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { SCREENS } from "../components/Shell";
import { KEYWORDS, SPOTS, buildIndex, normAr, prepareIndex, searchPages, searchTokens, type SearchLine } from "./navSearch";

const line = (path: string, label: [string, string], where: [string, string] = ["الشغل", "Work"], icon = "layers"): SearchLine => ({
  path,
  icon,
  label,
  where,
});

const admin: SearchLine[] = [
  line("/admin/settings", ["الإعدادات و AI", "Settings & AI"], ["الإعدادات", "Settings"], "sliders"),
  line("/accounts/rules", ["قواعد الحساب", "Payroll rules"], ["الإعدادات", "Settings"], "list-checks"),
  line("/hr/leave", ["طلبات الإجازة", "Leave requests"], ["الموظفين", "People"], "hand"),
  line("/inbox", ["ميلات واردة", "Incoming mail"]),
  line("/tasks", ["التاسكات", "Tasks"]),
  line("/notifications", ["التنبيهات", "Notifications"], ["حسابي", "My account"], "bell"),
];

const found = (lines: SearchLine[], query: string) => searchPages(prepareIndex(buildIndex(lines)), query);

describe("normAr", () => {
  it("reads an Arabic word the same however it is spelled", () => {
    expect(normAr("إجازات")).toBe(normAr("اجازات"));
    expect(normAr("مكافأة")).toBe(normAr("مكافاه"));
    expect(normAr("مستشفى")).toBe(normAr("مستشفي"));
    expect(normAr("  Mail   BOX ")).toBe("mail box");
    expect(normAr("جَدْوَل")).toBe("جدول");
  });
});

describe("searchTokens", () => {
  it("leaves filler words out and tries a word without its article too", () => {
    expect(searchTokens("عايز اروح لصفحة الاجازات").map((token) => token.full)).toEqual(["لصفحه", "الاجازات"]);
    expect(searchTokens("الحظر")).toEqual([{ full: "الحظر", bare: "حظر" }]);
    expect(searchTokens("i want to open the page")).toEqual([]);
    expect(searchTokens("   ")).toEqual([]);
  });
});

describe("the index", () => {
  it("holds the pages of the lines the person has, and each page once", () => {
    const rows = buildIndex([...admin, line("/inbox", ["ميلات واردة", "Incoming mail"])]);
    const pages = rows.filter((row) => !row.hash).map((row) => row.path);
    expect(pages).toEqual(["/admin/settings", "/accounts/rules", "/hr/leave", "/inbox", "/tasks", "/notifications"]);
  });

  it("holds the sections inside a page only for a person who has the page", () => {
    const anchors = (lines: SearchLine[]) => buildIndex(lines).filter((row) => row.hash).map((row) => row.hash);
    expect(anchors(admin)).toContain("settings-rate_keywords");
    expect(anchors(admin)).toContain("r-bonuses");
    const operation = [line("/inbox", ["ميلات واردة", "Incoming mail"]), line("/tasks", ["التاسكات", "Tasks"])];
    expect(anchors(operation)).toEqual([]);
    // One page, not the other: the sections follow their own page.
    expect(anchors([admin[1]!])).not.toContain("s-ai");
    expect(anchors([admin[0]!])).not.toContain("r-bonuses");
  });

  it("names a section by the page it is in", () => {
    const row = buildIndex(admin).find((one) => one.hash === "s-email")!;
    expect(row.where).toEqual(["الإعدادات و AI", "Settings & AI"]);
    expect(row.icon).toBe("sliders");
  });
});

describe("searching pages", () => {
  it("finds a page by its name, in either language", () => {
    expect(found(admin, "التاسكات")[0]?.path).toBe("/tasks");
    expect(found(admin, "tasks")[0]?.path).toBe("/tasks");
    expect(found(admin, "Payroll rules")[0]?.path).toBe("/accounts/rules");
  });

  it("finds a page by the words people use for it", () => {
    // "اجازات" is also the name of the leave rules' section, which says it as well: both are found, the page among them.
    expect(found(admin, "اجازات").map((row) => row.path)).toContain("/hr/leave");
    expect(found(admin, "طلب اجازة")[0]?.path).toBe("/hr/leave");
    // The email settings section says "ايميل" in its own name, so it comes first; the mailbox is found by the same word.
    expect(found(admin, "ايميل").map((row) => row.path)).toContain("/inbox");
    expect(found(admin, "inbox")[0]?.path).toBe("/inbox");
    expect(found(admin, "اشعارات").map((row) => row.path)).toContain("/notifications");
    expect(found([admin[5]!], "اشعارات")[0]?.path).toBe("/notifications");
  });

  it("finds a section inside a page, and puts it above its page when it says it better", () => {
    const blocked = found(admin, "كلمات الحظر");
    expect(blocked[0]).toMatchObject({ path: "/admin/settings", hash: "settings-rate_keywords" });
    // The section that only shares a word with it ("كلمات" in the production bands) comes after, not before.
    expect(blocked.findIndex((row) => row.hash === "r-bands")).toBeGreaterThan(0);
    const bonus = found(admin, "المكافآت");
    expect(bonus[0]).toMatchObject({ path: "/accounts/rules", hash: "r-bonuses" });
  });

  it("finds nothing for a page the person has no line for", () => {
    const operation = [line("/inbox", ["ميلات واردة", "Incoming mail"]), line("/tasks", ["التاسكات", "Tasks"])];
    expect(found(operation, "كلمات الحظر")).toEqual([]);
    expect(found(operation, "settings")).toEqual([]);
    expect(found(operation, "قواعد الحساب")).toEqual([]);
  });

  it("finds nothing for nothing, or for filler alone, and no more than eight", () => {
    expect(found(admin, "")).toEqual([]);
    expect(found(admin, "عايز اروح")).toEqual([]);
    const many = Array.from({ length: 20 }, (_, at) => line(`/p${at}`, [`صفحة تاسك ${at}`, `Task page ${at}`]));
    expect(found(many, "تاسك")).toHaveLength(8);
  });

  it("puts the row that matches everything typed above the ones that match a part of it", () => {
    const rows = [line("/a", ["ميلات", "Mail"]), line("/b", ["ميلات واردة", "Incoming mail"]), line("/c", ["واردة", "Incoming"])];
    expect(found(rows, "ميلات واردة")[0]?.path).toBe("/b");
  });
});

describe("what the words and the sections point at", () => {
  /** Every address a line of the menu can have. */
  const addresses = new Set<string>(["/notifications"]);
  for (const screen of Object.values(SCREENS)) {
    addresses.add(screen.path);
    for (const entry of screen.extra ?? []) addresses.add(entry.path);
  }

  it("keeps words only for pages that are lines of the menu", () => {
    for (const path of Object.keys(KEYWORDS)) expect(addresses.has(path), path).toBe(true);
  });

  it("keeps sections only inside pages that are lines of the menu, each once", () => {
    for (const spot of SPOTS) expect(addresses.has(spot.path), spot.anchor).toBe(true);
    const keys = SPOTS.map((spot) => `${spot.path}#${spot.anchor}`);
    expect(new Set(keys).size).toBe(keys.length);
  });

  // The anchors are ids the pages draw. A section renamed on the server would send the search to a page that does not
  // scroll anywhere: the pages and the server's lists are read here, as the classic menu's own test read its templates.
  const root = resolve(import.meta.dirname, "../../..");
  const read = (path: string) => readFileSync(resolve(root, path), "utf-8");
  const keysOf = (source: string, name: string): string[] => {
    const start = source.indexOf(`${name} = (`);
    const body = source.slice(start, source.indexOf("\n)\n", start));
    return [...body.matchAll(/"key": "([a-z_]+)"/g)].map((match) => match[1]!);
  };

  it("lands on sections the settings page and the rules page really have", () => {
    const settings = keysOf(read("dashboard/api_admin_settings.py"), "SECTIONS");
    const rules = keysOf(read("dashboard/payroll_texts.py"), "SECTIONS");
    expect(settings.length).toBeGreaterThan(2);
    expect(rules.length).toBeGreaterThan(5);
    expect(read("frontend/src/pages/AdminSettingsPage.tsx")).toContain("id={`s-${section.key}`}");
    expect(read("frontend/src/pages/AccountsRulesPage.tsx")).toContain("id={`r-${section.key}`}");
    expect(read("frontend/src/pages/AccountsRulesPage.tsx")).toContain('id="r-bands"');
    for (const spot of SPOTS.filter((one) => one.path === "/admin/settings" && one.anchor.startsWith("s-"))) {
      expect(settings, spot.anchor).toContain(spot.anchor.slice(2));
    }
    for (const spot of SPOTS.filter((one) => one.path === "/accounts/rules" && one.anchor !== "r-bands")) {
      expect(rules, spot.anchor).toContain(spot.anchor.slice(2));
    }
  });

  it("lands on the fields of the settings page that the server really sends", () => {
    const source = read("dashboard/api_admin_settings.py");
    expect(read("frontend/src/pages/AdminSettingsPage.tsx")).toContain('prefix="settings"');
    for (const spot of SPOTS.filter((one) => one.anchor.startsWith("settings-"))) {
      expect(source, spot.anchor).toContain(`"${spot.anchor.slice("settings-".length)}"`);
    }
  });

  it("lands on the cards the recruitment settings page draws", () => {
    const page = read("frontend/src/pages/HrRecruitmentSettingsPage.tsx");
    for (const spot of SPOTS.filter((one) => one.path === "/hr/recruitment/settings")) expect(page, spot.anchor).toContain(`id="${spot.anchor}"`);
  });
});
