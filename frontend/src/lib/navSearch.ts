/**
 * The menu's search: the pages a person may open, the sections inside some of them, and (from the server) their tasks.
 *
 * Type what you want, "كلمات الحظر", "باسورد الإيميل", "اجازات", and go straight there. The index is the menu's own lines,
 * so a page the person has no line for never turns up, neither as itself nor as one of its sections: the gate is the
 * menu's and is written once. Matching is forgiving on purpose: Arabic spelled any of the usual ways, filler words
 * ignored, and the row that matches most of what was typed comes first. The words and the scoring are the classic
 * menu's (the old classic `nav.py` and `app.js`, both deleted), so the same thing is found by the same typing.
 */

/** A line of the menu, as the search needs it. */
export interface SearchLine {
  path: string;
  icon: string;
  label: [string, string];
  /** The heading of the section the line is in, both languages. */
  where: [string, string];
}

export interface SearchRow {
  /** Where it goes, and the part of that page to land on (`""` for the page itself). */
  path: string;
  hash: string;
  icon: string;
  label: [string, string];
  where: [string, string];
  keywords: string;
}

/** Words people type for a page, besides its name: Arabic as it is spoken, and the English. Keyed by the page's address. */
export const KEYWORDS: Record<string, string> = {
  "/inbox": "ميل ايميل بريد رسايل واردة جيميل mail email inbox letters",
  "/chats": "شات محادثات واتساب عملاء جروب زمايل رسايل chat whatsapp messages groups",
  "/line": "رقمي خطي واتساب ايميلي سيلز sales line number whatsapp mail alias",
  "/tasks": "تاسك مهام شغل جديد task tasks jobs new",
  "/team": "فريق مترجمين متاح مشغول اونلاين team status online busy",
  "/announce": "اشعار تنبيه للكل الموظفين اعلان رسالة announce notify everyone broadcast",
  "/lead": "تاسكاتي مهامي مراجعة my tasks review",
  "/lead/translators": "مترجمين متاحين فريقي translators",
  "/translator": "شغلي تاسكاتي مهامي my work tasks",
  "/clients": "عملاء اكواد كود عميل clients codes",
  "/admin/clients": "بيانات العملاء ارقام اسماء تليفون عميل جديد client records",
  "/hr/recruitment": "توظيف تعيين مرشحين لوحة recruitment hiring board",
  "/hr/vacancies": "وظايف وظائف شاغرة اعلان vacancies jobs openings",
  "/hr/candidates": "مرشحين متقدمين cv سيرة ذاتية مقابلة candidates applicants interview",
  "/reviewer/tests": "اختبارات المرشحين تصحيح candidate tests",
  "/hr/questions": "بنك الاسئلة اسئلة البوت question bank",
  "/hr/approvals": "موافقات التعيين موافقة approvals",
  "/hr/recruitment/settings": "اعدادات التوظيف البوت رقم التوظيف recruitment settings",
  "/hr/employees": "موظفين ملفات الموظفين مستخدمين حسابات يوزر باسورد صلاحيات ادوار شيفتات موظف جديد employees staff files users accounts roles",
  "/hr/shifts": "شيفتات شيفت مواعيد الشغل اضافة تعديل حذف shifts hours",
  "/hr/probation": "فترة الاختبار تثبيت probation",
  "/hr/performance": "اداء تقييم الاداء performance review",
  "/hr/complaints": "شكاوى شكوى عملاء complaints",
  "/hr/salary-requests": "طلبات تغيير الراتب زيادة مرتب salary change raise",
  "/hr/salary-plans": "خطط الرواتب مرتبات تارجت salary plans",
  "/hr/attendance": "حضور انصراف غياب بصمة لوحة الحضور attendance",
  "/hr/schedules": "جداول شيفتات شيفت مواعيد schedules shifts",
  "/hr/leave": "اجازات اجازة طلبات الاجازة اذن leave vacation",
  "/hr/overtime": "اوفرتايم ساعات اضافية overtime",
  "/hr/report": "تقرير شهري تقرير الحضور monthly report",
  "/hr/offices": "مكاتب مواقع لوكيشن عنوان offices locations",
  "/hr/devices": "اجهزة موبايلات اجهزة الحضور devices",
  "/accounts": "مرتبات رواتب كشف الشهر حسابات payroll salaries",
  "/accounts/attendance": "حضور وانتاج كلمات انتاج attendance output production",
  "/accounts/violations": "مخالفات خصومات جزاءات خصم violations deductions",
  "/accounts/rules": "قواعد الحساب قواعد المرتبات payroll rules",
  "/admin": "نظرة عامة احصائيات داشبورد overview dashboard stats",
  "/admin/settings": "اعدادات settings",
  "/admin/simulate": "محاكاة تجربة رسالة تجريبية simulate test",
  "/admin/audit": "سجل النشاط لوج مين عمل ايه audit log history",
  "/attendance": "حضوري بصمتي تسجيل حضور my attendance check in",
  "/leave": "اجازاتي طلب اجازة my leave",
  "/payroll": "مستحقاتي فلوسي مرتبي my payroll",
  "/notifications": "تنبيهات اشعارات notifications",
  "/admin/reset-tasks": "ريستارت مسح كل التاسكات ابدأ من الاول ترقيم reset delete all tasks",
  "/admin/reset-staff": "ريستارت مسح كل الموظفين ابدأ ببيانات حقيقية بيانات تجريبية reset delete all staff employees",
  "/admin/reset-mail": "مسح الميلات الايميلات البريد الوارد الصادر حذف delete all mail emails inbox",
};

