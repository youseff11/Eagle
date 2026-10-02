import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Role, TranslatorTask } from "../api/types";
import { ToastProvider } from "../components/Toasts";
import { jsonResponse, me, mockFetch, renderWithProviders, type Routes as FetchRoutes } from "../test/helpers";
import { TaskPage } from "./TaskPage";

afterEach(() => vi.unstubAllGlobals());

const CODE = "TSK-00001";
const TASK = `/api/v1/translator/tasks/${CODE}/`;
const stamp = (text: string) => ({ ar: `${text} م`, en: `${text} PM` });

function task(overrides: Partial<TranslatorTask> = {}): TranslatorTask {
  return {
    code: CODE,
    title: "Contract for review",
    status: { value: "in_progress", tone: "work", ar: "شغل جاري", en: "In progress" },
    priority: { value: "high", ar: "عالية", en: "High" },
    origin: { value: "whatsapp", icon: "message", ar: "واتساب", en: "WhatsApp" },
    client: "CL-0001",
    source_lang: "English",
    target_lang: "Arabic",
    due: { ar: "2026-10-02 5:30 م", en: "2026-10-02 5:30 PM" },
    due_state: "ok",
    description: "Translate pages 2-4\nKeep the table",
    people: { operation: "Nour", team_lead: "Mona", translator: "Sam" },
    mine: true,
    files: {
      original: [
        { id: 1, url: "/files/in/contract.pdf", name: "contract.pdf", size: "2.0 KB", image: false },
        { id: 2, url: "/files/in/photo.png", name: "photo.png", size: "10 B", image: true },
      ],
      translation: [],
    },
    can_upload: true,
    translation_missing: true,
    under_review: false,
    extension: { can_ask: true, pending: null, last: null },
    chat: { url: "/ops/chats/g/7/", label_ar: "افتح الجروب", label_en: "Open the group" },
    requirements: [
      { id: 1, kind: { value: "like", ar: "بيحب", en: "Likes" }, author: "Nour", text: "Formal tone" },
      { id: 2, kind: { value: "dislike", ar: "بيكره", en: "Dislikes" }, author: null, text: "Contractions" },
    ],
    history: [
      { id: 1, name: "Mona", initials: "MS", role: "team_lead", at: stamp("10-01 9:00"), status: "accepted" },
      { id: 2, name: "Sam", initials: "SM", role: "translator", at: stamp("10-01 9:30"), status: "pending" },
    ],
    ai: { visible: true, enabled: false, checks: [] },
    ...overrides,
  };
}

/** The server's state: an action changes it, and the next read of the page sees the change. */
function serve(initial: TranslatorTask | Response, extra: FetchRoutes = {}, role: Role = "translator") {
  const state = { task: initial instanceof Response ? null : initial };
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role, is_admin: role === "admin" })),
    [TASK]: () => (initial instanceof Response ? initial : jsonResponse({ ok: true, task: state.task })),
    ...extra,
  });
  vi.stubGlobal("fetch", mocked.fn);
  return { ...mocked, state };
}

function open(route = `/tasks/${CODE}`, lang: "ar" | "en" = "ar") {
  return renderWithProviders(
    <ToastProvider>
      <Routes>
        <Route path="/tasks/:code" element={<TaskPage />} />
        <Route path="/translator" element={<div>desk page</div>} />
        <Route path="/" element={<div>home page</div>} />
      </Routes>
    </ToastProvider>,
    { route, lang },
  );
}

/** The page is drawn: the heading with the code is there while it loads, the title is not. */
const loaded = () => screen.findByText(/Contract for review/);

const posts = (calls: { url: string; init?: RequestInit }[], path: string) =>
  calls.filter((c) => c.url.startsWith(path) && c.init?.method === "POST");
const formBody = (call: { init?: RequestInit }) => Object.fromEntries(new URLSearchParams(String(call.init?.body)));

