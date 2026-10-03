import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { OpsTask, Role } from "../api/types";
import { ToastProvider } from "../components/Toasts";
import { jsonResponse, me, mockFetch, renderWithProviders, type Routes as FetchRoutes } from "../test/helpers";
import { OperationTaskPage } from "./OperationTaskPage";

afterEach(() => vi.unstubAllGlobals());

const CODE = "TSK-00001";
const DOOR = `/api/v1/tasks/${CODE}/`;
const stamp = (text: string) => ({ ar: `${text} م`, en: `${text} PM` });

function task(over: Partial<OpsTask> = {}): OpsTask {
  return {
    code: CODE,
    title: "Contract for review",
    status: { value: "in_progress", tone: "work", ar: "شغل جاري", en: "In progress" },
    priority: { value: "high", ar: "عالية", en: "High" },
    origin: { value: "whatsapp", icon: "message", ar: "واتساب", en: "WhatsApp" },
    client: "CL-0001",
    client_code: "CL-0001",
    source_lang: "English",
    target_lang: "Arabic",
    due: { ar: "2026-10-30 5:30 م", en: "2026-10-30 5:30 PM" },
    due_state: "ok",
    translator_due: stamp("10-28 3:00"),
    description: "Translate pages 2-4\nKeep the table",
    people: { operation: "Nour", team_lead: "Mona", translator: "Sam" },
    waiting_for: null,
    files: {
      original: [
        { id: 1, url: "/files/in/contract.pdf", name: "contract.pdf", size: "2.0 KB", image: false },
        { id: 2, url: "/files/in/photo.png", name: "photo.png", size: "10 B", image: true },
      ],
      translation: [],
    },
    chat: { url: "/ops/chats/u/9/", label_ar: "افتح الشات مع Mona", label_en: "Open the chat with Mona" },
    client_chat_url: "/ops/chats/CL-0001/",
    can: { assign_lead: false, take_over: false, deliver: false, cancel: true, add_member: false, new_request: true, set_deadline: true, set_words: true },
    lead: null,
    leads: [],
    handover: null,
    deliver: null,
    group_candidates: [],
    words: { state: "empty", value: null },
    requirements: [
      { id: 1, kind: { value: "like", ar: "بيحب", en: "Likes" }, author: "Nour", text: "Formal tone" },
      { id: 2, kind: { value: "dislike", ar: "بيكره", en: "Dislikes" }, author: null, text: "Contractions" },
    ],
    deliveries: [],
    messages: [],
    history: [
      { id: 1, name: "Mona", initials: "MS", role: "team_lead", at: stamp("10-01 9:00"), status: "accepted" },
      { id: 2, name: "Sam", initials: "SM", role: "translator", at: stamp("10-01 9:30"), status: "pending" },
    ],
    ...over,
  };
}

function serve(initial: OpsTask | Response, extra: FetchRoutes = {}, role: Role = "operation") {
  const state = { task: initial instanceof Response ? null : initial };
  // The first path that is a prefix of the request wins, and the page's own address is the start of its write doors.
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role, is_admin: role === "admin" })),
    ...extra,
    [DOOR]: () => (initial instanceof Response ? initial : jsonResponse({ ok: true, task: state.task })),
  });
  vi.stubGlobal("fetch", mocked.fn);
  return { ...mocked, state };
}

function open(route = `/tasks/${CODE}`, lang: "ar" | "en" = "ar") {
  return renderWithProviders(
    <ToastProvider>
      <Routes>
        <Route path="/tasks/:code" element={<OperationTaskPage />} />
        <Route path="/tasks" element={<div>tasks page</div>} />
        <Route path="/tasks/new" element={<div>new task page</div>} />
        <Route path="/" element={<div>home page</div>} />
      </Routes>
    </ToastProvider>,
    { route, lang },
  );
}

const loaded = () => screen.findByText(/Contract for review/);
const posts = (calls: { url: string; init?: RequestInit }[], path: string) => calls.filter((c) => c.url === path && c.init?.method === "POST");
const form = (call: { init?: RequestInit }) => Object.fromEntries(new URLSearchParams(String(call.init?.body)));
const parts = (call: { init?: RequestInit }) => call.init!.body as FormData;
const A = (name: string) => `/api/tasks/${CODE}/${name}/`;