/** A section inside a page, reachable from the search. It is shown only when the page is a line of this person's menu. */
export interface Spot {
  /** The page's address (its menu line is the gate) and the id inside it to land on. */
  path: string;
  anchor: string;
  label: [string, string];
  keywords: string;
}

/**
 * The anchors are the ids the pages draw: `s-<section>` on the settings page, `settings-<field>` on a field of it,
 * `r-<section>` on the payroll rules, `rec-…` on the recruitment settings. A test holds them to the sections the server sends.
 */
export const SPOTS: Spot[] = [
  // -- the settings page
  {
    path: "/admin/settings",
    anchor: "s-ai",
    label: ["مراجعة الترجمة بالـ AI", "AI translation check"],
    keywords: "ذكاء اصطناعي ai claude كلود مفتاح api key موديل model تشيك مراجعة",
  },
  {
    path: "/admin/settings",
    anchor: "s-workflow",
    label: ["قواعد الشغل", "Workflow rules"],
    keywords:
      "مهلة تأكيد الاستلام ثواني تحذير الديدلاين خصم عدم الرد تقييم نجوم سرعة التحديث response window penalty rating polling",
  },
  {
    path: "/admin/settings",
    anchor: "settings-rate_keywords",
    label: ["كلمات الحظر (بتخفي الرسالة عن الأوبريشن)", "Blocked keywords (hide from Operation)"],
    keywords: "حظر كلمات محظورة ممنوعة مخفية اخفاء ريت سعر اسعار فلوس rate price blocked keywords hide",
  },
  {
    path: "/admin/settings",
    anchor: "settings-group_creator_roles",
    label: ["مين يقدر يعمل جروب مع عميل", "Who can open a client group"],
    keywords: "جروب عميل صلاحية انشاء group permission",
  },
  {
    path: "/admin/settings",
    anchor: "s-whatsapp",
    label: ["إعدادات واتساب", "WhatsApp settings"],
    keywords: "واتساب توكن رقم ويب هوك webhook token phone number id verify app secret api version اختبار ربط",
  },
  {
    path: "/admin/settings",
    anchor: "s-email",
    label: ["إعدادات الإيميل", "Email settings"],
    keywords: "ايميل بريد جيميل imap smtp gmail باسورد سيرفر email mail server",
  },
  // -- the payroll rules
  { path: "/accounts/rules", anchor: "r-month", label: ["الشهر واليوم", "The month and the day"], keywords: "ايام الشغل ساعات اليوم بداية الشهر working days hours" },
  { path: "/accounts/rules", anchor: "r-deductions", label: ["الخصومات", "Deductions"], keywords: "خصم خصومات تأخير غياب جزاء deductions penalties" },
  { path: "/accounts/rules", anchor: "r-bonuses", label: ["المكافآت", "Bonuses"], keywords: "بونص مكافاة مكافأة حافز انضباط تارجت bonus incentive target" },
  { path: "/accounts/rules", anchor: "r-attendance", label: ["قواعد الحضور والانصراف", "Attendance rules"], keywords: "تأخير سماحية بصمة حضور انصراف late grace attendance" },
  { path: "/accounts/rules", anchor: "r-overtime", label: ["قواعد الأوفرتايم", "Overtime rules"], keywords: "اوفرتايم ساعات اضافية overtime" },
  { path: "/accounts/rules", anchor: "r-alerts", label: ["تنبيهات الحضور", "Attendance alerts"], keywords: "تنبيهات اشعارات alerts" },
  {
    path: "/accounts/rules",
    anchor: "r-leave",
    label: ["قواعد الإجازات والأذونات", "Leave and permission rules"],
    keywords: "اجازة اذن موافقة سلسلة الموافقة leave permission approval chain",
  },
  { path: "/accounts/rules", anchor: "r-performance", label: ["أوزان تقييم الأداء", "Performance weights"], keywords: "اوزان تقييم اداء performance weights" },
  {
    path: "/accounts/rules",
    anchor: "r-bands",
    label: ["شرائح بونص الإنتاج اليومي", "Daily production bonus bands"],
    keywords: "شرايح شرائح انتاج كلمات يومي بونص production bands words",
  },
  // -- the recruitment settings
  {
    path: "/hr/recruitment/settings",
    anchor: "rec-identity",
    label: ["إخفاء هوية الشركة وبوت التوظيف", "The identity rule and the recruitment bot"],
    keywords: "اخفاء اسم الشركة هوية identity hide company بوت رسايل البوت ترحيب bot",
  },
  {
    path: "/hr/recruitment/settings",
    anchor: "rec-line",
    label: ["رقم واتساب التوظيف", "The recruitment line"],
    keywords: "رقم التوظيف واتساب phone number recruitment line",
  },
];

