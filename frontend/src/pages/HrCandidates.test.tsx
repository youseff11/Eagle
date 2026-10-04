import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  DayStatusJson,
  HrApprovals,
  HrCandidate,
  HrCandidateRow,
  HrCandidates,
  HrHire,
  HrInterview,
  ReviewerQueue,
  ReviewerTest,
  Role,
} from "../api/types";
import { jsonResponse } from "../test/helpers";
import { field, fireValue, openHr as open, reads, serveHr, stampOf, type Handler } from "../test/hr";

afterEach(() => vi.unstubAllGlobals());

const serve = (who: Role, routes: Record<string, Handler>) => serveHr(who, routes);

const badge = (value: string, tone: string, ar: string, en: string): DayStatusJson => ({ value, tone, ar, en });
const screening = badge("screening", "wait", "فرز", "Screening");
const newcomer = badge("new", "new", "جديد", "New");
const waitingOwner = badge("owner_approval", "wait", "مستني المالك", "Owner approval");
const approved = badge("approved", "ok", "متوافق عليه", "Approved");
const rejected = badge("rejected", "dead", "مرفوض", "Rejected");
const whatsapp = { value: "whatsapp", ar: "واتساب", en: "WhatsApp" };
const online = { value: "online", ar: "أونلاين", en: "Online" };

function row(over: Partial<HrCandidateRow> = {}): HrCandidateRow {
  return {
    code: "CAN-0007",
    name: "Sara",
    vacancy: "مترجم عربي",
    vacancy_code: "VAC-0001",
    phone: "01000000000",
    source: whatsapp,
    status: screening,
    applied_on: "2026-10-01",
    anonymous: true,
    shift: "",
    ...over,
  };
}

function list(over: Partial<HrCandidates> = {}): HrCandidates {
  return {
    ok: true,
    rows: [row(), row({ code: "CAN-0008", name: "Omar", vacancy: null, vacancy_code: null, phone: "", status: newcomer })],
    total: 2,
    limit: 300,
    counts: {},
    statuses: [newcomer, screening, waitingOwner],
    sources: [whatsapp, { value: "referral", ar: "ترشيح", en: "Referral" }],
    vacancies: [{ code: "VAC-0001", title: "مترجم عربي" }],
    ...over,
  };
}

describe("HrCandidatesPage", () => {
  const page = (data: HrCandidates = list()) => ({ "/api/v1/hr/candidates/": () => jsonResponse(data) });

  it("lists everybody with the code that opens the file and the phone", async () => {
    serve("hr", page());
    const { container } = open("/hr/candidates");
    await screen.findByText("المرشحين", { selector: "h1" });
    const first = container.querySelector('[data-candidate="CAN-0007"]') as HTMLElement;
    expect(within(first).getByRole("link", { name: "CAN-0007" })).toHaveAttribute("href", "/hr/candidates/CAN-0007");
    expect(first).toHaveTextContent("01000000000");
    expect(first).toHaveTextContent("مترجم عربي");
    expect(container.querySelector('[data-candidate="CAN-0008"]')).toHaveTextContent("—");
  });

  it("filters through the address and forwards only the filters it knows", async () => {
    const served = serve("hr", page());
    const user = userEvent.setup();
    open("/hr/candidates?evil=1");
    await screen.findByText("المرشحين", { selector: "h1" });
    expect(reads(served, "/api/v1/hr/candidates/")[0]).toBe("/api/v1/hr/candidates/");
    await user.selectOptions(screen.getByLabelText("الحالة"), "screening");
    await user.selectOptions(screen.getByLabelText("المصدر"), "referral");
    await user.selectOptions(screen.getByLabelText("الوظيفة"), "VAC-0001");
    await waitFor(() => expect(reads(served, "/api/v1/hr/candidates/").some((url) => url.includes("status=screening") && url.includes("source=referral") && url.includes("vacancy=VAC-0001"))).toBe(true));
    expect(reads(served, "/api/v1/hr/candidates/").every((url) => !url.includes("evil"))).toBe(true);
  });

  it("searches when the form is sent and keeps what was typed", async () => {
    const served = serve("hr", page());
    const user = userEvent.setup();
    open("/hr/candidates");
    await screen.findByText("المرشحين", { selector: "h1" });
    await user.type(screen.getByLabelText("بحث"), "mona{enter}");
    await waitFor(() => expect(reads(served, "/api/v1/hr/candidates/").some((url) => url.includes("q=mona"))).toBe(true));
    expect(screen.getByTestId("where")).toHaveTextContent("/hr/candidates?q=mona");
  });

  it("says how many it shows out of how many there are", async () => {
    serve("hr", page(list({ total: 450, limit: 300 })));
    const { container } = open("/hr/candidates");
    await screen.findByText("المرشحين", { selector: "h1" });
    expect(container.querySelector('[data-note="limit"]')).toHaveTextContent("450");
    expect(container.querySelector(".page-head .chip")).toHaveTextContent("2 / 450");
  });

  it("says when nobody matches", async () => {
    serve("hr", page(list({ rows: [], total: 0 })));
    open("/hr/candidates");
    expect(await screen.findByText("مفيش مرشحين بالشروط دي.")).toBeInTheDocument();
  });

  it("is HR's and the admin's", async () => {
    const served = serve("sales", page());
    open("/hr/candidates");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/"))).toBe(false);
  });
});

const file = { url: "/files/recruitment/cv/2026/10/abc.pdf", name: "Sara CV.pdf" };