describe("OperationTaskPage: what the operation reads", () => {
  it("shows the task: code, status, priority, the client's date, the translator's, and where it came from", async () => {
    serve(task());
    const { container } = open();
    await loaded();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(CODE);
    expect(screen.getByText("شغل جاري").closest(".badge")).not.toBeNull();
    expect(screen.getByText("عالية")).toHaveClass("badge--prio-high");
    expect(screen.getByText("واتساب")).toBeInTheDocument();
    expect(screen.getByText("2026-10-30 5:30 م").closest(".deadline--ok")).not.toBeNull();
    expect(screen.getByTitle("الديدلاين اللي المترجم شايفه")).toHaveTextContent("10-28 3:00 م");
    expect(container.textContent).toContain("CL-0001 · English → Arabic");
    for (const name of ["Nour", "Mona", "Sam"]) expect(within(container).getAllByText(name).length).toBeGreaterThan(0);
    const brief = screen.getByText(/Translate pages 2-4/);
    expect(brief).toHaveStyle({ whiteSpace: "pre-wrap" });
    expect(brief.textContent).toBe("Translate pages 2-4\nKeep the table");
  });

  it("says there is no deadline and no translator date when there are none", async () => {
    serve(task({ due: null, due_state: "none", translator_due: null }));
    const { container } = open();
    await loaded();
    expect(screen.getByText("من غير ديدلاين").closest(".deadline--none")).not.toBeNull();
    expect(container.querySelector(".page-head .chip")).toBeNull();
  });

  it("speaks English when asked", async () => {
    serve(task());
    open(`/tasks/${CODE}`, "en");
    expect(await screen.findByText("In progress")).toBeInTheDocument();
    expect(screen.getByText("2026-10-30 5:30 PM")).toBeInTheDocument();
    expect(screen.getByText("Original (from the client)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /New request, same files/ })).toBeInTheDocument();
  });

  it("offers a new request on the same files, as a route with the task named", async () => {
    serve(task());
    open();
    const link = await screen.findByRole("link", { name: /طلب جديد على نفس الملفات/ });
    expect(link).toHaveAttribute("href", `/tasks/new?from=${CODE}`);
    await userEvent.click(link);
    expect(await screen.findByText("new task page")).toBeInTheDocument();
  });

  it("lists the client's files as links that open on their own, pictures as pictures, and what the translator handed in", async () => {
    serve(
      task({
        files: {
          original: task().files.original,
          translation: [{ id: 9, url: "/files/out/translated.docx", name: "translated.docx", size: "1.5 KB", image: false, at: stamp("10-02 4:10") }],
        },
      }),
    );
    const { container } = open();
    const pdf = await screen.findByRole("link", { name: /contract\.pdf/ });
    expect(pdf).toHaveAttribute("href", "/files/in/contract.pdf");
    expect(pdf).toHaveAttribute("target", "_blank");
    expect(pdf.getAttribute("rel")).toContain("noopener");
    expect(container.querySelector('a.task-thumb img[alt="photo.png"]')?.getAttribute("src")).toBe("/files/in/photo.png");
    expect(screen.getByRole("link", { name: /translated\.docx/ })).toHaveTextContent("10-02 4:10 م");
  });

  it("says the translation has not come when it has not, and has no translation box when nobody has the task", async () => {
    serve(task());
    const view = open();
    expect(await screen.findByText("المترجم لسه مارفعش ملف الترجمة.")).toBeInTheDocument();
    view.unmount();
    vi.unstubAllGlobals();
    serve(task({ people: { operation: "Nour", team_lead: null, translator: null } }));
    open();
    await loaded();
    expect(screen.queryByText("ملف الترجمة (من المترجم)")).toBeNull();
  });

  it("draws a file only as a link to this site, and still names it", async () => {
    serve(
      task({
        files: {
          original: [
            { id: 1, url: "https://evil.example/a.pdf", name: "outside.pdf", size: "1 B", image: false },
            { id: 2, url: "javascript:alert(1)", name: "script.png", size: "1 B", image: true },
          ],
          translation: [],
        },
      }),
    );
    const { container } = open();
    expect(await screen.findByText("outside.pdf")).toBeInTheDocument();
    expect(screen.getByText("script.png")).toBeInTheDocument();
    expect(container.querySelector(".task-files a, .task-files img")).toBeNull();
  });

  it("links the leader's chat and the client's own conversation, for addresses on this site only", async () => {
    serve(task());
    const view = open();
    expect(await screen.findByRole("link", { name: /افتح الشات مع Mona/ })).toHaveAttribute("href", "/ops/chats/u/9/");
    expect(screen.getByRole("link", { name: /المحادثة مع العميل/ })).toHaveAttribute("href", "/ops/chats/CL-0001/");
    view.unmount();
    vi.unstubAllGlobals();
    serve(task({ chat: { url: "https://evil.example/", label_ar: "x", label_en: "x" }, client_chat_url: "//evil.example" }));
    open();
    await loaded();
    expect(screen.queryByRole("link", { name: /المحادثة مع العميل/ })).toBeNull();
    expect(screen.queryByRole("link", { name: "x" })).toBeNull();
  });

  it("says who has been asked to take it and how long they have", async () => {
    serve(task({ waiting_for: { name: "Sam", seconds_left: 42 } }));
    open();
    await loaded();
    expect(screen.getByText("لسه ماأكدش الاستلام — العداد شغال.").closest(".note")).toHaveTextContent("Sam");
    expect(screen.getByText("42s")).toBeInTheDocument();
  });

  it("lists the client's messages with their channel, and their files", async () => {
    serve(
      task({
        messages: [
          { id: 1, channel: "whatsapp", at: stamp("10-01 9:00"), body: "Please translate this", files: [{ id: 3, url: "/files/in/a.pdf", name: "a.pdf", size: "1 B", image: false }] },
          { id: 2, channel: "email", at: stamp("10-01 9:05"), body: "", files: [] },
        ],
      }),
    );
    const { container } = open();
    expect(await screen.findByText("Please translate this")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /a\.pdf/ })).toHaveAttribute("href", "/files/in/a.pdf");
    expect(container.textContent).toContain("WhatsApp · 10-01 9:00 م");
    expect(container.textContent).toContain("Email · 10-01 9:05 م");
  });

  it("lists the delivery log with the state of each, and the reason a send failed", async () => {
    serve(
      task({
        deliveries: [
          { id: 1, at: stamp("10-02 5:00"), channel: "whatsapp", files: 2, by: "Nour", status: "sent", error: "" },
          { id: 2, at: stamp("10-02 5:05"), channel: "email", files: 0, by: null, status: "failed", error: "The server refused" },
        ],
      }),
    );
    open();
    expect((await screen.findByText("sent")).closest(".note")).toHaveClass("note--ok");
    expect(screen.getByText("The server refused").closest(".note")).toHaveClass("note--high");
  });

  it("lists the requirements, the assignment history, and the state of the word count", async () => {
    serve(task({ words: { state: "confirmed", value: 1200 } }));
    const { container } = open();
    expect(await screen.findByText("Formal tone")).toBeInTheDocument();
    expect(screen.getByText("Contractions").closest(".note")).toHaveClass("note--high");
    const history = container.querySelectorAll(".timeline li");
    expect(history).toHaveLength(2);
    expect(within(history[0] as HTMLElement).getByText("استلم")).toHaveClass("badge--ok");
    expect(container.querySelector("#wordCount")).toHaveTextContent("متسجّل");
    expect(container.querySelector("#wordCount .kv .mono")).toHaveTextContent("1200");
  });

  it("is for the operation and the admin: anybody else is sent home without asking for the task", async () => {
    const mocked = serve(task(), {}, "translator");
    open();
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(mocked.calls.some((c) => c.url === DOOR)).toBe(false);
  });

  it("answers the admin too", async () => {
    serve(task(), {}, "admin");
    open();
    expect(await loaded()).toBeInTheDocument();
  });

  it("says the task does not exist for a 404, could not load for a failure, and is loading before that", async () => {
    serve(jsonResponse({ ok: false, error: "not_found" }, 404));
    const first = open();
    expect(await screen.findByRole("alert")).toHaveTextContent("التاسك دي مش موجودة.");
    expect(screen.getByRole("link", { name: /التاسكات/ })).toHaveAttribute("href", "/tasks");
    first.unmount();
    vi.unstubAllGlobals();

    serve(jsonResponse({ ok: false, error: "server" }, 500));
    const second = open();
    expect(await screen.findByRole("alert")).toHaveTextContent("حصلت مشكلة في التحميل.");
    second.unmount();
    vi.unstubAllGlobals();

    serve(new Response(null) as Response);
    vi.stubGlobal("fetch", () => new Promise(() => undefined));
    open();
    await waitFor(() => expect(screen.getByText("بيحمّل...")).toBeInTheDocument());
  });
});