describe("TaskPage: what the translator reads", () => {
  it("shows the task as the classic page does, with the translator's own date", async () => {
    const { calls } = serve(task());
    const { container } = open();
    expect(await screen.findByText("Contract for review", { exact: false })).toBeInTheDocument();
    expect(calls.some((c) => c.url === TASK)).toBe(true);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(CODE);
    expect(screen.getByText("شغل جاري").closest(".badge")).not.toBeNull();
    expect(screen.getByText("عالية")).toHaveClass("badge--prio-high");
    expect(screen.getByText("واتساب")).toBeInTheDocument();
    expect(screen.getByText("2026-10-02 5:30 م").closest(".deadline--ok")).not.toBeNull();
    expect(container.textContent).toContain("CL-0001 · English → Arabic");
    for (const name of ["Nour", "Mona", "Sam"]) expect(within(container).getAllByText(name).length).toBeGreaterThan(0);
    // The brief keeps its line breaks.
    const brief = screen.getByText(/Translate pages 2-4/);
    expect(brief).toHaveStyle({ whiteSpace: "pre-wrap" });
    expect(brief.textContent).toBe("Translate pages 2-4\nKeep the table");
  });

  it("speaks English when asked", async () => {
    serve(task());
    open(`/tasks/${CODE}`, "en");
    expect(await screen.findByText("In progress")).toBeInTheDocument();
    expect(screen.getByText("2026-10-02 5:30 PM")).toBeInTheDocument();
    expect(screen.getByText("Original (from the client)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Finished/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open the group/ })).toBeInTheDocument();
  });

  it("says there is no deadline when there is none", async () => {
    serve(task({ due: null, due_state: "none" }));
    const { container } = open();
    await loaded();
    expect(screen.getByText("من غير ديدلاين").closest(".deadline--none")).not.toBeNull();
    expect(container.querySelector(".deadline--ok")).toBeNull();
  });

  it("lists the original files as links that open on their own and the pictures as pictures", async () => {
    serve(task());
    const { container } = open();
    const pdf = await screen.findByRole("link", { name: /contract\.pdf/ });
    expect(pdf).toHaveAttribute("href", "/files/in/contract.pdf");
    expect(pdf).toHaveAttribute("target", "_blank");
    expect(pdf.getAttribute("rel")).toContain("noopener");
    const picture = container.querySelector('a.task-thumb img[alt="photo.png"]') as HTMLImageElement;
    expect(picture.getAttribute("src")).toBe("/files/in/photo.png");
    expect(picture.getAttribute("loading")).toBe("lazy");
    expect(screen.getByText("الملف الأصلي (من العميل)").parentElement).toHaveTextContent("2");
  });

  it("draws a file link only for an address on this site, and still names the file", async () => {
    serve(
      task({
        files: {
          original: [
            { id: 1, url: "https://evil.example/a.pdf", name: "outside.pdf", size: "1 B", image: false },
            { id: 2, url: "javascript:alert(1)", name: "script.pdf", size: "1 B", image: false },
            { id: 3, url: "//evil.example/b.png", name: "protocol.png", size: "1 B", image: true },
          ],
          translation: [],
        },
      }),
    );
    const { container } = open();
    expect(await screen.findByText("outside.pdf")).toBeInTheDocument();
    expect(screen.getByText("script.pdf")).toBeInTheDocument();
    expect(container.querySelector(".task-files a")).toBeNull();
    expect(container.querySelector(".task-files img")).toBeNull();
  });

  it("lists what the translator handed in, with when, and says so when nothing is there yet", async () => {
    serve(
      task({
        files: {
          original: [],
          translation: [{ id: 9, url: "/files/out/translated.docx", name: "translated.docx", size: "1.5 KB", image: false, at: stamp("10-02 4:10") }],
        },
        translation_missing: false,
      }),
    );
    open();
    const link = await screen.findByRole("link", { name: /translated\.docx/ });
    expect(link).toHaveAttribute("href", "/files/out/translated.docx");
    expect(link).toHaveTextContent("10-02 4:10 م");
    expect(link).toHaveAttribute("title", "1.5 KB · 10-02 4:10 م");
  });

  it("says the translation has not been uploaded when it has not", async () => {
    serve(task());
    open();
    expect(await screen.findByText("المترجم لسه مارفعش ملف الترجمة.")).toBeInTheDocument();
  });

  it("links to the group with the leader, only for an address on this site", async () => {
    serve(task());
    open();
    expect(await screen.findByRole("link", { name: /افتح الجروب/ })).toHaveAttribute("href", "/ops/chats/g/7/");
  });

  it("draws no chat link when there is none or it is not on this site", async () => {
    serve(task({ chat: null }));
    open();
    await loaded();
    expect(screen.queryByRole("link", { name: /افتح الجروب/ })).toBeNull();
    vi.unstubAllGlobals();
  });

  it("does not follow a chat address that leaves the site", async () => {
    serve(task({ chat: { url: "https://evil.example/", label_ar: "افتح الجروب", label_en: "Open" } }));
    open();
    await loaded();
    expect(screen.queryByRole("link", { name: /افتح الجروب/ })).toBeNull();
  });

  it("lists the client's requirements with their kind, and the assignment history with who took it", async () => {
    serve(task());
    const { container } = open();
    expect(await screen.findByText("Formal tone")).toBeInTheDocument();
    expect(screen.getByText("Contractions").closest(".note")).toHaveClass("note--high");
    expect(screen.getByText(/بيحب · Nour/)).toBeInTheDocument();
    expect(screen.getByText(/بيكره · —/)).toBeInTheDocument();
    const history = container.querySelectorAll(".timeline li");
    expect(history).toHaveLength(2);
    expect(history[0]).toHaveTextContent("MS");
    expect(history[0]).toHaveTextContent("تيم ليدر");
    expect(within(history[0] as HTMLElement).getByText("استلم")).toHaveClass("badge--ok");
    expect(within(history[1] as HTMLElement).getByText("مستني")).toHaveClass("badge--wait");
  });

  it("says so when there are no requirements and no assignments", async () => {
    serve(task({ requirements: [], history: [] }));
    open();
    expect(await screen.findByText("مفيش متطلبات مسجلة لحد دلوقتي.")).toBeInTheDocument();
    expect(screen.getByText("لسه مفيش توزيع.")).toBeInTheDocument();
  });

  it("is for translators and the admin: anybody else is sent home without asking for the task", async () => {
    const { calls } = serve(task(), {}, "operation");
    open();
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(calls.some((c) => c.url === TASK)).toBe(false);
  });

  it("says the task is not available when the server says it is not theirs", async () => {
    serve(jsonResponse({ ok: false, error: "not_found" }, 404));
    open();
    expect(await screen.findByRole("alert")).toHaveTextContent("التاسك دي مش متاحة ليك.");
    expect(screen.getByRole("link", { name: /شغلي/ })).toHaveAttribute("href", "/translator");
    expect(screen.queryByText("الإجراءات")).toBeNull();
  });

  it("says it could not load on a server failure, which is not the same as not being theirs", async () => {
    serve(jsonResponse({ ok: false, error: "server" }, 500));
    open();
    expect(await screen.findByRole("alert")).toHaveTextContent("حصلت مشكلة في التحميل.");
  });

  it("reads what the admin sees as read only: none of the translator's buttons", async () => {
    serve(task({ mine: false, can_upload: false, ai: { visible: false, enabled: true, checks: [] }, extension: { can_ask: false, pending: null, last: null } }), {}, "admin");
    open();
    expect(await screen.findByText(/التاسك دي مش بتاعتك/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /خلصت/ })).toBeNull();
    expect(screen.queryByTestId("translation-input")).toBeNull();
    expect(screen.queryByText("مراجعة الترجمة بالـ AI")).toBeNull();
    expect(screen.queryByRole("button", { name: /اطلب وقت أطول/ })).toBeNull();
  });
});

describe("TaskPage: uploading the translation", () => {
  const file = (name: string, size = 4) => new File([new Uint8Array(size)], name, { type: "application/octet-stream" });

  it("has no upload box when the job is not in progress", async () => {
    serve(task({ can_upload: false, under_review: true, status: { value: "under_review", tone: "review", ar: "تحت المراجعة", en: "Under review" } }));
    open();
    await loaded();
    expect(screen.queryByTestId("translation-input")).toBeNull();
  });

  it("sends the files to the group, says so, and reads the page again", async () => {
    const mocked = serve(task(), {
      [`/api/tasks/${CODE}/translation/`]: () => jsonResponse({ ok: true, message: {}, room: 7 }),
    });
    open();
    const input = await screen.findByTestId("translation-input");
    const before = mocked.calls.filter((c) => c.url === TASK).length;
    fireEvent.change(input, { target: { files: [file("a.docx"), file("b.docx")] } });

    expect(await screen.findByText("اترفع واتبعت في الجروب")).toBeInTheDocument();
    const [call] = posts(mocked.calls, `/api/tasks/${CODE}/translation/`);
    expect((call!.init!.body as FormData).getAll("files").map((f) => (f as File).name)).toEqual(["a.docx", "b.docx"]);
    expect(new Headers(call!.init!.headers).get("Content-Type")).toBeNull();
    await waitFor(() => expect(mocked.calls.filter((c) => c.url === TASK).length).toBeGreaterThan(before));
  });

  it("carries the CSRF token", async () => {
    document.cookie = "csrftoken=tok456";
    const mocked = serve(task(), { [`/api/tasks/${CODE}/translation/`]: () => jsonResponse({ ok: true }) });
    open();
    fireEvent.change(await screen.findByTestId("translation-input"), { target: { files: [file("a.docx")] } });
    await screen.findByText("اترفع واتبعت في الجروب");
    expect(new Headers(posts(mocked.calls, `/api/tasks/${CODE}/translation/`)[0]!.init!.headers).get("X-CSRFToken")).toBe("tok456");
    document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("says why in words when the server refuses, and nothing is said to have been sent", async () => {
    const mocked = serve(task(), {
      [`/api/tasks/${CODE}/translation/`]: () => jsonResponse({ ok: false, error: "no_room" }, 400),
    });
    open();
    fireEvent.change(await screen.findByTestId("translation-input"), { target: { files: [file("a.docx")] } });
    expect(await screen.findByRole("alert")).toHaveTextContent(/مفيش جروب مع التيم ليدر/);
    expect(screen.queryByText("اترفع واتبعت في الجروب")).toBeNull();
    expect(posts(mocked.calls, `/api/tasks/${CODE}/translation/`)).toHaveLength(1);
  });

  it("is not sure, rather than failed, when nothing came back", async () => {
    serve(task(), { [`/api/tasks/${CODE}/translation/`]: () => Promise.reject(new TypeError("network down")) });
    open();
    fireEvent.change(await screen.findByTestId("translation-input"), { target: { files: [file("a.docx")] } });
    expect(await screen.findByRole("alert")).toHaveTextContent(/مش متأكدين/);
  });

  it("refuses too many files, or too much, before anything is sent", async () => {
    const mocked = serve(task());
    open();
    const input = await screen.findByTestId("translation-input");
    fireEvent.change(input, { target: { files: Array.from({ length: 11 }, (_, i) => file(`f${i}.docx`)) } });
    expect(await screen.findByRole("alert")).toHaveTextContent("لحد 10 ملفات في المرة.");
    const huge = file("huge.docx", 8);
    Object.defineProperty(huge, "size", { value: 96 * 1024 * 1024 });
    fireEvent.change(input, { target: { files: [huge] } });
    expect(await screen.findByText(/أكبر من المسموح/)).toBeInTheDocument();
    expect(posts(mocked.calls, `/api/tasks/${CODE}/translation/`)).toHaveLength(0);
  });

  it("does nothing when the box is closed without a file", async () => {
    const mocked = serve(task());
    open();
    fireEvent.change(await screen.findByTestId("translation-input"), { target: { files: [] } });
    expect(posts(mocked.calls, `/api/tasks/${CODE}/translation/`)).toHaveLength(0);
  });
});

describe("TaskPage: finished", () => {
  const finish = () => screen.getByRole("button", { name: "خلصت الترجمة" });

  it("waits for the translation: the button is off and says why", async () => {
    serve(task());
    open();
    await loaded();
    expect(finish()).toBeDisabled();
    expect(screen.getByText(/ارفع ملف الترجمة من فوق الأول/)).toBeInTheDocument();
  });

  it("asks before it sends the job to review, and sends nothing on cancel", async () => {
    const mocked = serve(task({ translation_missing: false }));
    open();
    await loaded();
    expect(screen.queryByText(/ارفع ملف الترجمة من فوق الأول/)).toBeNull();
    await userEvent.click(finish());
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("متأكد إنك رفعت ملف الترجمة النهائي وخلصت؟")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "إلغاء" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(posts(mocked.calls, `/api/tasks/${CODE}/translated/`)).toHaveLength(0);
  });

  it("sends it once confirmed, closes, and shows the task in review when the page is read again", async () => {
    const mocked = serve(task({ translation_missing: false }), {
      [`/api/tasks/${CODE}/translated/`]: () => {
        mocked.state.task = task({
          translation_missing: false, can_upload: false, under_review: true,
          status: { value: "under_review", tone: "review", ar: "تحت المراجعة", en: "Under review" },
        });
        return jsonResponse({ ok: true, status: "under_review" });
      },
    });
    open();
    await loaded();
    await userEvent.click(finish());
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "أيوه، خلصت" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(posts(mocked.calls, `/api/tasks/${CODE}/translated/`)).toHaveLength(1);
    expect(await screen.findByText("التيم ليدر بيراجع دلوقتي.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "خلصت الترجمة" })).toBeNull();
    expect(screen.queryByTestId("translation-input")).toBeNull();
  });

  it("says the server's own sentence when it refuses, and keeps the question open", async () => {
    serve(task({ translation_missing: false }), {
      [`/api/tasks/${CODE}/translated/`]: () =>
        jsonResponse({ ok: false, code: "no_translation_file", error: "ارفع ملف الترجمة الأول من صفحة التاسك، وبعدين دوس «خلصت»." }, 400),
    });
    open();
    await loaded();
    await userEvent.click(finish());
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "أيوه، خلصت" }));
    expect(await within(screen.getByRole("dialog")).findByRole("alert")).toHaveTextContent("ارفع ملف الترجمة الأول من صفحة التاسك");
    expect(within(screen.getByRole("dialog")).getByRole("button", { name: "أيوه، خلصت" })).toBeEnabled();
  });

  it("treats an ok:false with a 200 as a refusal and not as done", async () => {
    serve(task({ translation_missing: false }), { [`/api/tasks/${CODE}/translated/`]: () => jsonResponse({ ok: false, status: "in_progress" }) });
    open();
    await loaded();
    await userEvent.click(finish());
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "أيوه، خلصت" }));
    expect(await within(screen.getByRole("dialog")).findByRole("alert")).toHaveTextContent("مقدرتش أعمل ده.");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("is not sure, rather than failed, when the server failed", async () => {
    serve(task({ translation_missing: false }), { [`/api/tasks/${CODE}/translated/`]: () => jsonResponse({ ok: false, error: "server" }, 500) });
    open();
    await loaded();
    await userEvent.click(finish());
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "أيوه، خلصت" }));
    expect(await within(screen.getByRole("dialog")).findByRole("alert")).toHaveTextContent(/مش متأكدين/);
  });

  it("is not there when the task is in review, and says the leader is looking", async () => {
    serve(task({ can_upload: false, under_review: true }));
    open();
    expect(await screen.findByText("التيم ليدر بيراجع دلوقتي.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "خلصت الترجمة" })).toBeNull();
  });
});

