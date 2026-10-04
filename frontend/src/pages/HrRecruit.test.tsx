import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  DayStatusJson,
  HrCandidateRow,
  HrQuestions,
  HrRecruitSettings,
  HrRecruitment,
  HrVacancies,
  HrVacancy,
  Role,
} from "../api/types";
import { jsonResponse } from "../test/helpers";
import { field, fireValue, openHr as open, reads, serveHr, stampOf, type Handler } from "../test/hr";

afterEach(() => vi.unstubAllGlobals());

const serve = (who: Role, routes: Record<string, Handler>) => serveHr(who, routes);

const newStatus: DayStatusJson = { value: "new", tone: "info", ar: "جديد", en: "New" };
const owner: DayStatusJson = { value: "owner_approval", tone: "wait", ar: "مستني المالك", en: "Owner approval" };
const opened: DayStatusJson = { value: "open", tone: "ok", ar: "مفتوحة", en: "Open" };
const draft: DayStatusJson = { value: "draft", tone: "wait", ar: "مسودة", en: "Draft" };
const closed: DayStatusJson = { value: "closed", tone: "dead", ar: "مقفولة", en: "Closed" };
const whatsapp = { value: "whatsapp", ar: "واتساب", en: "WhatsApp" };
const text = { value: "text", ar: "نص", en: "Text" };

function candidate(over: Partial<HrCandidateRow> = {}): HrCandidateRow {
  return {
    code: "CAN-0007",
    name: "Sara",
    vacancy: "مترجم عربي",
    vacancy_code: "VAC-0001",
    phone: "01000000000",
    source: whatsapp,
    status: newStatus,
    applied_on: "2026-10-01",
    anonymous: true,
    shift: "",
    ...over,
  };
}

function board(over: Partial<HrRecruitment> = {}): HrRecruitment {
  return {
    ok: true,
    counts: { open_vacancies: 2, total_applicants: 9, screening: 3, pending_owner: 1, interviews_today: 2, pending_tests: 4, hired: 5, on_probation: 6 },
    recent: [candidate(), candidate({ code: "CAN-0008", name: "Omar", vacancy: null, vacancy_code: null })],
    today_interviews: [{ candidate: { code: "CAN-0007", name: "Sara" }, kind: { value: "online", ar: "أونلاين", en: "Online" }, at: stampOf("3:00 م", "3:00 PM") }],
    waiting_owner: [candidate({ code: "CAN-0009", name: "Laila", status: owner })],
    privacy_armed: true,
    bot_enabled: true,
    recruit_number: "+20 100 000 0000",
    can: { approve: false },
    ...over,
  };
}