describe("OperationTaskPage: sending a new task to a leader", () => {
  const leads = [
    { id: 10, name: "Mona", online: true, tasks: 2 },
    { id: 11, name: "Hany", online: false, tasks: 0 },
  ];

  it("offers every leader with whether they are here and how many tasks they have, the first chosen", async () => {
    serve(task({ can: { assign_lead: true, take_over: false, deliver: false, cancel: true, add_member: false, new_request: true, set_deadline: true, set_words: true }, leads }));
    open();
    const select = (await screen.findByLabelText("اعمل assign لتيم ليدر")) as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.textContent)).toEqual(["Mona — online · 2 tasks", "Hany — offline · 0 tasks"]);
    expect(select.value).toBe("10");
  });

  it("sends the chosen leader, says so, and reads the task again", async () => {
    const mocked = serve(task({ can: { assign_lead: true, take_over: false, deliver: false, cancel: true, add_member: false, new_request: true, set_deadline: true, set_words: true }, leads }), {
      [A("assign-lead")]: () => {
        mocked.state.task = task({ status: { value: "awaiting_lead", tone: "wait", ar: "بانتظار التيم ليدر", en: "Awaiting team leader" } });
        return jsonResponse({ ok: true, assignment: 5, status: "awaiting_lead" });
      },
    });
    open();
    await userEvent.selectOptions(await screen.findByLabelText("اعمل assign لتيم ليدر"), "11");
    await userEvent.click(screen.getByRole("button", { name: /ابعتها للتيم ليدر/ }));
    expect(await screen.findByText("اتبعت للتيم ليدر")).toBeInTheDocument();
    expect(form(posts(mocked.calls, A("assign-lead"))[0]!)).toEqual({ user: "11" });
    expect(await screen.findByText("بانتظار التيم ليدر")).toBeInTheDocument();
    expect(screen.queryByLabelText("اعمل assign لتيم ليدر")).toBeNull();
  });

  it("sends the first leader when none was chosen", async () => {
    const mocked = serve(task({ can: { assign_lead: true, take_over: false, deliver: false, cancel: true, add_member: false, new_request: true, set_deadline: true, set_words: true }, leads }), {
      [A("assign-lead")]: () => jsonResponse({ ok: true }),
    });
    open();
    await userEvent.click(await screen.findByRole("button", { name: /ابعتها للتيم ليدر/ }));
    await waitFor(() => expect(posts(mocked.calls, A("assign-lead"))).toHaveLength(1));
    expect(form(posts(mocked.calls, A("assign-lead"))[0]!)).toEqual({ user: "10" });
  });

  it("says why when it is refused, and says so when there is nobody to send it to", async () => {
    serve(task({ can: { assign_lead: true, take_over: false, deliver: false, cancel: true, add_member: false, new_request: true, set_deadline: true, set_words: true }, leads }), {
      [A("assign-lead")]: () => jsonResponse({ ok: false, error: "forbidden" }, 403),
    });
    const view = open();
    await userEvent.click(await screen.findByRole("button", { name: /ابعتها للتيم ليدر/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("مش من حقك تعمل ده.");
    view.unmount();
    vi.unstubAllGlobals();
    serve(task({ can: { assign_lead: true, take_over: false, deliver: false, cancel: true, add_member: false, new_request: true, set_deadline: true, set_words: true }, leads: [] }));
    open();
    expect(await screen.findByText("مفيش تيم ليدرز مسجلين تبعتلهم التاسك.")).toBeInTheDocument();
  });

  it("has no box for it once the task is on its way", async () => {
    serve(task());
    open();
    await loaded();
    expect(screen.queryByLabelText("اعمل assign لتيم ليدر")).toBeNull();
  });
});

describe("OperationTaskPage: taking over and delivering", () => {
  const taking = () => task({ status: { value: "reviewed", tone: "ok", ar: "تمت المراجعة", en: "Reviewed" }, can: { assign_lead: false, take_over: true, deliver: false, cancel: true, add_member: false, new_request: true, set_deadline: true, set_words: true } });
  const delivering = (over: Partial<OpsTask> = {}) =>
    task({
      status: { value: "reviewed", tone: "ok", ar: "تمت المراجعة", en: "Reviewed" },
      can: { assign_lead: false, take_over: false, deliver: true, cancel: true, add_member: false, new_request: true, set_deadline: true, set_words: true },
      handover: { by: "Nour", at: stamp("10-02 6:00") },
      deliver: {
        channel: "whatsapp",
        reachable: true,
        files: [
          { id: 5, name: "translated.docx", size: "1.5 KB", sender: "Sam", final: true },
          { id: 6, name: "notes.pdf", size: "1 B", sender: "Mona", final: false },
        ],
      },
      ...over,
    });

  it("asks for the take-over, says why it matters, and asks again before it does it", async () => {
    const mocked = serve(taking(), { [A("ack")]: () => jsonResponse({ ok: true, status: "reviewed" }) });
    open();
    expect(await screen.findByText("التاسك مستنية استلامك")).toBeInTheDocument();
    expect(screen.getByText(/مفيش ملف بيروح للعميل/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /استلمت التاسك/ }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("تأكيد إنك استلمت التاسك من التيم ليدر؟")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "إلغاء" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(posts(mocked.calls, A("ack"))).toHaveLength(0);
  });

  it("takes it over once confirmed, and shows the delivery box when the page is read again", async () => {
    const mocked = serve(taking(), {
      [A("ack")]: () => {
        mocked.state.task = delivering();
        return jsonResponse({ ok: true, status: "reviewed" });
      },
    });
    open();
    await userEvent.click(await screen.findByRole("button", { name: /استلمت التاسك/ }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "أيوه، استلمتها" }));
    expect(await screen.findByText("التاسك مستلمة — تقدر تبعتها للعميل.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(posts(mocked.calls, A("ack"))).toHaveLength(1);
    expect(screen.queryByText("التاسك مستنية استلامك")).toBeNull();
  });

  it("keeps the question open with the reason when the take-over is refused", async () => {
    serve(taking(), { [A("ack")]: () => jsonResponse({ ok: false, status: "reviewed" }) });
    open();
    await userEvent.click(await screen.findByRole("button", { name: /استلمت التاسك/ }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "أيوه، استلمتها" }));
    expect(await within(screen.getByRole("dialog")).findByRole("alert")).toHaveTextContent("مقدرتش أعمل ده.");
  });

  it("shows who took it over and what would go: the translator's files ticked, the rest not, and the channel", async () => {
    serve(delivering());
    const { container } = open();
    expect(await screen.findByText("التاسك مستلمة — تقدر تبعتها للعميل.")).toBeInTheDocument();
    expect(container.querySelector(".note--ok .note__where")).toHaveTextContent("Nour · 10-02 6:00 م");
    const boxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect(boxes.map((b) => b.checked)).toEqual([true, false]);
    expect(screen.getByText("Sam · 1.5 KB")).toBeInTheDocument();
    expect(screen.getByText("WhatsApp")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /ابعت للعميل وسلّم/ })).toBeEnabled();
  });

  it("sends the ticked files, the note and the word to send, then says it was delivered", async () => {
    const mocked = serve(delivering(), { [A("deliver")]: () => jsonResponse({ ok: true, status: "sent", channel: "WhatsApp", files: 2 }) });
    open();
    await screen.findByText("التاسك مستلمة — تقدر تبعتها للعميل.");
    await userEvent.click(screen.getAllByRole("checkbox")[1]!);
    await userEvent.type(screen.getByLabelText("رسالة للعميل"), "  Here you are ");
    await userEvent.click(screen.getByRole("button", { name: /ابعت للعميل وسلّم/ }));
    expect(await screen.findByText("تم التسليم")).toBeInTheDocument();
    const [call] = posts(mocked.calls, A("deliver"));
    expect(parts(call!).getAll("attachments")).toEqual(["5", "6"]);
    expect(parts(call!).get("note")).toBe("Here you are");
    expect(parts(call!).get("send")).toBe("1");
  });

  it("sends only what is ticked", async () => {
    const mocked = serve(delivering(), { [A("deliver")]: () => jsonResponse({ ok: true, status: "sent", channel: "WhatsApp", files: 0 }) });
    open();
    await screen.findByText("التاسك مستلمة — تقدر تبعتها للعميل.");
    await userEvent.click(screen.getAllByRole("checkbox")[0]!);
    await userEvent.click(screen.getByRole("button", { name: /ابعت للعميل وسلّم/ }));
    await waitFor(() => expect(posts(mocked.calls, A("deliver"))).toHaveLength(1));
    expect(parts(posts(mocked.calls, A("deliver"))[0]!).getAll("attachments")).toEqual([]);
  });

  it("says no files are in the chat when there are none, and cannot send to a client nobody can reach", async () => {
    serve(delivering({ deliver: { channel: "email", reachable: false, files: [] } }));
    open();
    expect(await screen.findByText("مفيش ملفات في الشات — هيتبعت النص بس.")).toBeInTheDocument();
    expect(screen.getByText("مفيش رقم ولا إيميل للعميل")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /ابعت للعميل وسلّم/ })).toBeDisabled();
  });

  it("says why when the send is refused, and does not say it was delivered", async () => {
    serve(delivering(), { [A("deliver")]: () => jsonResponse({ ok: false, error: "الملف كبير على واتساب", status: "failed", channel: "WhatsApp", files: 1 }, 400) });
    open();
    await screen.findByText("التاسك مستلمة — تقدر تبعتها للعميل.");
    await userEvent.click(screen.getByRole("button", { name: /ابعت للعميل وسلّم/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("الملف كبير على واتساب");
    expect(screen.queryByText("تم التسليم")).toBeNull();
    expect(screen.getByRole("button", { name: /ابعت للعميل وسلّم/ })).toBeEnabled();
  });

  it("is not sure, rather than failed, when nothing came back from a send", async () => {
    serve(delivering(), { [A("deliver")]: () => Promise.reject(new TypeError("network down")) });
    open();
    await screen.findByText("التاسك مستلمة — تقدر تبعتها للعميل.");
    await userEvent.click(screen.getByRole("button", { name: /ابعت للعميل وسلّم/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/مش متأكدين/);
  });

  it("asks before it closes without sending, and then sends nothing at all", async () => {
    const mocked = serve(delivering(), { [A("deliver")]: () => jsonResponse({ ok: true, status: "closed", channel: "", files: 0 }) });
    open();
    await screen.findByText("التاسك مستلمة — تقدر تبعتها للعميل.");
    await userEvent.type(screen.getByLabelText("رسالة للعميل"), "must not be sent");
    await userEvent.click(screen.getByRole("button", { name: "قفل التاسك من غير إرسال" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("تقفل التاسك من غير ما تبعت للعميل؟")).toBeInTheDocument();
    expect(posts(mocked.calls, A("deliver"))).toHaveLength(0);
    await userEvent.click(within(dialog).getByRole("button", { name: "اقفلها" }));
    await waitFor(() => expect(posts(mocked.calls, A("deliver"))).toHaveLength(1));
    const call = posts(mocked.calls, A("deliver"))[0]!;
    expect(parts(call).get("send")).toBe("0");
    expect(parts(call).getAll("attachments")).toEqual([]);
    expect(parts(call).get("note")).toBe("");
  });

  it("has neither box before the job is reviewed", async () => {
    serve(task());
    open();
    await loaded();
    expect(screen.queryByText("التاسك مستنية استلامك")).toBeNull();
    expect(screen.queryByText("الملفات اللي هتتبعت للعميل")).toBeNull();
  });
});

describe("OperationTaskPage: the deadline, the group, cancelling", () => {
  const boxes = () => within(document.querySelector(".dur") as HTMLElement).getAllByRole("spinbutton");

  it("cannot save while nothing is typed, and sends only what was typed once something is", async () => {
    const mocked = serve(task(), { [A("deadline")]: () => jsonResponse({ ok: true }) });
    open();
    await loaded();
    const save = screen.getByRole("button", { name: "حفظ الديدلاين" });
    expect(save).toBeDisabled();
    await userEvent.type(boxes()[0]!, "3");
    await userEvent.type(boxes()[1]!, "12");
    expect(save).toBeEnabled();
    await userEvent.click(save);
    expect(await screen.findByText("الديدلاين اتحفظ")).toBeInTheDocument();
    expect(form(posts(mocked.calls, A("deadline"))[0]!)).toEqual({ deadline_days: "3", deadline_hours: "12", deadline_minutes: "" });
    // The boxes are empty again: leave it as it is.
    expect(boxes().map((b) => (b as HTMLInputElement).value)).toEqual(["", "", ""]);
    expect(screen.getByRole("button", { name: "حفظ الديدلاين" })).toBeDisabled();
  });

  it("sends zeros as zeros: that is how the deadline is cleared", async () => {
    const mocked = serve(task(), { [A("deadline")]: () => jsonResponse({ ok: true }) });
    open();
    await loaded();
    await userEvent.type(boxes()[0]!, "0");
    await userEvent.click(screen.getByRole("button", { name: "حفظ الديدلاين" }));
    await waitFor(() => expect(posts(mocked.calls, A("deadline"))).toHaveLength(1));
    expect(form(posts(mocked.calls, A("deadline"))[0]!)).toEqual({ deadline_days: "0", deadline_hours: "", deadline_minutes: "" });
  });

  it("says the server's own words when the deadline is refused, and keeps what was typed", async () => {
    serve(task(), { [A("deadline")]: () => jsonResponse({ ok: false, error: "bad_date", detail: "مفيش ديدلاين بالسالب." }, 400) });
    open();
    await loaded();
    await userEvent.type(boxes()[0]!, "5");
    await userEvent.click(screen.getByRole("button", { name: "حفظ الديدلاين" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("مفيش ديدلاين بالسالب.");
    expect((boxes()[0] as HTMLInputElement).value).toBe("5");
  });

  it("has no add-to-the-group box for the operation", async () => {
    serve(task());
    open();
    await loaded();
    expect(screen.queryByLabelText("ضيف حد لجروب التاسك")).toBeNull();
  });

  it("lets the admin add somebody to the group, from those who are not in it", async () => {
    const mocked = serve(
      task({ can: { assign_lead: false, take_over: false, deliver: false, cancel: true, add_member: true, new_request: true, set_deadline: true, set_words: true }, group_candidates: [{ id: 21, name: "Nadia", role: "operation" }, { id: 22, name: "Omar", role: "team_lead" }] }),
      { [A("add-member")]: () => jsonResponse({ ok: true }) },
      "admin",
    );
    open();
    await userEvent.selectOptions(await screen.findByLabelText("ضيف حد لجروب التاسك"), "22");
    await userEvent.click(screen.getByRole("button", { name: "ضيف" }));
    expect(await screen.findByText("اتضاف للجروب")).toBeInTheDocument();
    expect(form(posts(mocked.calls, A("add-member"))[0]!)).toEqual({ user: "22" });
  });

  it("asks before it cancels, cancels once confirmed, and is not there for a finished task", async () => {
    const mocked = serve(task(), {
      [A("cancel")]: () => {
        mocked.state.task = task({ can: { assign_lead: false, take_over: false, deliver: false, cancel: false, add_member: false, new_request: true, set_deadline: true, set_words: true } });
        return jsonResponse({ ok: true, status: "cancelled" });
      },
    });
    open();
    await userEvent.click(await screen.findByRole("button", { name: /إلغاء التاسك/ }));
    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "إلغاء" }));
    expect(posts(mocked.calls, A("cancel"))).toHaveLength(0);
    await userEvent.click(screen.getByRole("button", { name: /إلغاء التاسك/ }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "ألغي التاسك" }));
    expect(await screen.findByText("التاسك اتلغت")).toBeInTheDocument();
    expect(posts(mocked.calls, A("cancel"))).toHaveLength(1);
    await waitFor(() => expect(screen.queryByRole("button", { name: /إلغاء التاسك/ })).toBeNull());
  });

  it("says why a cancel was refused and keeps the question open", async () => {
    serve(task(), { [A("cancel")]: () => jsonResponse({ ok: false, error: "forbidden" }, 403) });
    open();
    await userEvent.click(await screen.findByRole("button", { name: /إلغاء التاسك/ }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "ألغي التاسك" }));
    expect(await within(screen.getByRole("dialog")).findByRole("alert")).toHaveTextContent("مش من حقك تعمل ده.");
  });
});

describe("OperationTaskPage: the word count and the requirements", () => {
  const WORDS = `/api/v1/tasks/${CODE}/words/`;
  const REQ = `/api/v1/tasks/${CODE}/requirements/`;

  it("says it is not set, cannot save what is not a whole number, and saves one", async () => {
    const mocked = serve(task(), {
      [WORDS]: () => {
        mocked.state.task = task({ words: { state: "confirmed", value: 1500 } });
        return jsonResponse({ ok: true, words: 1500, state: "confirmed" });
      },
    });
    open();
    expect(await screen.findByText("لسه متكتبش")).toBeInTheDocument();
    const save = within(document.querySelector("#wordCount") as HTMLElement).getByRole("button", { name: "حفظ" });
    expect(save).toBeDisabled();
    const input = screen.getByLabelText("عدد الكلمات", { selector: "input" });
    await userEvent.type(input, "-5");
    expect(save).toBeDisabled();
    await userEvent.clear(input);
    await userEvent.type(input, "1500");
    await userEvent.click(save);
    expect(await screen.findByText("عدد الكلمات اتسجّل")).toBeInTheDocument();
    expect(JSON.parse(String(posts(mocked.calls, WORDS)[0]!.init!.body))).toEqual({ words: 1500 });
    expect(await screen.findByText("متسجّل")).toBeInTheDocument();
  });

  it("shows the number that is set in the box, ready to change", async () => {
    serve(task({ words: { state: "confirmed", value: 1200 } }));
    open();
    await loaded();
    expect((screen.getByLabelText("عدد الكلمات", { selector: "input" }) as HTMLInputElement).value).toBe("1200");
  });

  it("says why when the number is refused", async () => {
    serve(task(), { [WORDS]: () => jsonResponse({ ok: false, error: "bad_words" }, 400) });
    open();
    await loaded();
    await userEvent.type(screen.getByLabelText("عدد الكلمات", { selector: "input" }), "100");
    await userEvent.click(within(document.querySelector("#wordCount") as HTMLElement).getByRole("button", { name: "حفظ" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("اكتب رقم صحيح.");
  });

  it("adds a requirement of the kind chosen, trimmed, and empties the box", async () => {
    const mocked = serve(task(), { [REQ]: () => jsonResponse({ ok: true, requirement: { id: 9 } }) });
    open();
    await loaded();
    const add = screen.getByRole("button", { name: /ضيف متطلب/ });
    expect(add).toBeDisabled();
    await userEvent.selectOptions(screen.getByLabelText("النوع"), "dislike");
    await userEvent.type(screen.getByLabelText("المتطلب"), "  No passive voice ");
    await userEvent.click(add);
    expect(await screen.findByText("المتطلب اتضاف")).toBeInTheDocument();
    expect(JSON.parse(String(posts(mocked.calls, REQ)[0]!.init!.body))).toEqual({ kind: "dislike", text: "No passive voice" });
    expect((screen.getByLabelText("المتطلب") as HTMLTextAreaElement).value).toBe("");
  });

  it("says why a requirement was refused and keeps what was typed", async () => {
    serve(task(), { [REQ]: () => jsonResponse({ ok: false, error: "bad_requirement", fields: ["text"] }, 400) });
    open();
    await loaded();
    await userEvent.type(screen.getByLabelText("المتطلب"), "x");
    await userEvent.click(screen.getByRole("button", { name: /ضيف متطلب/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("اكتب المتطلب.");
    expect((screen.getByLabelText("المتطلب") as HTMLTextAreaElement).value).toBe("x");
  });

  it("carries the CSRF token on a write", async () => {
    document.cookie = "csrftoken=tok123";
    const mocked = serve(task(), { [REQ]: () => jsonResponse({ ok: true }) });
    open();
    await loaded();
    await userEvent.type(screen.getByLabelText("المتطلب"), "x");
    fireEvent.click(screen.getByRole("button", { name: /ضيف متطلب/ }));
    await waitFor(() => expect(posts(mocked.calls, REQ)).toHaveLength(1));
    expect(new Headers(posts(mocked.calls, REQ)[0]!.init!.headers).get("X-CSRFToken")).toBe("tok123");
    document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });
});

describe("OperationTaskPage: the AI's notes", () => {
  const AI = `/api/v1/tasks/${CODE}/ai-notes/`;
  const notes = (over: object = {}) => ({
    ok: true,
    task: { code: CODE, title: "Contract for review" },
    can_recheck: true,
    check: { id: 3, status: "issues", count: 1, at: stamp("10-02 5:30"), automatic: true, old: false, summary: "One thing.", error: "" },
    issues: [{ severity: "high", location: "page 2", category: null, source: "s", translation: "t", compared: true, text: { ar: "غلط", en: "Wrong" }, meaning: "" }],
    ...over,
  });

  it("is open at the top of the page for the admin, who reviews", async () => {
    const mocked = serve(task(), { [AI]: () => jsonResponse(notes()) }, "admin");
    open();
    expect(await screen.findByText("ملاحظات الـ AI على الترجمة")).toBeInTheDocument();
    expect(screen.getByText("One thing.")).toBeInTheDocument();
    const box = document.querySelector("#aiNotes") as HTMLElement;
    const title = screen.getByText(/Contract for review/, { selector: "h2" });
    // Above the task's own card: the box is the first thing the reviewer reads.
    expect(box.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(mocked.calls.some((call) => call.url === AI)).toBe(true);
  });

  it("is not asked for, and not drawn, for the operation: it is not theirs to read", async () => {
    const mocked = serve(task(), { [AI]: () => jsonResponse(notes()) }, "operation");
    open();
    await loaded();
    expect(mocked.calls.some((call) => call.url === AI)).toBe(false);
    expect(document.querySelector("#aiNotes")).toBeNull();
  });

  it("is not drawn for the admin when no check has run", async () => {
    serve(task(), { [AI]: () => jsonResponse(notes({ check: null, issues: [] })) }, "admin");
    open();
    await loaded();
    expect(document.querySelector("#aiNotes")).toBeNull();
  });
});

describe("OperationTaskPage: the team leader's page", () => {
  const LEADER_CAN = { assign_lead: false, take_over: false, deliver: false, cancel: false, add_member: false, new_request: false, set_deadline: false, set_words: true };
  const tools = (over: object = {}) => ({
    can_assign: false,
    translators: [],
    can_set_translator_deadline: false,
    can_review: false,
    client_due: stamp("10-30 5:30"),
    extension: null,
    ...over,
  });
  const leaderTask = (lead: object, over: Partial<OpsTask> = {}) =>
    task({ can: LEADER_CAN, lead: tools(lead), client_chat_url: null, messages: [], leads: [], ...over } as Partial<OpsTask>);
  const AI = `/api/v1/tasks/${CODE}/ai-notes/`;
  const form = (call: { init?: RequestInit }) => Object.fromEntries(new URLSearchParams(String(call.init?.body)));
  const calls = (mocked: { calls: { url: string; init?: RequestInit }[] }, path: string) => mocked.calls.filter((call) => call.url === path && call.init?.method === "POST");

  it("is open to the leader, with none of the operation's tools: no new request, no client date, no cancel", async () => {
    serve(leaderTask({}), {}, "team_lead");
    open();
    await loaded();
    expect(screen.queryByRole("link", { name: /طلب جديد على نفس الملفات/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "حفظ الديدلاين" })).toBeNull();
    expect(screen.queryByRole("button", { name: "إلغاء التاسك" })).toBeNull();
    // Nothing for the leader to do on this task now: there is no card of actions at all.
    expect(screen.queryByText("الإجراءات")).toBeNull();
    // But the word count is theirs to settle.
    expect(screen.getByText("عدد الكلمات", { selector: "h3" })).toBeInTheDocument();
  });

  it("asks for the AI's notes, which are the leader's to read", async () => {
    const mocked = serve(leaderTask({}), { [AI]: () => jsonResponse({ ok: true, task: { code: CODE, title: "x" }, can_recheck: false, check: null, issues: [] }) }, "team_lead");
    open();
    await loaded();
    await waitFor(() => expect(mocked.calls.some((call) => call.url === AI)).toBe(true));
  });

  it("hides the word count from a person who may not settle it", async () => {
    serve(leaderTask({}, { can: { ...LEADER_CAN, set_words: false } }), {}, "team_lead");
    open();
    await loaded();
    expect(screen.queryByText("عدد الكلمات")).toBeNull();
  });

  describe("giving it to a translator", () => {
    const TRANSLATORS = [
      { id: 21, name: "Nada", state: "free", rating: 4.5 },
      { id: 22, name: "Sam", state: "busy", rating: 3.25 },
      { id: 23, name: "Ola", state: "off", rating: 5 },
    ];
    const waiting = () => leaderTask({ can_assign: true, translators: TRANSLATORS }, { translator_due: null, people: { operation: "Nour", team_lead: "Mona", translator: null } });

    it("offers the leader's own team, each with whether they are free, the first one chosen", async () => {
      serve(waiting(), {}, "team_lead");
      open();
      const select = await screen.findByLabelText("اعمل assign لمترجم من فريقك");
      expect(select).toHaveValue("21");
      expect(Array.from(select.querySelectorAll("option")).map((option) => option.textContent)).toEqual([
        "Nada — فاضي · 4.50",
        "Sam — مشغول · 3.25",
        "Ola — أوفلاين · 5.00",
      ]);
    });

    it("sends the translator chosen and the leader's own date, as the classic form does", async () => {
      const user = userEvent.setup();
      const mocked = serve(waiting(), { [A("assign-translator")]: () => jsonResponse({ ok: true, assignment: 5, status: "awaiting_translator" }) }, "team_lead");
      open();
      await user.selectOptions(await screen.findByLabelText("اعمل assign لمترجم من فريقك"), "22");
      await user.type(screen.getByLabelText("الديدلاين اللي هتديه للمترجم - يوم"), "2");
      await user.type(screen.getByLabelText("الديدلاين اللي هتديه للمترجم - ساعة"), "3");
      await user.click(screen.getByRole("button", { name: "ابعتها للمترجم" }));
      expect(await screen.findByText("اتبعتت للمترجم")).toBeInTheDocument();
      expect(form(calls(mocked, A("assign-translator"))[0]!)).toEqual({ user: "22", tdeadline_days: "2", tdeadline_hours: "3", tdeadline_minutes: "" });
    });

    it("sends empty boxes when the leader gives no date of their own: the client's date is then the translator's", async () => {
      const user = userEvent.setup();
      const mocked = serve(waiting(), { [A("assign-translator")]: () => jsonResponse({ ok: true }) }, "team_lead");
      open();
      await user.click(await screen.findByRole("button", { name: "ابعتها للمترجم" }));
      await waitFor(() => expect(calls(mocked, A("assign-translator"))).toHaveLength(1));
      expect(form(calls(mocked, A("assign-translator"))[0]!)).toEqual({ user: "21", tdeadline_days: "", tdeadline_hours: "", tdeadline_minutes: "" });
    });

    it("reminds the leader of the client's date, and of the review time a shorter one keeps", async () => {
      serve(waiting(), {}, "team_lead");
      open();
      await screen.findByLabelText("اعمل assign لمترجم من فريقك");
      expect(screen.getByText(/شيل لنفسك وقت للمراجعة/)).toBeInTheDocument();
      expect(screen.getByTitle("ديدلاين العميل")).toHaveTextContent("10-30 5:30 م");
    });

    it("says why it was refused, in the server's own words, and keeps what was typed", async () => {
      const user = userEvent.setup();
      serve(waiting(), { [A("assign-translator")]: () => jsonResponse({ ok: false, error: "الديدلاين ده أبعد من ديدلاين العميل." }, 400) }, "team_lead");
      open();
      const days = await screen.findByLabelText("الديدلاين اللي هتديه للمترجم - يوم");
      await user.type(days, "9");
      await user.click(screen.getByRole("button", { name: "ابعتها للمترجم" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("الديدلاين ده أبعد من ديدلاين العميل.");
      expect(days).toHaveValue(9);
    });

    it("says there is nobody to send it to when the leader has no team", async () => {
      serve(leaderTask({ can_assign: true, translators: [] }), {}, "team_lead");
      open();
      expect(await screen.findByText("مفيش مترجمين تحتك تبعتلهم التاسك.")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "ابعتها للمترجم" })).toBeNull();
    });

    it("is not offered once a translator has it", async () => {
      serve(leaderTask({ can_assign: false, can_set_translator_deadline: true }), {}, "team_lead");
      open();
      await loaded();
      expect(screen.queryByRole("button", { name: "ابعتها للمترجم" })).toBeNull();
    });

    it("sends one request for two presses", async () => {
      const user = userEvent.setup();
      let release: (() => void) | undefined;
      const mocked = serve(waiting(), { [A("assign-translator")]: () => new Promise<Response>((resolve) => (release = () => resolve(jsonResponse({ ok: true })))) }, "team_lead");
      open();
      const button = await screen.findByRole("button", { name: "ابعتها للمترجم" });
      await user.click(button);
      await user.click(button);
      expect(calls(mocked, A("assign-translator"))).toHaveLength(1);
      release?.();
    });
  });

  describe("the translator's own date", () => {
    it("is changed with the same three boxes, only once something is typed", async () => {
      const user = userEvent.setup();
      const mocked = serve(leaderTask({ can_set_translator_deadline: true }), { [A("translator-deadline")]: () => jsonResponse({ ok: true }) }, "team_lead");
      open();
      const save = await screen.findByRole("button", { name: "حفظ ديدلاين المترجم" });
      expect(save).toBeDisabled();
      await user.type(screen.getByLabelText("ديدلاين المترجم - ساعة"), "5");
      expect(save).toBeEnabled();
      await user.click(save);
      expect(await screen.findByText("ديدلاين المترجم اتحفظ")).toBeInTheDocument();
      expect(form(calls(mocked, A("translator-deadline"))[0]!)).toEqual({ tdeadline_days: "", tdeadline_hours: "5", tdeadline_minutes: "" });
      // The boxes are empty again: blank means "leave it alone".
      expect(screen.getByLabelText("ديدلاين المترجم - ساعة")).toHaveValue(null);
    });

    it("says what the translator has now, and what zeros do", async () => {
      serve(leaderTask({ can_set_translator_deadline: true }), {}, "team_lead");
      open();
      await screen.findByRole("button", { name: "حفظ ديدلاين المترجم" });
      expect(screen.getByText(/أصفار يعني المترجم يشتغل على ديدلاين العميل/)).toBeInTheDocument();
      expect(screen.getAllByText(/10-28 3:00 م/).length).toBeGreaterThan(0);
    });

    it("says why it was refused", async () => {
      const user = userEvent.setup();
      serve(leaderTask({ can_set_translator_deadline: true }), { [A("translator-deadline")]: () => jsonResponse({ ok: false, error: "مفيش ديدلاين بالسالب." }, 400) }, "team_lead");
      open();
      await user.type(await screen.findByLabelText("ديدلاين المترجم - يوم"), "3");
      await user.click(screen.getByRole("button", { name: "حفظ ديدلاين المترجم" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("مفيش ديدلاين بالسالب.");
    });
  });

  describe("a request for more time", () => {
    const asked = () => leaderTask({ extension: { id: 7, length: "يوم و3 ساعات", reason: "The file is long", new_due: stamp("11-01 3:00") } });

    it("is read with the length, why, and where the translator's date would land beside the client's", async () => {
      serve(asked(), {}, "team_lead");
      open();
      expect(await screen.findByText("المترجم طالب وقت إضافي")).toBeInTheDocument();
      expect(screen.getByText("يوم و3 ساعات — The file is long")).toBeInTheDocument();
      const dates = screen.getByText("ديدلاينه هيبقى").closest("div") as HTMLElement;
      expect(dates).toHaveTextContent("11-01 3:00 م");
      expect(dates).toHaveTextContent("العميل 10-30 5:30 م");
    });

    it("is approved with one press", async () => {
      const user = userEvent.setup();
      const mocked = serve(asked(), { "/api/extensions/7/approve/": () => jsonResponse({ ok: true }) }, "team_lead");
      open();
      await user.click(await screen.findByRole("button", { name: "موافق" }));
      expect(await screen.findByText("وافقت على الوقت الإضافي")).toBeInTheDocument();
      expect(calls(mocked, "/api/extensions/7/approve/")).toHaveLength(1);
    });

    it("is declined only after asking, and not at all if the leader says no", async () => {
      const user = userEvent.setup();
      const mocked = serve(asked(), { "/api/extensions/7/decline/": () => jsonResponse({ ok: true }) }, "team_lead");
      open();
      await user.click(await screen.findByRole("button", { name: "رفض" }));
      expect(screen.getByText("ترفض الوقت الإضافي؟")).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "إلغاء" }));
      expect(calls(mocked, "/api/extensions/7/decline/")).toHaveLength(0);
      await user.click(screen.getByRole("button", { name: "رفض" }));
      await user.click(screen.getByRole("button", { name: "أيوه، ارفض" }));
      expect(await screen.findByText("رفضت الوقت الإضافي")).toBeInTheDocument();
      expect(calls(mocked, "/api/extensions/7/decline/")).toHaveLength(1);
    });

    it("says why an answer was refused and leaves the request where it was", async () => {
      const user = userEvent.setup();
      serve(asked(), { "/api/extensions/7/approve/": () => jsonResponse({ ok: false, error: "التاسك دي اتقفلت." }, 400) }, "team_lead");
      open();
      await user.click(await screen.findByRole("button", { name: "موافق" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("التاسك دي اتقفلت.");
      expect(screen.getByText("المترجم طالب وقت إضافي")).toBeInTheDocument();
    });

    it("is not drawn when nobody has asked", async () => {
      serve(leaderTask({ can_set_translator_deadline: true }), {}, "team_lead");
      open();
      await screen.findByRole("button", { name: "حفظ ديدلاين المترجم" });
      expect(screen.queryByText("المترجم طالب وقت إضافي")).toBeNull();
    });
  });

  describe("the review", () => {
    it("is finished after asking, and goes on to the operation", async () => {
      const user = userEvent.setup();
      const mocked = serve(leaderTask({ can_review: true }), { [A("reviewed")]: () => jsonResponse({ ok: true }) }, "team_lead");
      open();
      await user.click(await screen.findByRole("button", { name: "تمت المراجعة" }));
      expect(screen.getByText("تأكيد إن المراجعة خلصت؟")).toBeInTheDocument();
      expect(calls(mocked, A("reviewed"))).toHaveLength(0);
      await user.click(screen.getByRole("button", { name: "أيوه، خلصت" }));
      expect(await screen.findByText("المراجعة خلصت")).toBeInTheDocument();
      expect(calls(mocked, A("reviewed"))).toHaveLength(1);
    });

    it("can be put off with no after-effect", async () => {
      const user = userEvent.setup();
      const mocked = serve(leaderTask({ can_review: true }), { [A("reviewed")]: () => jsonResponse({ ok: true }) }, "team_lead");
      open();
      await user.click(await screen.findByRole("button", { name: "تمت المراجعة" }));
      await user.click(screen.getByRole("button", { name: "إلغاء" }));
      expect(calls(mocked, A("reviewed"))).toHaveLength(0);
    });

    it("says why it was refused", async () => {
      const user = userEvent.setup();
      serve(leaderTask({ can_review: true }), { [A("reviewed")]: () => jsonResponse({ ok: false, error: "حالة التاسك دلوقتي مش بتسمح بده." }, 400) }, "team_lead");
      open();
      await user.click(await screen.findByRole("button", { name: "تمت المراجعة" }));
      await user.click(screen.getByRole("button", { name: "أيوه، خلصت" }));
      expect(await screen.findAllByText("حالة التاسك دلوقتي مش بتسمح بده.")).not.toHaveLength(0);
    });

    it("is not offered while the task is not under review", async () => {
      serve(leaderTask({ can_review: false, can_set_translator_deadline: true }), {}, "team_lead");
      open();
      await screen.findByRole("button", { name: "حفظ ديدلاين المترجم" });
      expect(screen.queryByRole("button", { name: "تمت المراجعة" })).toBeNull();
    });
  });

  it("gives the admin both sets: the operation's tools and the leader's", async () => {
    serve(
      task({
        can: { ...LEADER_CAN, cancel: true, new_request: true, set_deadline: true },
        lead: tools({ can_set_translator_deadline: true, can_review: true }),
      } as Partial<OpsTask>),
      {},
      "admin",
    );
    open();
    await loaded();
    expect(screen.getByRole("button", { name: "إلغاء التاسك" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "حفظ الديدلاين" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "حفظ ديدلاين المترجم" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "تمت المراجعة" })).toBeInTheDocument();
  });
});