/** Words that say nothing about what is wanted ("عايز اروح لـ", "how do i"), left out of the match. */
const FILLER =
  ("عايز عاوز عايزه انا اروح روح فين ازاي ايه اعمل اشوف شوف افتح" +
    " احدث حدث تحديث اعدل عدل تعديل اغير غير تغيير صفحه صفحة بتاعت بتاع في من على عن" +
    " لل ال و يا i want to go open the page change update edit set how where a of").split(" ");

/** Arabic spelled any of the usual ways reads the same: no marks, one alef, ة as ه, ى as ي, hamza carriers plain. */
export function normAr(text: string): string {
  return String(text || "")
    .toLowerCase()
    .replace(/[ً-ْـ]/g, "")
    .replace(/[أإآ]/g, "ا")
    .replace(/ة/g, "ه")
    .replace(/ى/g, "ي")
    .replace(/ؤ/g, "و")
    .replace(/ئ/g, "ي")
    .replace(/\s+/g, " ")
    .trim();
}

const FILLER_NORMAL = new Set(FILLER.map(normAr));

interface Token {
  full: string;
  bare: string;
}

/** The words to look for. "الحظر" finds "حظر": the word without its article is tried too. */
export function searchTokens(query: string): Token[] {
  return normAr(query)
    .split(" ")
    .filter((word) => word && !FILLER_NORMAL.has(word))
    .map((word) => ({ full: word, bare: word.length > 4 && word.startsWith("ال") ? word.slice(2) : word }));
}

interface Prepared {
  row: SearchRow;
  name: string;
  rest: string;
}

/** The words a row is looked up by, normalised once (not on every keystroke). */
function prepare(row: SearchRow): Prepared {
  return {
    row,
    name: normAr(`${row.label[0]} ${row.label[1]}`),
    rest: normAr(`${row.keywords} ${row.where[0]} ${row.where[1]}`),
  };
}

function score(entry: Prepared, tokens: Token[]): number {
  let total = 0;
  let hits = 0;
  for (const token of tokens) {
    const inName = entry.name.includes(token.full) || entry.name.includes(token.bare);
    const inRest = entry.rest.includes(token.full) || entry.rest.includes(token.bare);
    if (inName) {
      total += 3;
      hits += 1;
    } else if (inRest) {
      total += 2;
      hits += 1;
    }
  }
  if (!hits) return 0;
  // Every word typed found in one place beats a scatter of partials.
  if (hits === tokens.length) total += 4;
  // A section inside a page is the more exact answer when both match.
  if (entry.row.hash) total += 1;
  return total;
}

/**
 * Everything the search can find for these menu lines: the pages first, then the sections inside them. Built from the
 * lines, so a page this person has no line for is not here, and neither are its sections.
 */
export function buildIndex(lines: SearchLine[]): SearchRow[] {
  const rows: SearchRow[] = [];
  const pages = new Map<string, SearchLine>();
  for (const line of lines) {
    if (pages.has(line.path)) continue;
    pages.set(line.path, line);
    rows.push({ path: line.path, hash: "", icon: line.icon, label: line.label, where: line.where, keywords: KEYWORDS[line.path] ?? "" });
  }
  for (const spot of SPOTS) {
    const page = pages.get(spot.path);
    if (!page) continue;
    // A section's "where" is the page it is in, the way the classic menu names it.
    rows.push({ path: spot.path, hash: spot.anchor, icon: page.icon, label: spot.label, where: page.label, keywords: spot.keywords });
  }
  return rows;
}

/** The index, prepared once: what `searchPages` is asked about on every keystroke. */
export function prepareIndex(rows: SearchRow[]): Prepared[] {
  return rows.map(prepare);
}

/** The best matches for what was typed, the closest first. Nothing typed, or only filler, finds nothing. */
export function searchPages(index: Prepared[], query: string, limit = 8): SearchRow[] {
  const tokens = searchTokens(query);
  if (!tokens.length) return [];
  return index
    .map((entry) => ({ row: entry.row, points: score(entry, tokens) }))
    .filter((hit) => hit.points > 0)
    .sort((a, b) => b.points - a.points)
    .slice(0, limit)
    .map((hit) => hit.row);
}

export type { Prepared };