function candidate(over: Partial<HrCandidate> = {}, who: Partial<HrCandidate["candidate"]> = {}): HrCandidate {
  return {
    ok: true,
    candidate: {
      ...row(),
      email: "sara@example.com",
      department: "الترجمة",
      experience_years: "3",
      languages: "AR, EN",
      skills: "",
      expected_salary: "6000",
      hr_notes: "",
      hr_recommendation: "",
      rejection_reason: "",
      cv: file,
      identity: { revealed: false, at: null, by: null },
      owner_decision: null,
      hired_user: null,
      ...who,
    },
    form: [field("full_name", "الاسم", { value: "Sara" }), field("hr_notes", "ملاحظات HR", { kind: "textarea" })],
    answers: [{ order: 1, question: "اسمك إيه؟", value: "Sara", file: null, at: stampOf("10-01 3:00 م", "10-01 3:00 PM") }],
    interviews: [
      { id: 21, at: stampOf("2026-10-05 3:00 م", "2026-10-05 3:00 PM"), kind: online, interviewer: "Mona", meeting_link: "", location: "", notes: "", evaluated: true, marks: {}, total: 41, max: 50, comments: "" },
      { id: 22, at: stampOf("2026-10-06 1:00 م", "2026-10-06 1:00 PM"), kind: online, interviewer: null, meeting_link: "", location: "", notes: "", evaluated: false, marks: {}, total: 0, max: 50, comments: "" },
    ],
    tests: [
      { id: 31, title: "Sample test", department: null, brief: "", language_pair: "EN-AR", word_count: 300, assignment: { url: "/files/recruitment/tests/x.docx", name: "test.docx" }, submission: null, submitted_at: null, deadline: null, overdue: true, reviewer: "Nour", marked: true, marks: {}, total: 38, max: 50, comments: "" },
    ],
    next_statuses: [badge("interview", "info", "مقابلة", "Interview"), badge("rejected", "dead", "مرفوض", "Rejected")],
    privacy_armed: true,
    line_ready: true,
    interview_form: [field("scheduled_at", "الموعد", { kind: "datetime", required: true }), field("meeting_link", "لينك الاجتماع")],
    test_form: [field("title", "العنوان"), field("deadline_days", "يوم", { kind: "number", ltr: true })],
    can: { hire: false, mark: false },
    ...over,
  };
}