describe("HrRecruitmentPage", () => {
  const page = (data: HrRecruitment = board()) => ({ "/api/v1/hr/recruitment/": () => jsonResponse(data) });

  it("draws the counts, the latest applicants with a link to each file, today's interviews and who waits for the owner", async () => {
    serve("hr", page());
    const { container } = open("/hr/recruitment");
    await screen.findByText("لوحة التوظيف", { selector: "h1" });
    expect(Array.from(container.querySelectorAll(".kpi")).map((one) => one.textContent)).toEqual([
      "وظايف مفتوحة2",
      "إجمالي المتقدمين9",
      "في الفرز3",
      "مستني المالك1",
      "مقابلات النهارده2",
      "اختبارات معلقة4",
      "اتعيّنوا5",
      "تحت الاختبار6",
    ]);
    const first = container.querySelector('[data-candidate="CAN-0007"]') as HTMLElement;
    expect(within(first).getByRole("link", { name: "CAN-0007" })).toHaveAttribute("href", "/hr/candidates/CAN-0007");
    expect(first).toHaveTextContent("Sara");
    expect(first).toHaveTextContent("مترجم عربي");
    expect(within(first).getByText("جديد")).toHaveClass("badge--info");
    expect(container.querySelector('[data-candidate="CAN-0008"]')).toHaveTextContent("—");
    expect(container.querySelector('[data-card="today"]')).toHaveTextContent("3:00 م");
    expect(container.querySelector('[data-card="owner"]')).toHaveTextContent("Laila");
  });

  it("offers the owner's queue only to whoever may decide", async () => {
    serve("hr", page());
    const view = open("/hr/recruitment");
    await screen.findByText("لوحة التوظيف", { selector: "h1" });
    expect(screen.queryByRole("link", { name: /افتح الطابور/ })).toBeNull();
    view.unmount();
    serve("admin", page(board({ can: { approve: true } })));
    open("/hr/recruitment");
    expect(await screen.findByRole("link", { name: /افتح الطابور/ })).toHaveAttribute("href", "/hr/approvals");
  });

  it("says out loud when nothing is configured to be scrubbed from what a candidate reads, and stays quiet when it is", async () => {
    serve("hr", page(board({ privacy_armed: false })));
    const view = open("/hr/recruitment");
    await screen.findByText("لوحة التوظيف", { selector: "h1" });
    const note = view.container.querySelector('[data-note="privacy"]') as HTMLElement;
    expect(note).toHaveTextContent("قاعدة إخفاء الهوية مش مفعّلة");
    expect(within(note).getByRole("link", { name: "إعدادات التوظيف" })).toHaveAttribute("href", "/hr/recruitment/settings");
    view.unmount();
    serve("hr", page());
    const again = open("/hr/recruitment");
    await screen.findByText("لوحة التوظيف", { selector: "h1" });
    expect(again.container.querySelector('[data-note="privacy"]')).toBeNull();
  });

  it("says the bot hears nothing when there is no recruitment number, or that it is switched off", async () => {
    serve("hr", page(board({ recruit_number: "" })));
    const view = open("/hr/recruitment");
    expect(await screen.findByText("رقم التوظيف لسه مش متسجل — البوت مش هيستقبل حاجة.")).toBeInTheDocument();
    view.unmount();
    serve("hr", page(board({ bot_enabled: false })));
    open("/hr/recruitment");
    expect(await screen.findByText("البوت مقفول من الإعدادات.")).toBeInTheDocument();
  });

  it("says when nobody has applied", async () => {
    serve("hr", page(board({ recent: [], waiting_owner: [], today_interviews: [] })));
    open("/hr/recruitment");
    expect(await screen.findByText("مفيش متقدمين لسه.")).toBeInTheDocument();
    expect(screen.getByText("مفيش مقابلات النهارده.")).toBeInTheDocument();
    expect(screen.getByText("مفيش حاجة مستنية.")).toBeInTheDocument();
  });

  it("is HR's and the admin's: anyone else is sent home and nothing is asked", async () => {
    const served = serve("translator", page());
    open("/hr/recruitment");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/"))).toBe(false);
  });
});

const vacancyForm = [
  field("title", "المسمى الوظيفي", { required: true }),
  field("openings", "عدد الشواغر", { kind: "number", value: 1 }),
  field("deadline_days", "الإعلان يقفل بعد (يوم)", { kind: "number", ltr: true }),
];

function vacancies(over: Partial<HrVacancies> = {}): HrVacancies {
  return {
    ok: true,
    rows: [
      { code: "VAC-0001", title: "مترجم عربي", department: "اللغويات", work_mode: { value: "office", ar: "من المكتب", en: "Office" }, applicants: 4, status: opened },
      { code: "VAC-0002", title: "مراجع", department: null, work_mode: { value: "remote", ar: "عن بعد", en: "Remote" }, applicants: 0, status: draft },
    ],
    statuses: [draft, opened, closed],
    form: vacancyForm,
    ...over,
  };
}