describe("TaskPage: more time", () => {
  const box = () => screen.getByRole("button", { name: /اطلب وقت أطول/, expanded: true });

  it("opens from the head of the page, and the first box has the cursor", async () => {
    serve(task());
    open();
    await loaded();
    expect(screen.queryByLabelText("السبب")).toBeNull();
    await userEvent.click(screen.getAllByRole("button", { name: /اطلب وقت أطول/ })[0]!);
    expect(screen.getByLabelText("السبب")).toBeInTheDocument();
    expect(document.activeElement).toBe(screen.getAllByRole("spinbutton")[0]);
    expect(box()).toBeInTheDocument();
  });

  it("opens by itself when the desk sent the person with the hash", async () => {
    serve(task());
    open(`/tasks/${CODE}#more-time`);
    expect(await screen.findByLabelText("السبب")).toBeInTheDocument();
  });

  it("does not send nothing: no length, no button", async () => {
    const mocked = serve(task());
    open(`/tasks/${CODE}#more-time`);
    const send = await screen.findByRole("button", { name: "ابعت الطلب للتيم ليدر" });
    expect(send).toBeDisabled();
    expect(posts(mocked.calls, `/api/tasks/${CODE}/extension/`)).toHaveLength(0);
  });

  it("sends days, hours, minutes and the reason, and says it went to the leader", async () => {
    const mocked = serve(task(), {
      [`/api/tasks/${CODE}/extension/`]: () => {
        mocked.state.task = task({ extension: { can_ask: false, pending: { minutes: 1530, reason: "Heavy tables" }, last: null } });
        return jsonResponse({ ok: true, id: 3 });
      },
    });
    open(`/tasks/${CODE}#more-time`);
    const [days, hours, minutes] = await screen.findAllByRole("spinbutton");
    await userEvent.clear(days!);
    await userEvent.type(days!, "1");
    await userEvent.clear(hours!);
    await userEvent.type(hours!, "1");
    await userEvent.clear(minutes!);
    await userEvent.type(minutes!, "30");
    await userEvent.type(screen.getByLabelText("السبب"), "  Heavy tables ");
    await userEvent.click(screen.getByRole("button", { name: "ابعت الطلب للتيم ليدر" }));

    expect(await screen.findByText("الطلب اتبعت للتيم ليدر")).toBeInTheDocument();
    expect(formBody(posts(mocked.calls, `/api/tasks/${CODE}/extension/`)[0]!)).toEqual({ days: "1", hours: "1", minutes: "30", reason: "Heavy tables" });
    // The next read says it is waiting, and the box is gone.
    expect(await screen.findByText("طلبت وقت إضافي")).toBeInTheDocument();
    expect(screen.getByText(/1 يوم 1 ساعة 30 دقيقة — Heavy tables/)).toBeInTheDocument();
    expect(screen.getByText("مستني رد التيم ليدر.")).toBeInTheDocument();
    expect(screen.queryByLabelText("السبب")).toBeNull();
    expect(screen.getByText("طلبت وقت أطول - مستني الرد")).toBeInTheDocument();
  });

  it("says why when it is refused, and keeps what was typed", async () => {
    serve(task(), { [`/api/tasks/${CODE}/extension/`]: () => jsonResponse({ ok: false, error: "الوقت المطلوب بيعدّي ديدلاين العميل." }, 400) });
    open(`/tasks/${CODE}#more-time`);
    const [days] = await screen.findAllByRole("spinbutton");
    await userEvent.clear(days!);
    await userEvent.type(days!, "9");
    await userEvent.type(screen.getByLabelText("السبب"), "Because");
    await userEvent.click(screen.getByRole("button", { name: "ابعت الطلب للتيم ليدر" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("الوقت المطلوب بيعدّي ديدلاين العميل.");
    expect(screen.getByLabelText("السبب")).toHaveValue("Because");
  });

  it("shows a request that waits for the leader, and offers no second one", async () => {
    serve(task({ extension: { can_ask: false, pending: { minutes: 90, reason: "" }, last: null } }));
    open();
    expect(await screen.findByText("طلبت وقت إضافي")).toBeInTheDocument();
    expect(screen.getByText("1 ساعة 30 دقيقة")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /اطلب وقت أطول/ })).toBeNull();
  });

  it("shows the leader's answer with the note, in green when yes and in red when no", async () => {
    const decided = (status: "approved" | "declined", note: string) =>
      task({ extension: { can_ask: true, pending: null, last: { status, minutes: 1500, note, at: stamp("10-02 3:00") } } });
    serve(decided("declined", "Client needs it today"));
    const { unmount } = open();
    expect(await screen.findByText("التيم ليدر رفض الوقت الإضافي.")).toBeInTheDocument();
    expect(screen.getByText("Client needs it today")).toBeInTheDocument();
    expect(screen.getByText("التيم ليدر رفض الوقت الإضافي.").closest(".note")).toHaveClass("note--high");
    expect(screen.getByText(/10-02 3:00 م · 1 يوم 1 ساعة/)).toBeInTheDocument();
    unmount();
    vi.unstubAllGlobals();

    serve(decided("approved", ""));
    open();
    expect((await screen.findByText("التيم ليدر وافق على الوقت الإضافي.")).closest(".note")).toHaveClass("note--ok");
  });
});

describe("TaskPage: the AI check", () => {
  const ai = (over: Partial<TranslatorTask["ai"]> = {}) => ({ visible: true, enabled: true, checks: [], ...over });
  const run = () => screen.getByRole("button", { name: "تشيك" });

  it("says it is switched off, and offers no form", async () => {
    serve(task({ ai: ai({ enabled: false }) }));
    open();
    expect((await screen.findByText("متوقفة من الأدمن")).closest(".badge")).toHaveClass("badge--dead");
    expect(screen.queryByRole("button", { name: "تشيك" })).toBeNull();
  });

  it("asks with the boxes it was given, empty ones meaning 'read the files'", async () => {
    const mocked = serve(task({ ai: ai() }), {
      [`/api/tasks/${CODE}/ai-check/`]: () => jsonResponse({ ok: true, status: "clean", summary: "", issues: [], count: 0 }),
    });
    open();
    await screen.findByText("مفعّلة");
    await userEvent.click(run());
    expect(await screen.findByText(/مفيش أخطاء واضحة/)).toBeInTheDocument();
    expect(formBody(posts(mocked.calls, `/api/tasks/${CODE}/ai-check/`)[0]!)).toEqual({ source_text: "", translated_text: "" });

    await userEvent.type(screen.getByLabelText("النص الأصلي (اختياري)"), "Hello");
    await userEvent.type(screen.getByLabelText("الترجمة"), "مرحبا");
    await userEvent.click(run());
    await waitFor(() => expect(posts(mocked.calls, `/api/tasks/${CODE}/ai-check/`)).toHaveLength(2));
    expect(formBody(posts(mocked.calls, `/api/tasks/${CODE}/ai-check/`)[1]!)).toEqual({ source_text: "Hello", translated_text: "مرحبا" });
  });

  it("draws what it found: where, the two excerpts, what is wrong in the page's language, and what the source means", async () => {
    serve(task({ ai: ai() }), {
      [`/api/tasks/${CODE}/ai-check/`]: () =>
        jsonResponse({
          ok: true, status: "issues", count: 2, summary: "Two things to look at",
          issues: [
            { location: "Page 2", severity: "high", source_excerpt: "Net 30 days", translation_excerpt: "", issue_ar: "ناقصة", issue_en: "Missing", correct_meaning_ar: "الدفع بعد 30 يوم" },
            { location: "Page 3", severity: "low", issue_en: "Only English" },
          ],
        }),
    });
    const { container } = open();
    await screen.findByText("مفعّلة");
    await userEvent.click(run());
    expect(await screen.findByText("Two things to look at")).toBeInTheDocument();
    const card = screen.getByText("مراجعة الترجمة بالـ AI").closest(".card") as HTMLElement;
    // One note per issue, by how serious: high is red, low is blue.
    expect(card.querySelectorAll(".note.note--high")).toHaveLength(1);
    expect(card.querySelectorAll(".note.note--info")).toHaveLength(1);
    expect(screen.getByText("Net 30 days")).toBeInTheDocument();
    expect(screen.getByText("(مش موجودة في الترجمة)")).toBeInTheDocument();
    expect(screen.getByText("ناقصة")).toBeInTheDocument();
    expect(screen.getByText(/الدفع بعد 30 يوم/)).toBeInTheDocument();
    // An issue written in one language only is still shown in the other page.
    expect(screen.getByText("Only English")).toBeInTheDocument();
    expect(container.querySelectorAll(".ai-issue__pair")).toHaveLength(1);
  });

  it("says in English what it found when the page is English", async () => {
    serve(task({ ai: ai() }), {
      [`/api/tasks/${CODE}/ai-check/`]: () =>
        jsonResponse({ ok: true, status: "issues", count: 1, summary: "", issues: [{ location: "P1", severity: "medium", issue_ar: "ناقصة", issue_en: "Missing" }] }),
    });
    open(`/tasks/${CODE}`, "en");
    await screen.findByText("Enabled");
    await userEvent.click(screen.getByRole("button", { name: "Check" }));
    expect(await screen.findByText("Missing")).toBeInTheDocument();
    expect(screen.queryByText("ناقصة")).toBeNull();
  });

  it("says the check itself failed when the server says so, without calling it a clean result", async () => {
    serve(task({ ai: ai() }), { [`/api/tasks/${CODE}/ai-check/`]: () => jsonResponse({ ok: false, status: "error", error: "The model did not answer" }) });
    open();
    await screen.findByText("مفعّلة");
    await userEvent.click(run());
    expect(await screen.findByRole("alert")).toHaveTextContent("The model did not answer");
    expect(screen.queryByText(/مفيش أخطاء واضحة/)).toBeNull();
  });

  it("says it is off when the server refuses because the admin turned it off meanwhile", async () => {
    serve(task({ ai: ai() }), { [`/api/tasks/${CODE}/ai-check/`]: () => jsonResponse({ ok: false, error: "disabled" }, 400) });
    open();
    await screen.findByText("مفعّلة");
    await userEvent.click(run());
    expect(await screen.findByRole("alert")).toHaveTextContent("مراجعة الـAI متوقفة من الأدمن.");
  });

  it("shows the last checks: the state of each, when, how many, and which ran by themselves", async () => {
    serve(
      task({
        ai: ai({
          checks: [
            { id: 1, status: "issues", count: 3, automatic: true, summary: "Three issues", at: stamp("10-02 1:00") },
            { id: 2, status: "running", count: 0, automatic: false, summary: "", at: stamp("10-02 12:00") },
            { id: 3, status: "error", count: 0, automatic: false, summary: "Could not read", at: stamp("10-02 11:00") },
            { id: 4, status: "clean", count: 0, automatic: false, summary: "All good", at: stamp("10-02 10:00") },
          ],
        }),
      }),
    );
    open();
    const first = (await screen.findByText("Three issues")).closest(".note") as HTMLElement;
    expect(first).toHaveClass("note--warn");
    expect(first).toHaveTextContent("10-02 1:00 م · 3 · تلقائي");
    expect(screen.getByText(/الفحص شغال دلوقتي/).closest(".note")).toHaveClass("note--info");
    expect(screen.getByText("Could not read").closest(".note")).toHaveClass("note--high");
    expect(screen.getByText("All good").closest(".note")).toHaveClass("note--ok");
  });

  it("is not drawn for somebody whose task it is not", async () => {
    serve(task({ ai: ai({ visible: false }) }));
    open();
    await loaded();
    expect(screen.queryByText("مراجعة الترجمة بالـ AI")).toBeNull();
  });
});