describe("HrCandidatePage", () => {
  const page = (data: HrCandidate = candidate()) => ({ "/api/v1/hr/candidates/CAN-0007/": () => jsonResponse(data) });

  it("draws the application: who, what the bot collected, the interviews and the tests", async () => {
    serve("hr", page());
    const { container } = open("/hr/candidates/CAN-0007");
    await screen.findByText("إجابات المرشح");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Sara");
    expect(container.querySelector('[data-badge="anonymous"]')).not.toBeNull();
    expect(container.querySelector('[data-card="answers"]')).toHaveTextContent("اسمك إيه؟");
    const first = container.querySelector('[data-interview="21"]') as HTMLElement;
    expect(first).toHaveTextContent("41 / 50");
    expect(within(first).getByRole("link", { name: /قيّم/ })).toHaveAttribute("href", "/hr/interviews/21");
    expect(container.querySelector('[data-interview="22"]')).toHaveTextContent("—");
    const test = container.querySelector('[data-test="31"]') as HTMLElement;
    expect(test).toHaveTextContent("38 / 50");
    expect(test).toHaveTextContent("فات الموعد");
    expect(within(test).getByRole("link", { name: /test\.docx/ })).toHaveAttribute("href", "/files/recruitment/tests/x.docx");
  });

  it("offers the hire only to an approved candidate and the employee file once there is one", async () => {
    serve("hr", page(candidate({ can: { hire: true, mark: false } }, { status: approved })));
    const view = open("/hr/candidates/CAN-0007");
    expect(await screen.findByRole("link", { name: /حوّله لموظف/ })).toHaveAttribute("href", "/hr/candidates/CAN-0007/hire");
    view.unmount();
    serve("hr", page(candidate({ can: { hire: true, mark: false } }, { status: approved, hired_user: 44 })));
    open("/hr/candidates/CAN-0007");
    expect(await screen.findByRole("link", { name: /ملف الموظف/ })).toHaveAttribute("href", "/hr/employees/44");
    expect(screen.queryByRole("link", { name: /حوّله لموظف/ })).toBeNull();
  });

  it("does not offer the hire to a candidate who is not approved", async () => {
    serve("hr", page());
    open("/hr/candidates/CAN-0007");
    await screen.findByText("إجابات المرشح");
    expect(screen.queryByRole("link", { name: /حوّله لموظف/ })).toBeNull();
  });

  it("offers the marking only to who may mark", async () => {
    serve("admin", page(candidate({ can: { hire: false, mark: true } })));
    const view = open("/hr/candidates/CAN-0007");
    expect(await screen.findByRole("link", { name: /صحّح/ })).toHaveAttribute("href", "/reviewer/tests/31");
    view.unmount();
    serve("hr", page());
    open("/hr/candidates/CAN-0007");
    await screen.findByText("إجابات المرشح");
    expect(screen.queryByRole("link", { name: /صحّح/ })).toBeNull();
  });

  it("says when the identity rule is not armed", async () => {
    serve("hr", page(candidate({ privacy_armed: false })));
    const { container } = open("/hr/candidates/CAN-0007");
    await screen.findByText("إجابات المرشح");
    expect(container.querySelector('[data-note="privacy"]')).not.toBeNull();
  });

  it("moves the candidate with the chosen status and the reason, and the server's refusal is shown in words", async () => {
    const served = serve("hr", {
      ...page(),
      "/api/v1/hr/candidates/CAN-0007/status/": (url, init) => served.record(url, init, { ok: true }),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/candidates/CAN-0007");
    await screen.findByText("إجابات المرشح");
    const card = container.querySelector('[data-card="status"]') as HTMLElement;
    await user.selectOptions(within(card).getByLabelText("الحالة الجديدة"), "rejected");
    await user.type(within(card).getByLabelText("سبب أو ملاحظة"), "Not a fit");
    await user.click(within(card).getByRole("button", { name: /انقل/ }));
    await waitFor(() => expect(served.sent.length).toBe(1));
    expect(served.sent[0]).toEqual({ url: "/api/v1/hr/candidates/CAN-0007/status/", body: { status: "rejected", reason: "Not a fit" } });
  });

  it("shows the pipeline's refusal and changes nothing on the page", async () => {
    serve("hr", {
      ...page(),
      "/api/v1/hr/candidates/CAN-0007/status/": () => jsonResponse({ ok: false, error: "refused", message: "مينفعش تنقل من «فرز» للحالة دي." }, 409),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/candidates/CAN-0007");
    await screen.findByText("إجابات المرشح");
    const card = container.querySelector('[data-card="status"]') as HTMLElement;
    await user.click(within(card).getByRole("button", { name: /انقل/ }));
    expect(await within(card).findByRole("alert")).toHaveTextContent("مينفعش تنقل");
  });

  it("says when there is no move, and that the owner has the decision when it is with them", async () => {
    serve("hr", page(candidate({ next_statuses: [] }, { status: waitingOwner })));
    const { container } = open("/hr/candidates/CAN-0007");
    await screen.findByText("إجابات المرشح");
    expect(container.querySelector('[data-note="no-move"]')).not.toBeNull();
    expect(container.querySelector('[data-note="owner"]')).not.toBeNull();
    expect(screen.queryByRole("button", { name: /انقل/ })).toBeNull();
  });

  it("shows why a candidate was rejected", async () => {
    serve("hr", page(candidate({ next_statuses: [] }, { status: rejected, rejection_reason: "Salary expectations" })));
    const { container } = open("/hr/candidates/CAN-0007");
    await screen.findByText("إجابات المرشح");
    expect(container.querySelector('[data-note="rejected"]')).toHaveTextContent("Salary expectations");
  });

  it("asks twice before revealing the company, then sends the reason", async () => {
    const served = serve("hr", {
      ...page(),
      "/api/v1/hr/candidates/CAN-0007/reveal/": (url, init) => served.record(url, init, { ok: true }),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/candidates/CAN-0007");
    await screen.findByText("إجابات المرشح");
    const card = container.querySelector('[data-card="identity"]') as HTMLElement;
    await user.type(within(card).getByLabelText("السبب (اختياري)"), "Offer stage");
    await user.click(within(card).getByRole("button", { name: /اكشف الهوية/ }));
    expect(served.sent).toHaveLength(0);
    await user.click(within(card).getByRole("button", { name: /أيوه، اكشف/ }));
    await waitFor(() => expect(served.sent.length).toBe(1));
    expect(served.sent[0]).toEqual({ url: "/api/v1/hr/candidates/CAN-0007/reveal/", body: { reason: "Offer stage" } });
  });

  it("can take the second look back: no is no", async () => {
    const served = serve("hr", { ...page(), "/api/v1/hr/candidates/CAN-0007/reveal/": (url, init) => served.record(url, init, { ok: true }) });
    const user = userEvent.setup();
    const { container } = open("/hr/candidates/CAN-0007");
    await screen.findByText("إجابات المرشح");
    const card = container.querySelector('[data-card="identity"]') as HTMLElement;
    await user.click(within(card).getByRole("button", { name: /اكشف الهوية/ }));
    await user.click(within(card).getByRole("button", { name: "لأ" }));
    expect(within(card).getByRole("button", { name: /اكشف الهوية/ })).toBeInTheDocument();
    expect(served.sent).toHaveLength(0);
  });

  it("shows who revealed the company and when, and no button to do it again", async () => {
    serve("hr", page(candidate({}, { identity: { revealed: true, at: stampOf("2026-10-02 1:00 م", "2026-10-02 1:00 PM"), by: "Mona" } })));
    const { container } = open("/hr/candidates/CAN-0007");
    await screen.findByText("إجابات المرشح");
    const card = container.querySelector('[data-card="identity"]') as HTMLElement;
    expect(card).toHaveTextContent("Mona");
    expect(card).toHaveTextContent("2026-10-02 1:00 م");
    expect(within(card).queryByRole("button")).toBeNull();
    expect(container.querySelector('[data-badge="revealed"]')).not.toBeNull();
  });

  it("sends the message through the server and clears the box", async () => {
    const served = serve("hr", { ...page(), "/api/v1/hr/candidates/CAN-0007/message/": (url, init) => served.record(url, init, { ok: true }) });
    const user = userEvent.setup();
    const { container } = open("/hr/candidates/CAN-0007");
    await screen.findByText("إجابات المرشح");
    const card = container.querySelector('[data-card="message"]') as HTMLElement;
    const send = within(card).getByRole("button", { name: /ابعت/ });
    expect(send).toBeDisabled();
    await user.type(within(card).getByLabelText("الرسالة"), "Welcome");
    await user.click(send);
    await waitFor(() => expect(served.sent.length).toBe(1));
    expect(served.sent[0]).toEqual({ url: "/api/v1/hr/candidates/CAN-0007/message/", body: { body: "Welcome" } });
    await waitFor(() => expect(within(card).getByLabelText("الرسالة")).toHaveValue(""));
  });

  it("keeps the words when the message did not go, and says why", async () => {
    serve("hr", {
      ...page(),
      "/api/v1/hr/candidates/CAN-0007/message/": () => jsonResponse({ ok: false, error: "send_failed", message: "الرقم مش مسجل على واتساب." }, 502),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/candidates/CAN-0007");
    await screen.findByText("إجابات المرشح");
    const card = container.querySelector('[data-card="message"]') as HTMLElement;
    await user.type(within(card).getByLabelText("الرسالة"), "Welcome");
    await user.click(within(card).getByRole("button", { name: /ابعت/ }));
    expect(await within(card).findByRole("alert")).toHaveTextContent("الرقم مش مسجل على واتساب.");
    expect(within(card).getByLabelText("الرسالة")).toHaveValue("Welcome");
  });

  it("will not send when there is no recruitment number, and says why", async () => {
    const served = serve("hr", { ...page(candidate({ line_ready: false })), "/api/v1/hr/candidates/CAN-0007/message/": (url, init) => served.record(url, init, { ok: true }) });
    const user = userEvent.setup();
    const { container } = open("/hr/candidates/CAN-0007");
    await screen.findByText("إجابات المرشح");
    const card = container.querySelector('[data-card="message"]') as HTMLElement;
    expect(card.querySelector('[data-note="no-line"]')).not.toBeNull();
    await user.type(within(card).getByLabelText("الرسالة"), "Welcome");
    expect(within(card).getByRole("button", { name: /ابعت/ })).toBeDisabled();
    expect(served.sent).toHaveLength(0);
  });

  it("says so when the server refuses a message for want of the recruitment number", async () => {
    serve("hr", {
      ...page(),
      "/api/v1/hr/candidates/CAN-0007/message/": () => jsonResponse({ ok: false, error: "no_recruit_line" }, 409),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/candidates/CAN-0007");
    await screen.findByText("إجابات المرشح");
    const card = container.querySelector('[data-card="message"]') as HTMLElement;
    await user.type(within(card).getByLabelText("الرسالة"), "Welcome");
    await user.click(within(card).getByRole("button", { name: /ابعت/ }));
    expect(await within(card).findByRole("alert")).toHaveTextContent("رقم التوظيف مش متسجل");
  });

  it("books an interview with what was filled, and shows the form's refusal beside its box", async () => {
    const served = serve("hr", {
      ...page(),
      "/api/v1/hr/candidates/CAN-0007/interviews/": (url, init) => served.record(url, init, { ok: true, id: 9 }),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/candidates/CAN-0007");
    await screen.findByText("إجابات المرشح");
    const card = container.querySelector('[data-card="interview-new"]') as HTMLElement;
    expect(within(card).getByRole("button", { name: /سجّل/ })).toBeDisabled();
    fireValue(within(card).getByLabelText("الموعد"), "2026-10-20T15:30");
    await user.type(within(card).getByLabelText("لينك الاجتماع"), "https://meet.example/abc");
    await user.click(within(card).getByRole("button", { name: /سجّل/ }));
    await waitFor(() => expect(served.sent.length).toBe(1));
    expect(served.sent[0]!.body).toEqual({ values: { scheduled_at: "2026-10-20T15:30", meeting_link: "https://meet.example/abc" } });
  });

  it("shows an interview form's refusal", async () => {
    serve("hr", {
      ...page(),
      "/api/v1/hr/candidates/CAN-0007/interviews/": () => jsonResponse({ ok: false, error: "invalid", errors: { scheduled_at: ["Enter a valid date/time."] } }, 400),
    });
    const user = userEvent.setup();
    const { container } = open("/hr/candidates/CAN-0007");
    await screen.findByText("إجابات المرشح");
    const card = container.querySelector('[data-card="interview-new"]') as HTMLElement;
    await user.type(within(card).getByLabelText("لينك الاجتماع"), "x");
    await user.click(within(card).getByRole("button", { name: /سجّل/ }));
    expect(await within(card).findByText("Enter a valid date/time.")).toBeInTheDocument();
  });

  it("sets a test as plain JSON when there is no file", async () => {
    const served = serve("hr", { ...page(), "/api/v1/hr/candidates/CAN-0007/tests/": (url, init) => served.record(url, init, { ok: true, id: 3 }) });
    const user = userEvent.setup();
    const { container } = open("/hr/candidates/CAN-0007");
    await screen.findByText("إجابات المرشح");
    const card = container.querySelector('[data-card="test-new"]') as HTMLElement;
    await user.type(within(card).getByLabelText("العنوان"), "Sample");
    await user.type(within(card).getByLabelText("يوم"), "2");
    await user.click(within(card).getByRole("button", { name: /سجّل/ }));
    await waitFor(() => expect(served.sent.length).toBe(1));
    expect(served.sent[0]!.body).toEqual({ values: { title: "Sample", deadline_days: "2" } });
  });

  it("sets a test with its file as a multipart form: the values as JSON text and the file beside them", async () => {
    let seen: FormData | null = null;
    serve("hr", {
      ...page(),
      "/api/v1/hr/candidates/CAN-0007/tests/": (_url, init) => {
        seen = init?.body as FormData;
        return jsonResponse({ ok: true, id: 3 });
      },
    });
    const user = userEvent.setup();
    const { container } = open("/hr/candidates/CAN-0007");
    await screen.findByText("إجابات المرشح");
    const card = container.querySelector('[data-card="test-new"]') as HTMLElement;
    await user.type(within(card).getByLabelText("العنوان"), "Sample");
    await user.upload(within(card).getByLabelText("ملف الاختبار"), new File(["docx"], "test.docx"));
    await user.click(within(card).getByRole("button", { name: /سجّل/ }));
    await waitFor(() => expect(seen).not.toBeNull());
    expect(JSON.parse(String(seen!.get("values")))).toEqual({ title: "Sample" });
    expect((seen!.get("assignment") as File).name).toBe("test.docx");
  });

  it("saves only the profile boxes that changed", async () => {
    const served = serve("hr", { ...page(), "/api/v1/hr/candidates/CAN-0007/save/": (url, init) => served.record(url, init, { ok: true }) });
    const user = userEvent.setup();
    const { container } = open("/hr/candidates/CAN-0007");
    await screen.findByText("إجابات المرشح");
    const card = container.querySelector('[data-card="profile"]') as HTMLElement;
    const save = within(card).getByRole("button", { name: "احفظ" });
    expect(save).toBeDisabled();
    await user.type(within(card).getByLabelText("ملاحظات HR"), "Strong");
    await user.click(save);
    await waitFor(() => expect(served.sent.length).toBe(1));
    expect(served.sent[0]!.body).toEqual({ values: { hr_notes: "Strong" } });
  });

  it("uploads a CV as a file of its own, and links the one there is", async () => {
    let seen: FormData | null = null;
    serve("hr", {
      ...page(),
      "/api/v1/hr/candidates/CAN-0007/cv/": (_url, init) => {
        seen = init?.body as FormData;
        return jsonResponse({ ok: true });
      },
    });
    const user = userEvent.setup();
    const { container } = open("/hr/candidates/CAN-0007");
    await screen.findByText("إجابات المرشح");
    const card = container.querySelector('[data-card="profile"]') as HTMLElement;
    expect(within(card).getByRole("link", { name: /Sara CV\.pdf/ })).toHaveAttribute("href", "/files/recruitment/cv/2026/10/abc.pdf");
    await user.upload(within(card).getByLabelText("الـCV"), new File(["pdf"], "new cv.pdf"));
    await waitFor(() => expect(seen).not.toBeNull());
    expect((seen!.get("file") as File).name).toBe("new cv.pdf");
  });

  it("says when a CV is refused for its size or for being empty", async () => {
    serve("hr", { ...page(), "/api/v1/hr/candidates/CAN-0007/cv/": () => jsonResponse({ ok: false, error: "bad_file" }, 400) });
    const user = userEvent.setup();
    const { container } = open("/hr/candidates/CAN-0007");
    await screen.findByText("إجابات المرشح");
    const card = container.querySelector('[data-card="profile"]') as HTMLElement;
    await user.upload(within(card).getByLabelText("الـCV"), new File(["pdf"], "cv.pdf"));
    expect(await within(card).findByText(/أكبر من الحد/)).toBeInTheDocument();
  });

  it("says a candidate that is not there is not there", async () => {
    serve("hr", { "/api/v1/hr/candidates/CAN-0007/": () => jsonResponse({ ok: false, error: "not_found" }, 404) });
    open("/hr/candidates/CAN-0007");
    expect(await screen.findByRole("alert")).toHaveTextContent("الصفحة دي مش موجودة.");
  });

  it("is HR's and the admin's", async () => {
    const served = serve("translator", page());
    open("/hr/candidates/CAN-0007");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/"))).toBe(false);
  });
});

function interview(): HrInterview {
  return {
    ok: true,
    interview: { id: 21, at: stampOf("2026-10-05 3:00 م", "2026-10-05 3:00 PM"), kind: online, interviewer: "Mona", meeting_link: "https://meet.example/abc", location: "", notes: "", evaluated: true, marks: { communication: 8 }, total: 8, max: 50, comments: "" },
    candidate: { code: "CAN-0007", name: "Sara" },
    form: [field("communication", "التواصل", { kind: "number", value: 8, min: 0, max: 10 }), field("experience", "الخبرة", { kind: "number", min: 0, max: 10 }), field("comments", "ملاحظات", { kind: "textarea" })],
  };
}

describe("HrInterviewPage", () => {
  const page = () => ({ "/api/v1/hr/interviews/21/": () => jsonResponse(interview()) });

  it("shows who, when, the total so far and the way back", async () => {
    serve("hr", page());
    const { container } = open("/hr/interviews/21");
    await screen.findByText("الدرجات");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Sara");
    expect(container.querySelector('[data-card="total"]')).toHaveTextContent("8 / 50");
    expect(within(container.querySelector('[data-card="total"]') as HTMLElement).getByRole("link", { name: /ارجع للمرشح/ })).toHaveAttribute("href", "/hr/candidates/CAN-0007");
    expect(container.querySelector('[data-card="meeting"]')).toHaveTextContent("https://meet.example/abc");
  });

  it("saves only the marks that changed, and the total is the server's", async () => {
    const served = serve("hr", { ...page(), "/api/v1/hr/interviews/21/score/": (url, init) => served.record(url, init, { ok: true, total: 17, max: 50 }) });
    const user = userEvent.setup();
    open("/hr/interviews/21");
    await screen.findByText("الدرجات");
    expect(screen.getByLabelText("التواصل")).toHaveValue(8);
    expect(screen.getByRole("button", { name: /احفظ التقييم/ })).toBeDisabled();
    await user.type(screen.getByLabelText("الخبرة"), "9");
    await user.click(screen.getByRole("button", { name: /احفظ التقييم/ }));
    await waitFor(() => expect(served.sent.length).toBe(1));
    expect(served.sent[0]).toEqual({ url: "/api/v1/hr/interviews/21/score/", body: { values: { experience: "9" } } });
    expect(screen.queryByLabelText(/الإجمالي/)).toBeNull();
  });

  it("shows the form's refusal", async () => {
    serve("hr", { ...page(), "/api/v1/hr/interviews/21/score/": () => jsonResponse({ ok: false, error: "invalid", errors: { experience: ["من 0 لـ 10."] } }, 400) });
    const user = userEvent.setup();
    open("/hr/interviews/21");
    await screen.findByText("الدرجات");
    await user.type(screen.getByLabelText("الخبرة"), "5");
    await user.click(screen.getByRole("button", { name: /احفظ التقييم/ }));
    expect(await screen.findByText("من 0 لـ 10.")).toBeInTheDocument();
  });

  it("says an interview that is not there is not there", async () => {
    serve("hr", { "/api/v1/hr/interviews/21/": () => jsonResponse({ ok: false, error: "not_found" }, 404) });
    open("/hr/interviews/21");
    expect(await screen.findByRole("alert")).toHaveTextContent("الصفحة دي مش موجودة.");
  });
});

function hire(over: Partial<HrHire> = {}): HrHire {
  return {
    ok: true,
    candidate: { code: "CAN-0007", name: "Sara", phone: "01000000000", email: "sara@example.com", languages: "AR, EN", department: "الترجمة", shift: "الصبح", cv: file, status: approved, hired_user: null },
    hireable: true,
    probation_days: 90,
    form: [
      field("role", "الدور", { kind: "select", required: true, value: "translator", choices: [{ value: "translator", label: "Translator", label_ar: "مترجم", label_en: "Translator" }, { value: "reviewer", label: "Reviewer", label_ar: "مراجع", label_en: "Reviewer" }] }),
      field("job_title", "المسمى الوظيفي", { value: "مترجم عربي" }),
      field("joining_date", "تاريخ الانضمام", { kind: "date", required: true, value: "2026-10-04" }),
      field("username", "اسم المستخدم", { ltr: true }),
      field("password", "الباسورد", { kind: "password", saved: false }),
    ],
    ...over,
  };
}

describe("HrHirePage", () => {
  const page = (data: HrHire = hire()) => ({ "/api/v1/hr/candidates/CAN-0007/hire/": () => jsonResponse(data) });

  it("shows what carries over, the contract form as it starts, and how long the probation is", async () => {
    serve("hr", page());
    const { container } = open("/hr/candidates/CAN-0007/hire");
    await screen.findByText("بيانات التعاقد");
    const carries = container.querySelector('[data-card="carries"]') as HTMLElement;
    for (const part of ["Sara", "01000000000", "sara@example.com", "AR, EN", "الترجمة", "الصبح"]) expect(carries).toHaveTextContent(part);
    expect(screen.getByLabelText("المسمى الوظيفي")).toHaveValue("مترجم عربي");
    expect(screen.getByLabelText("تاريخ الانضمام")).toHaveValue("2026-10-04");
    expect(container.querySelector('[data-note="probation"]')).toHaveTextContent("90");
  });

  it("tells HR the starting salary is the owner's to set and where to ask for it, and says nothing when the box is there", async () => {
    serve("hr", page());
    const view = open("/hr/candidates/CAN-0007/hire");
    await screen.findByText("بيانات التعاقد");
    expect(view.container.querySelector('[data-note="salary-later"]')).not.toBeNull();
    expect(screen.getByRole("link", { name: "طلبات تغيير الراتب" })).toHaveAttribute("href", "/hr/salary-requests");
    view.unmount();
    const withSalary = hire();
    serve("admin", page({ ...withSalary, form: [...withSalary.form, field("salary", "الراتب الأساسي", { kind: "number" })] }));
    const owner = open("/hr/candidates/CAN-0007/hire");
    await screen.findByText("بيانات التعاقد");
    expect(owner.container.querySelector('[data-note="salary-later"]')).toBeNull();
    expect(screen.getByLabelText("الراتب الأساسي")).toBeInTheDocument();
  });

  it("offers only the roles the server sent and a password box that starts empty", async () => {
    serve("hr", page());
    open("/hr/candidates/CAN-0007/hire");
    await screen.findByText("بيانات التعاقد");
    expect(within(screen.getByLabelText("الدور")).getAllByRole("option").map((one) => one.getAttribute("value"))).toEqual(["translator", "reviewer"]);
    const password = screen.getByLabelText("الباسورد");
    expect(password).toHaveAttribute("type", "password");
    expect(password).toHaveValue("");
  });

  it("sends only what was changed, and goes to the new employee's file", async () => {
    const served = serve("hr", {
      ...page(),
      "/api/v1/hr/candidates/CAN-0007/hire/save/": (url, init) => served.record(url, init, { ok: true, id: 44, username: "sara.new" }),
      "/api/v1/hr/employees/44/": () => jsonResponse({ ok: false, error: "not_found" }, 404),
    });
    const user = userEvent.setup();
    open("/hr/candidates/CAN-0007/hire");
    await screen.findByText("بيانات التعاقد");
    await user.selectOptions(screen.getByLabelText("الدور"), "reviewer");
    await user.type(screen.getByLabelText("الباسورد"), "A-long-pass-phrase-2026");
    await user.click(screen.getByRole("button", { name: /عيّنه/ }));
    await waitFor(() => expect(served.sent.length).toBe(1));
    expect(served.sent[0]).toEqual({ url: "/api/v1/hr/candidates/CAN-0007/hire/save/", body: { values: { role: "reviewer", password: "A-long-pass-phrase-2026" } } });
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/hr/employees/44"));
  });

  it("shows the form's refusal beside its box and stays on the page", async () => {
    serve("hr", {
      ...page(),
      "/api/v1/hr/candidates/CAN-0007/hire/save/": () => jsonResponse({ ok: false, error: "invalid", errors: { password: ["This password is too common."], role: ["Select a valid choice."] } }, 400),
    });
    const user = userEvent.setup();
    open("/hr/candidates/CAN-0007/hire");
    await screen.findByText("بيانات التعاقد");
    await user.type(screen.getByLabelText("الباسورد"), "password1");
    await user.click(screen.getByRole("button", { name: /عيّنه/ }));
    expect(await screen.findByText("This password is too common.")).toBeInTheDocument();
    expect(screen.getByText("Select a valid choice.")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/hr\/candidates\/CAN-0007\/hire$/);
  });

  it("says the owner has to approve first, with no form, when the candidate is not approved", async () => {
    serve("hr", page(hire({ hireable: false, form: [], candidate: { ...hire().candidate, status: screening } })));
    const { container } = open("/hr/candidates/CAN-0007/hire");
    await screen.findByText(/لازم المالك يوافق الأول/);
    expect(container.querySelector('[data-card="contract"]')).toBeNull();
    expect(screen.getByRole("link", { name: "ارجع للمرشح" })).toHaveAttribute("href", "/hr/candidates/CAN-0007");
  });

  it("says a candidate already hired is hired, and links the employee", async () => {
    serve("hr", page(hire({ hireable: false, form: [], candidate: { ...hire().candidate, hired_user: 44 } })));
    open("/hr/candidates/CAN-0007/hire");
    await screen.findByText(/المرشح ده اتعيّن بالفعل/);
    expect(screen.getByRole("link", { name: "ملف الموظف" })).toHaveAttribute("href", "/hr/employees/44");
  });

  it("is HR's and the admin's", async () => {
    const served = serve("accounting", page());
    open("/hr/candidates/CAN-0007/hire");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/"))).toBe(false);
  });
});

function approvals(over: Partial<HrApprovals> = {}): HrApprovals {
  return {
    ok: true,
    waiting: [{ ...row({ code: "CAN-0009", name: "Laila", status: waitingOwner }), interview_score: { total: 41, max: 50 }, test_score: null, expected_salary: "7000", hr_recommendation: "Hire", hr_notes: "Strong", cv: file, department: "الترجمة" }],
    decided: [
      { ...row({ code: "CAN-0010", name: "Karim", status: approved }), decided_at: stampOf("2026-10-02 1:00 م", "2026-10-02 1:00 PM"), can_hire: true },
      { ...row({ code: "CAN-0011", name: "Hala", status: badge("hired", "ok", "اتعيّن", "Hired") }), decided_at: null, can_hire: false },
    ],
    ...over,
  };
}

describe("HrApprovalsPage", () => {
  const page = (data: HrApprovals = approvals()) => ({ "/api/v1/hr/approvals/": () => jsonResponse(data) });

  it("shows what the owner decides on, and a score nobody gave as a dash and not a zero", async () => {
    serve("admin", page());
    const { container } = open("/hr/approvals");
    await screen.findByText("مستني قرارك");
    const card = container.querySelector('[data-waiting="CAN-0009"]') as HTMLElement;
    expect(within(card).getByRole("link", { name: "Laila" })).toHaveAttribute("href", "/hr/candidates/CAN-0009");
    expect(card.querySelector('[data-score="interview"]')).toHaveTextContent("41 / 50");
    expect(card.querySelector('[data-score="test"]')).toHaveTextContent("—");
    expect(card).toHaveTextContent("7000");
    expect(card).toHaveTextContent("Hire");
    expect(within(card).getByRole("link", { name: /Sara CV\.pdf/ })).toHaveAttribute("href", file.url);
  });

  it("approves with one click, and sends no reason with it", async () => {
    const served = serve("admin", { ...page(), "/api/v1/hr/approvals/CAN-0009/approve/": (url, init) => served.record(url, init, { ok: true }) });
    const user = userEvent.setup();
    const { container } = open("/hr/approvals");
    await screen.findByText("مستني قرارك");
    const card = container.querySelector('[data-waiting="CAN-0009"]') as HTMLElement;
    await user.type(within(card).getByLabelText("سبب الرفض"), "typed but not rejecting");
    await user.click(within(card).getByRole("button", { name: /وافق على التعيين/ }));
    await waitFor(() => expect(served.sent.length).toBe(1));
    expect(served.sent[0]).toEqual({ url: "/api/v1/hr/approvals/CAN-0009/approve/", body: { reason: "" } });
  });

  it("rejects with the typed reason", async () => {
    const served = serve("admin", { ...page(), "/api/v1/hr/approvals/CAN-0009/reject/": (url, init) => served.record(url, init, { ok: true }) });
    const user = userEvent.setup();
    const { container } = open("/hr/approvals");
    await screen.findByText("مستني قرارك");
    const card = container.querySelector('[data-waiting="CAN-0009"]') as HTMLElement;
    await user.type(within(card).getByLabelText("سبب الرفض"), "Salary expectations");
    await user.click(within(card).getByRole("button", { name: /ارفض/ }));
    await waitFor(() => expect(served.sent.length).toBe(1));
    expect(served.sent[0]).toEqual({ url: "/api/v1/hr/approvals/CAN-0009/reject/", body: { reason: "Salary expectations" } });
  });

  it("offers the hire only for a decided candidate who has not been hired", async () => {
    serve("admin", page());
    const { container } = open("/hr/approvals");
    await screen.findByText("اتقرر فيها");
    expect(within(container.querySelector('[data-decided="CAN-0010"]') as HTMLElement).getByRole("link", { name: /حوّله لموظف/ })).toHaveAttribute("href", "/hr/candidates/CAN-0010/hire");
    expect(within(container.querySelector('[data-decided="CAN-0011"]') as HTMLElement).queryByRole("link", { name: /حوّله لموظف/ })).toBeNull();
  });

  it("says when nothing waits", async () => {
    serve("admin", page(approvals({ waiting: [], decided: [] })));
    open("/hr/approvals");
    expect(await screen.findByText("مفيش حاجة مستنية.")).toBeInTheDocument();
    expect(screen.getByText("لسه مفيش.")).toBeInTheDocument();
  });

  it("is the owner's alone: HR is sent home and nothing is asked", async () => {
    const served = serve("hr", page());
    open("/hr/approvals");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/hr/"))).toBe(false);
  });
});

function queue(over: Partial<ReviewerQueue> = {}): ReviewerQueue {
  return {
    ok: true,
    pending: [
      { id: 5, candidate: "CAN-0007", title: "Sample", department: "الترجمة", overdue: true, submitted: true, submitted_at: stampOf("10-03", "10-03"), marked_at: null, total: null, max: 50 },
      { id: 6, candidate: "CAN-0008", title: "Other", department: null, overdue: false, submitted: false, submitted_at: null, marked_at: null, total: null, max: 50 },
    ],
    done: [{ id: 4, candidate: "CAN-0006", title: "Old", department: null, overdue: false, submitted: true, submitted_at: stampOf("09-30", "09-30"), marked_at: stampOf("2026-10-01 1:00 م", "2026-10-01 1:00 PM"), total: 38, max: 50 }],
    ...over,
  };
}

describe("ReviewerTestsPage", () => {
  const page = (data: ReviewerQueue = queue()) => ({ "/api/v1/reviewer/tests/": () => jsonResponse(data) });

  it("lists the tests by candidate code with the way to mark each one", async () => {
    serve("reviewer", page());
    const { container } = open("/reviewer/tests");
    await screen.findByText("مستنية تصحيح");
    const first = container.querySelector('[data-table="pending"] [data-test="5"]') as HTMLElement;
    expect(first).toHaveTextContent("CAN-0007");
    expect(first).toHaveTextContent("فات الموعد");
    expect(within(first).getByRole("link", { name: /صحّح/ })).toHaveAttribute("href", "/reviewer/tests/5");
    expect(container.querySelector('[data-table="pending"] [data-test="6"]')).toHaveTextContent("لسه");
    expect(container.querySelector('[data-table="done"] [data-test="4"]')).toHaveTextContent("38 / 50");
  });

  it("says when there is nothing", async () => {
    serve("reviewer", page(queue({ pending: [], done: [] })));
    open("/reviewer/tests");
    expect(await screen.findByText("مفيش اختبارات مستنية.")).toBeInTheDocument();
    expect(screen.getByText("لسه مفيش.")).toBeInTheDocument();
  });

  it("is the reviewer's, a team leader's and the owner's: HR is sent home and nothing is asked", async () => {
    const served = serve("hr", page());
    open("/reviewer/tests");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/reviewer/"))).toBe(false);
    for (const who of ["team_lead", "admin"] as const) {
      serve(who, page());
      const view = open("/reviewer/tests");
      expect(await screen.findByText("مستنية تصحيح")).toBeInTheDocument();
      view.unmount();
    }
  });
});

function reviewerTest(over: Partial<ReviewerTest> = {}): ReviewerTest {
  return {
    ok: true,
    blind: true,
    candidate: { code: "CAN-0007" },
    test: {
      id: 5,
      title: "Sample",
      brief: "Translate the paragraph",
      department: null,
      language_pair: "EN-AR",
      word_count: 300,
      deadline: stampOf("2026-10-10", "2026-10-10"),
      assignment: { url: "/files/recruitment/tests/brief.pdf", name: "brief.pdf" },
      submission: { url: "/files/recruitment/tests/abc.docx", name: "submission.docx" },
      submitted_at: stampOf("10-03", "10-03"),
      marked: false,
      total: 0,
      max: 50,
    },
    form: [field("accuracy", "الدقة", { kind: "number", min: 0, max: 10 }), field("grammar", "القواعد", { kind: "number", min: 0, max: 10 }), field("comments", "ملاحظات المراجع", { kind: "textarea" })],
    ...over,
  };
}

describe("ReviewerTestPage", () => {
  const page = (data: ReviewerTest = reviewerTest()) => ({ "/api/v1/reviewer/tests/5/": () => jsonResponse(data) });

  it("shows the code and the work to a reviewer and says what they are not shown", async () => {
    serve("reviewer", page());
    const { container } = open("/reviewer/tests/5");
    await screen.findByText("التقييم");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("CAN-0007");
    expect(container.querySelector('[data-note="blind"]')).not.toBeNull();
    expect(within(container.querySelector('[data-field="submission"]') as HTMLElement).getByRole("link", { name: /submission\.docx/ })).toHaveAttribute("href", "/files/recruitment/tests/abc.docx");
    const card = container.querySelector('[data-card="test"]') as HTMLElement;
    expect(card).toHaveTextContent("EN-AR");
    expect(card).toHaveTextContent("Translate the paragraph");
    expect(within(card).getByRole("link", { name: /brief\.pdf/ })).toHaveAttribute("href", "/files/recruitment/tests/brief.pdf");
  });

  it("shows the owner who it is and no blind note", async () => {
    serve("admin", page(reviewerTest({ blind: false, candidate: { code: "CAN-0007", name: "Sara" } })));
    const { container } = open("/reviewer/tests/5");
    await screen.findByText("التقييم");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Sara");
    expect(container.querySelector('[data-note="blind"]')).toBeNull();
  });

  it("marks with only what was filled and goes back to the queue", async () => {
    const served = serve("reviewer", {
      ...page(),
      "/api/v1/reviewer/tests/5/score/": (url, init) => served.record(url, init, { ok: true, total: 17, max: 50 }),
      "/api/v1/reviewer/tests/": () => jsonResponse(queue()),
    });
    const user = userEvent.setup();
    open("/reviewer/tests/5");
    await screen.findByText("التقييم");
    expect(screen.getByRole("button", { name: /احفظ التقييم/ })).toBeDisabled();
    await user.type(screen.getByLabelText("الدقة"), "9");
    await user.type(screen.getByLabelText("القواعد"), "8");
    await user.click(screen.getByRole("button", { name: /احفظ التقييم/ }));
    await waitFor(() => expect(served.sent.length).toBe(1));
    expect(served.sent[0]).toEqual({ url: "/api/v1/reviewer/tests/5/score/", body: { values: { accuracy: "9", grammar: "8" } } });
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(/^\/reviewer\/tests$/));
  });

  it("attaches the candidate's work as a multipart form beside the values", async () => {
    let seen: FormData | null = null;
    serve("reviewer", {
      ...page(),
      "/api/v1/reviewer/tests/5/score/": (_url, init) => {
        seen = init?.body as FormData;
        return jsonResponse({ ok: true, total: 9, max: 50 });
      },
      "/api/v1/reviewer/tests/": () => jsonResponse(queue()),
    });
    const user = userEvent.setup();
    open("/reviewer/tests/5");
    await screen.findByText("التقييم");
    await user.upload(screen.getByLabelText("ملف تسليم المرشح"), new File(["docx"], "answer.docx"));
    await user.type(screen.getByLabelText("الدقة"), "9");
    await user.click(screen.getByRole("button", { name: /احفظ التقييم/ }));
    await waitFor(() => expect(seen).not.toBeNull());
    expect(JSON.parse(String(seen!.get("values")))).toEqual({ accuracy: "9" });
    expect((seen!.get("submission") as File).name).toBe("answer.docx");
  });

  it("shows the form's refusal and stays on the test", async () => {
    serve("reviewer", {
      ...page(),
      "/api/v1/reviewer/tests/5/score/": () => jsonResponse({ ok: false, error: "invalid", errors: { __all__: ["اكتب درجة واحدة على الأقل."] } }, 400),
    });
    const user = userEvent.setup();
    open("/reviewer/tests/5");
    await screen.findByText("التقييم");
    await user.type(screen.getByLabelText("ملاحظات المراجع"), "x");
    await user.click(screen.getByRole("button", { name: /احفظ التقييم/ }));
    expect(await screen.findByText("اكتب درجة واحدة على الأقل.")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/reviewer\/tests\/5$/);
  });

  it("says a test that is not there (or is another reviewer's) is not there", async () => {
    serve("reviewer", { "/api/v1/reviewer/tests/5/": () => jsonResponse({ ok: false, error: "not_found" }, 404) });
    open("/reviewer/tests/5");
    expect(await screen.findByRole("alert")).toHaveTextContent("الصفحة دي مش موجودة.");
  });

  it("is not HR's", async () => {
    const served = serve("hr", page());
    open("/reviewer/tests/5");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/reviewer/"))).toBe(false);
  });
});