describe("HrVacanciesPage", () => {
  const page = (data: HrVacancies = vacancies()) => ({ "/api/v1/hr/vacancies/": () => jsonResponse(data) });

  it("lists every vacancy with how many applied and where it stands", async () => {
    serve("hr", page());
    const { container } = open("/hr/vacancies");
    await screen.findByText("الوظائف المسجلة");
    const first = container.querySelector('[data-vacancy="VAC-0001"]') as HTMLElement;
    expect(within(first).getByRole("link", { name: "VAC-0001" })).toHaveAttribute("href", "/hr/vacancies/VAC-0001");
    expect(first).toHaveTextContent("اللغويات");
    expect(first).toHaveTextContent("من المكتب");
    expect(first).toHaveTextContent("4");
    expect(within(first).getByText("مفتوحة", { selector: ".badge" })).toHaveClass("badge--ok");
    const second = container.querySelector('[data-vacancy="VAC-0002"]') as HTMLElement;
    expect(second).toHaveTextContent("—");
    expect(within(second).getByText("مسودة", { selector: ".badge" })).toHaveClass("badge--wait");
  });

  it("filters by status through the address", async () => {
    const served = serve("hr", page());
    const user = userEvent.setup();
    open("/hr/vacancies");
    await screen.findByText("الوظائف المسجلة");
    expect(reads(served, "/api/v1/hr/vacancies/")[0]).toBe("/api/v1/hr/vacancies/");
    await user.selectOptions(screen.getByLabelText("الحالة"), "closed");
    await waitFor(() => expect(reads(served, "/api/v1/hr/vacancies/").some((url) => url.includes("status=closed"))).toBe(true));
    expect(screen.getByTestId("where")).toHaveTextContent("/hr/vacancies?status=closed");
  });

  it("adds a vacancy with only what was written and goes on to its questions", async () => {
    const served = serve("hr", {
      ...page(),
      "/api/v1/hr/vacancies/create/": (url, init) => served.record(url, init, { ok: true, code: "VAC-0003" }),
      "/api/v1/hr/vacancies/VAC-0003/": () => jsonResponse(vacancy()),
    });
    const user = userEvent.setup();
    open("/hr/vacancies");
    await screen.findByText("وظيفة جديدة", { selector: "h3" });
    const save = screen.getByRole("button", { name: "احفظ" });
    expect(save).toBeDisabled();
    await user.type(screen.getByLabelText("المسمى الوظيفي"), "محرر");
    await user.type(screen.getByLabelText("الإعلان يقفل بعد (يوم)"), "30");
    await user.click(save);
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/vacancies/create/")).toBe(true));
    expect(served.sent[0]!.body).toEqual({ values: { title: "محرر", deadline_days: "30" } });
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(/^\/hr\/vacancies\/VAC-0003$/));
  });

  it("shows the form's refusal beside its box and stays on the page", async () => {
    serve("hr", {
      ...page(),
      "/api/v1/hr/vacancies/create/": () => jsonResponse({ ok: false, error: "invalid", errors: { title: ["This field is required."] } }, 400),
    });
    const user = userEvent.setup();
    open("/hr/vacancies");
    await screen.findByText("وظيفة جديدة", { selector: "h3" });
    await user.type(screen.getByLabelText("عدد الشواغر"), "2");
    await user.click(screen.getByRole("button", { name: "احفظ" }));
    expect(await screen.findByText("This field is required.")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/hr\/vacancies$/);
  });

  it("is HR's and the admin's", async () => {
    const served = serve("sales", page());
    open("/hr/vacancies");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/"))).toBe(false);
  });
});

function vacancy(over: Partial<HrVacancy> = {}): HrVacancy {
  return {
    ok: true,
    vacancy: { code: "VAC-0001", title: "مترجم عربي", status: opened, applicants: 4, deadline: null },
    form: vacancyForm.map((one) => (one.name === "title" ? { ...one, value: "مترجم عربي" } : one)),
    links: [
      { id: 11, order: 1, required: true, question: { id: 1, text: "اسمك إيه؟", kind: text, maps_to: { value: "full_name", ar: "اسم المرشح", en: "Candidate name" } } },
      { id: 12, order: 2, required: false, question: { id: 2, text: "عندك خبرة؟", kind: text, maps_to: null } },
    ],
    pool: [
      { id: 5, department: "اللغويات", text: "بتترجم لأي لغات؟" },
      { id: 6, department: null, text: "مرتبك المتوقع؟" },
    ],
    candidates: [candidate()],
    ...over,
  };
}

describe("HrVacancyPage", () => {
  const page = (data: HrVacancy = vacancy()) => ({ "/api/v1/hr/vacancies/VAC-0001/": () => jsonResponse(data) });

  it("shows the questions the bot will ask in the order given, and who applied", async () => {
    serve("hr", page());
    const { container } = open("/hr/vacancies/VAC-0001");
    await screen.findByText("أسئلة البوت للوظيفة دي");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("مترجم عربي");
    const first = container.querySelector('[data-link="11"]') as HTMLElement;
    expect(first).toHaveTextContent("اسمك إيه؟");
    expect(first).toHaveTextContent("اسم المرشح");
    expect(within(first).getByLabelText("الترتيب")).toHaveValue(1);
    expect(within(first).getByLabelText("إجباري")).toBeChecked();
    expect(within(container.querySelector('[data-link="12"]') as HTMLElement).getByLabelText("إجباري")).not.toBeChecked();
    expect(container.querySelector('[data-candidate="CAN-0007"]')).toHaveTextContent("Sara");
  });

  it("warns that the bot will only ask about the shift when no question is chosen", async () => {
    serve("hr", page(vacancy({ links: [] })));
    const { container } = open("/hr/vacancies/VAC-0001");
    await screen.findByText("أسئلة البوت للوظيفة دي");
    expect(container.querySelector('[data-note="no-questions"]')).not.toBeNull();
    expect(screen.queryByRole("button", { name: "احفظ الترتيب" })).toBeNull();
  });

  it("saves the order and the required boxes of all the questions in one go", async () => {
    const served = serve("hr", {
      ...page(),
      "/api/v1/hr/vacancies/VAC-0001/questions/order/": (url, init) => served.record(url, init, { ok: true, saved: 2 }),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/vacancies/VAC-0001");
    await screen.findByText("أسئلة البوت للوظيفة دي");
    fireValue(within(container.querySelector('[data-link="11"]') as HTMLElement).getByLabelText("الترتيب"), "3");
    await user.click(within(container.querySelector('[data-link="12"]') as HTMLElement).getByLabelText("إجباري"));
    await user.click(screen.getByRole("button", { name: "احفظ الترتيب" }));
    await waitFor(() => expect(served.sent.some((post) => post.url.endsWith("/questions/order/"))).toBe(true));
    expect(served.sent[0]!.body).toEqual({
      rows: [
        { id: 11, order: 3, required: true },
        { id: 12, order: 2, required: true },
      ],
    });
  });

  it("adds the chosen question from the bank, the first one when nothing else is picked", async () => {
    const served = serve("hr", {
      ...page(),
      "/api/v1/hr/vacancies/VAC-0001/questions/": (url, init) => served.record(url, init, { ok: true, id: 13, added: true }),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/vacancies/VAC-0001");
    await screen.findByText("ضيف سؤال", { selector: "h3" });
    const add = container.querySelector('[data-card="add"]') as HTMLElement;
    expect(within(add).getByRole("option", { name: "[اللغويات] بتترجم لأي لغات؟" })).toBeInTheDocument();
    expect(within(add).getByRole("option", { name: "[عام] مرتبك المتوقع؟" })).toBeInTheDocument();
    await user.click(within(add).getByRole("button", { name: "ضيف" }));
    await waitFor(() => expect(served.sent.length).toBe(1));
    expect(served.sent[0]).toEqual({ url: "/api/v1/hr/vacancies/VAC-0001/questions/", body: { question: 5 } });
    await user.selectOptions(within(add).getByLabelText("السؤال"), "6");
    await user.click(within(add).getByRole("button", { name: "ضيف" }));
    await waitFor(() => expect(served.sent.length).toBe(2));
    expect(served.sent[1]!.body).toEqual({ question: 6 });
  });

  it("cannot add when the bank has nothing left to offer", async () => {
    serve("hr", page(vacancy({ pool: [] })));
    const { container } = open("/hr/vacancies/VAC-0001");
    await screen.findByText("ضيف سؤال", { selector: "h3" });
    expect(within(container.querySelector('[data-card="add"]') as HTMLElement).getByRole("button", { name: "ضيف" })).toBeDisabled();
  });

  it("takes a question off the vacancy by its link", async () => {
    const served = serve("hr", {
      ...page(),
      "/api/v1/hr/vacancies/questions/12/delete/": (url, init) => served.record(url, init, { ok: true, code: "VAC-0001" }),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/vacancies/VAC-0001");
    await screen.findByText("أسئلة البوت للوظيفة دي");
    await user.click(within(container.querySelector('[data-link="12"]') as HTMLElement).getByRole("button", { name: "شيل السؤال" }));
    await waitFor(() => expect(served.sent.length).toBe(1));
    expect(served.sent[0]!.url).toBe("/api/v1/hr/vacancies/questions/12/delete/");
  });

  it("changes the vacancy with only the box that changed, so a deadline nobody touched is not sent", async () => {
    const served = serve("hr", {
      ...page(),
      "/api/v1/hr/vacancies/VAC-0001/save/": (url, init) => served.record(url, init, { ok: true }),
    });
    const user = userEvent.setup();
    open("/hr/vacancies/VAC-0001");
    await screen.findByText("بيانات الوظيفة");
    expect(screen.getByLabelText("المسمى الوظيفي")).toHaveValue("مترجم عربي");
    const save = screen.getByRole("button", { name: "احفظ" });
    expect(save).toBeDisabled();
    await user.clear(screen.getByLabelText("المسمى الوظيفي"));
    await user.type(screen.getByLabelText("المسمى الوظيفي"), "مترجم أول");
    await user.click(save);
    await waitFor(() => expect(served.sent.some((post) => post.url.endsWith("/save/"))).toBe(true));
    expect(served.sent[0]!.body).toEqual({ values: { title: "مترجم أول" } });
  });

  it("says a vacancy that is not there is not there", async () => {
    serve("hr", { "/api/v1/hr/vacancies/VAC-0001/": () => jsonResponse({ ok: false, error: "not_found" }, 404) });
    open("/hr/vacancies/VAC-0001");
    expect(await screen.findByRole("alert")).toHaveTextContent("الصفحة دي مش موجودة.");
  });
});

function questions(over: Partial<HrQuestions> = {}): HrQuestions {
  return {
    ok: true,
    rows: [
      { id: 1, text: "اسمك إيه؟", options: [], department: null, kind: text, maps_to: { value: "full_name", ar: "اسم المرشح", en: "Candidate name" }, is_active: true },
      { id: 2, text: "بتشتغل شيفت؟", options: ["صباحي", "مسائي"], department: "اللغويات", kind: { value: "choice", ar: "اختيار واحد", en: "One" }, maps_to: null, is_active: false },
    ],
    editing: null,
    form: [field("text", "السؤال بالعربي", { required: true }), field("help_text", "تلميح للمرشح")],
    departments: [
      { id: 3, label: "اللغويات", questions: 1 },
      { id: 4, label: "المراجعة", questions: 0 },
    ],
    department_form: [field("name", "الاسم", { required: true }), field("name_ar", "بالعربي")],
    ...over,
  };
}

describe("HrQuestionsPage", () => {
  const page = (data: HrQuestions = questions()) => ({ "/api/v1/hr/questions/": () => jsonResponse(data) });

  it("lists the bank with each question's type, what it fills and whether it is on", async () => {
    serve("hr", page());
    const { container } = open("/hr/questions");
    await screen.findByText("الأسئلة", { selector: "h3" });
    const first = container.querySelector('[data-question="1"]') as HTMLElement;
    expect(first).toHaveTextContent("عام");
    expect(first).toHaveTextContent("اسم المرشح");
    expect(within(first).getByText("شغال")).toHaveClass("badge--ok");
    const second = container.querySelector('[data-question="2"]') as HTMLElement;
    expect(second).toHaveTextContent("صباحي · مسائي");
    expect(second).toHaveTextContent("اللغويات");
    expect(within(second).getByText("مقفول")).toBeInTheDocument();
    expect(within(second).getByRole("link", { name: /عدّل/ })).toHaveAttribute("href", "/hr/questions?edit=2");
  });

  it("says that a department only helps find a question, and counts each department's questions", async () => {
    serve("hr", page());
    const { container } = open("/hr/questions");
    await screen.findByText("الأسئلة", { selector: "h3" });
    expect(screen.getByText(/مفيش أسئلة مفروضة على أي قسم/)).toBeInTheDocument();
    const departments = container.querySelector('[data-card="departments"]') as HTMLElement;
    expect(departments).toHaveTextContent("اللغويات");
    expect(departments).toHaveTextContent("المراجعة");
  });

  it("narrows by department through the address", async () => {
    const served = serve("hr", page());
    const user = userEvent.setup();
    open("/hr/questions");
    await screen.findByText("الأسئلة", { selector: "h3" });
    await user.selectOptions(screen.getByLabelText("القسم"), "3");
    await waitFor(() => expect(reads(served, "/api/v1/hr/questions/").some((url) => url.includes("department=3"))).toBe(true));
    expect(screen.getByTestId("where")).toHaveTextContent("/hr/questions?department=3");
  });

  it("adds a question with no id, and the form starts clean again", async () => {
    const served = serve("hr", {
      ...page(),
      "/api/v1/hr/questions/save/": (url, init) => served.record(url, init, { ok: true, id: 9 }),
    });
    const user = userEvent.setup();
    open("/hr/questions");
    await screen.findByText("سؤال جديد", { selector: "h3" });
    const save = screen.getAllByRole("button", { name: "احفظ" })[0]!;
    expect(save).toBeDisabled();
    await user.type(screen.getByLabelText("السؤال بالعربي"), "عندك كمبيوتر؟");
    await user.click(save);
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/questions/save/")).toBe(true));
    expect(served.sent[0]!.body).toEqual({ values: { text: "عندك كمبيوتر؟" } });
    await waitFor(() => expect(screen.getByLabelText("السؤال بالعربي")).toHaveValue(""));
  });

  it("changes a question by id with only what changed, and goes back to the bank", async () => {
    const served = serve("hr", {
      "/api/v1/hr/questions/": (url) =>
        jsonResponse(
          url.searchParams.get("edit") === "1"
            ? questions({ editing: 1, form: questions().form.map((one) => (one.name === "text" ? { ...one, value: "اسمك إيه؟" } : one)) })
            : questions(),
        ),
      "/api/v1/hr/questions/save/": (url, init) => served.record(url, init, { ok: true, id: 1 }),
    });
    const user = userEvent.setup();
    open("/hr/questions?edit=1");
    await screen.findByText("تعديل سؤال");
    expect(screen.getByLabelText("السؤال بالعربي")).toHaveValue("اسمك إيه؟");
    await user.type(screen.getByLabelText("تلميح للمرشح"), "اكتب اسمك كامل");
    await user.click(screen.getAllByRole("button", { name: "احفظ" })[0]!);
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/questions/save/")).toBe(true));
    expect(served.sent[0]!.body).toEqual({ id: 1, values: { help_text: "اكتب اسمك كامل" } });
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(/^\/hr\/questions$/));
  });

  it("adds a department from its own small form", async () => {
    const served = serve("hr", {
      ...page(),
      "/api/v1/hr/departments/": (url, init) => served.record(url, init, { ok: true, id: 8 }),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/questions");
    await screen.findByText("الأقسام", { selector: "h3" });
    const card = container.querySelector('[data-card="departments"]') as HTMLElement;
    await user.type(within(card).getByLabelText("الاسم"), "Editing");
    await user.click(within(card).getByRole("button", { name: "ضيف قسم" }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/hr/departments/")).toBe(true));
    expect(served.sent[0]!.body).toEqual({ values: { name: "Editing" } });
  });

  it("shows the form's refusal beside its box", async () => {
    serve("hr", {
      ...page(),
      "/api/v1/hr/questions/save/": () => jsonResponse({ ok: false, error: "invalid", errors: { text: ["This field is required."] } }, 400),
    });
    const user = userEvent.setup();
    open("/hr/questions");
    await screen.findByText("سؤال جديد", { selector: "h3" });
    await user.type(screen.getByLabelText("تلميح للمرشح"), "x");
    await user.click(screen.getAllByRole("button", { name: "احفظ" })[0]!);
    expect(await screen.findByText("This field is required.")).toBeInTheDocument();
  });

  it("is HR's and the admin's", async () => {
    const served = serve("reviewer", page());
    open("/hr/questions");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/"))).toBe(false);
  });
});

function recruitSettings(over: Partial<HrRecruitSettings> = {}): HrRecruitSettings {
  return {
    ok: true,
    form: [field("redact_terms", "الكلمات (واحدة في كل سطر)", { kind: "textarea", value: "Acme" }), field("probation_days", "مدة فترة الاختبار (يوم)", { kind: "number", value: 90 })],
    privacy_armed: true,
    sample: "مرحبًا من [الشركة]",
    line: { number: "+20 100 000 0000", phone_number_id: true },
    ...over,
  };
}

describe("HrRecruitmentSettingsPage", () => {
  const page = (data: HrRecruitSettings = recruitSettings()) => ({ "/api/v1/hr/recruitment/settings/": () => jsonResponse(data) });

  it("shows what the filter makes of a message that names the company, beside the list that drives it", async () => {
    serve("hr", page());
    const { container } = open("/hr/recruitment/settings");
    await screen.findByText("إعدادات التوظيف", { selector: "h1" });
    expect(container.querySelector('[data-note="sample"]')).toHaveTextContent("مرحبًا من [الشركة]");
    expect(container.querySelector('[data-note="privacy"]')).toBeNull();
    expect(screen.getByLabelText("الكلمات (واحدة في كل سطر)")).toHaveValue("Acme");
  });

  it("warns, and shows no sample, when nothing is configured to redact", async () => {
    serve("hr", page(recruitSettings({ privacy_armed: false, sample: "", form: recruitSettings().form.map((one) => (one.name === "redact_terms" ? { ...one, value: "" } : one)) })));
    const { container } = open("/hr/recruitment/settings");
    await screen.findByText("إعدادات التوظيف", { selector: "h1" });
    expect(container.querySelector('[data-note="privacy"]')).not.toBeNull();
    expect(container.querySelector('[data-note="sample"]')).toBeNull();
  });

  it("shows the recruitment line, and what is missing when its ID is not set", async () => {
    serve("hr", page(recruitSettings({ line: { number: "", phone_number_id: false } })));
    const { container } = open("/hr/recruitment/settings");
    await screen.findByText("رقم التوظيف", { selector: "h3" });
    const card = container.querySelector('[data-card="line"]') as HTMLElement;
    expect(card).toHaveTextContent("—");
    expect(container.querySelector('[data-note="no-id"]')).toHaveTextContent("الأدمن بيحطه من الإعدادات.");
  });

  it("points the admin to the settings page for the missing ID", async () => {
    serve("admin", page(recruitSettings({ line: { number: "", phone_number_id: false } })));
    const { container } = open("/hr/recruitment/settings");
    await screen.findByText("رقم التوظيف", { selector: "h3" });
    expect(within(container.querySelector('[data-note="no-id"]') as HTMLElement).getByRole("link")).toHaveAttribute("href", "/admin/settings");
  });

  it("saves only the box that changed", async () => {
    const served = serve("hr", {
      ...page(),
      "/api/v1/hr/recruitment/settings/save/": (url, init) => served.record(url, init, recruitSettings()),
    });
    const user = userEvent.setup();
    open("/hr/recruitment/settings");
    await screen.findByText("إعدادات التوظيف", { selector: "h1" });
    const save = screen.getByRole("button", { name: "احفظ" });
    expect(save).toBeDisabled();
    await user.clear(screen.getByLabelText("مدة فترة الاختبار (يوم)"));
    await user.type(screen.getByLabelText("مدة فترة الاختبار (يوم)"), "60");
    await user.click(save);
    await waitFor(() => expect(served.sent.some((post) => post.url.endsWith("/settings/save/"))).toBe(true));
    expect(served.sent[0]!.body).toEqual({ values: { probation_days: "60" } });
  });

  it("is HR's and the admin's", async () => {
    const served = serve("accounting", page());
    open("/hr/recruitment/settings");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/"))).toBe(false);
  });
});
