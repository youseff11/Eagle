import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Role, TaskStartResponse } from "../api/types";
import { ToastProvider } from "../components/Toasts";
import { jsonResponse, me, mockFetch, renderWithProviders, type Routes as FetchRoutes } from "../test/helpers";
import { NewTaskPage } from "./NewTaskPage";

afterEach(() => vi.unstubAllGlobals());

const START = "/api/v1/task-form/";
const CREATE = "/api/v1/task-form/create/";

function start(over: Partial<TaskStartResponse> = {}): TaskStartResponse {
  return {
    ok: true,
    from_task: null,
    client_code: "",
    messages: [],
    picked: [],
    initial: { client: null, title: "", description: "", source_lang: "" },
    requirements: [],
    clients: [
      { id: 5, code: "CL-0001", label: "CL-0001" },
      { id: 6, code: "CL-0002", label: "CL-0002" },
    ],
    languages: [
      { code: "EN", ar: "إنجليزي", en: "English" },
      { code: "ZZ", ar: "ZZ", en: "ZZ" },
    ],
    quick_languages: ["AR", "EN", "FR"],
    priorities: [
      { value: "low", ar: "منخفضة", en: "Low" },
      { value: "normal", ar: "عادية", en: "Normal" },
      { value: "high", ar: "عالية", en: "High" },
    ],
    ...over,
  };
}

const fromMessage = () =>
  start({
    client_code: "CL-0001",
    messages: [
      {
        id: 7, channel: "whatsapp", at: { ar: "10/02 م", en: "10/02 PM" }, subject: "",
        body: "Please translate the contract",
        files: [{ id: 1, url: "/files/in/contract.pdf", name: "contract.pdf", size: "2.0 KB", image: false }],
      },
    ],
    initial: { client: 5, title: "Please translate the contract", description: "Please translate the contract", source_lang: "" },
    requirements: [{ id: 1, kind: { value: "rule", ar: "قاعدة", en: "Rule" }, author: "Nour", text: "British spelling" }],
  });

function serve(body: TaskStartResponse | Response, extra: FetchRoutes = {}, role: Role = "operation") {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role, is_admin: role === "admin" })),
    ...extra,
    [START]: () => (body instanceof Response ? body : jsonResponse(body)),
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function open(route = "/tasks/new", lang: "ar" | "en" = "ar") {
  return renderWithProviders(
    <ToastProvider>
      <Routes>
        <Route path="/tasks/new" element={<NewTaskPage />} />
        <Route path="/tasks/:code" element={<div>one task page</div>} />
        <Route path="/" element={<div>home page</div>} />
      </Routes>
    </ToastProvider>,
    { route, lang },
  );
}

const sent = (calls: { url: string; init?: RequestInit }[]) =>
  calls.filter((c) => c.url === CREATE && c.init?.method === "POST").map((c) => JSON.parse(String(c.init!.body)));
const ready = () => screen.findByLabelText("عنوان التاسك");
/** The form is drawn and has been filled from the message: the title is the message's first words. */
const filled = async () => {
  const title = await ready();
  await waitFor(() => expect(title).toHaveValue("Please translate the contract"));
};

describe("NewTaskPage: what it starts from", () => {
  it("is a blank form with the clients, the priorities and a note about where tasks come from", async () => {
    serve(start());
    open();
    await ready();
    const clients = screen.getByLabelText("كود العميل") as HTMLSelectElement;
    expect(Array.from(clients.options).map((o) => o.textContent)).toEqual(["—", "CL-0001", "CL-0002"]);
    expect(clients.value).toBe("");
    expect((screen.getByLabelText("الأولوية") as HTMLSelectElement).value).toBe("normal");
    expect(Array.from((screen.getByLabelText("الأولوية") as HTMLSelectElement).options).map((o) => o.textContent)).toEqual(["منخفضة", "عادية", "عالية"]);
    expect(screen.getByText(/تقدر تعمل التاسك من ميل/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /اعمل التاسك/ })).toBeDisabled();
  });

  it("asks the server for what the address names, passed on as it is - and nothing that is not an id or a code", async () => {
    const mocked = serve(start());
    open("/tasks/new?messages=7,8&files=3&from=TSK-00001&evil=1&message=%3Cscript%3E");
    await ready();
    const asked = mocked.calls.filter((c) => c.url.startsWith(START)).map((c) => c.url);
    expect(asked).toEqual([`${START}?messages=7%2C8&files=3&from=TSK-00001`]);
  });

  it("passes on the messages ticked for the details, and drops them when they are not ids", async () => {
    const mocked = serve(start());
    open("/tasks/new?messages=7,8&texts=8&texts=%3Cb%3E");
    await ready();
    const asked = mocked.calls.filter((c) => c.url.startsWith(START)).map((c) => c.url);
    expect(asked).toEqual([`${START}?messages=7%2C8&texts=8`]);
  });

  it("is filled from a message: its client, its words as the title and the details, and the message beside the form", async () => {
    serve(fromMessage());
    open("/tasks/new?message=7");
    await filled();
    expect((screen.getByLabelText("كود العميل") as HTMLSelectElement).value).toBe("5");
    expect((screen.getByLabelText("التفاصيل") as HTMLTextAreaElement).value).toBe("Please translate the contract");
    const side = screen.getByText("الرسالة الأصلية").closest(".card") as HTMLElement;
    expect(within(side).getByText("CL-0001")).toBeInTheDocument();
    expect(within(side).getByText("WhatsApp")).toBeInTheDocument();
    expect(within(side).getByRole("link", { name: /contract\.pdf/ })).toHaveAttribute("href", "/files/in/contract.pdf");
    expect(screen.getByText("British spelling")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /اعمل التاسك/ })).toBeEnabled();
  });

  it("says which files the translator gets: the ticked ones, every one, or none", async () => {
    serve(fromMessage());
    const first = open("/tasks/new?message=7");
    await screen.findByText("الرسالة الأصلية");
    expect(screen.getByText("كل ملفات الرسايل — مااختارتش ملفات معينة.")).toBeInTheDocument();
    first.unmount();
    vi.unstubAllGlobals();

    const ticked = fromMessage();
    ticked.picked = [{ id: 1, url: "/files/in/contract.pdf", name: "contract.pdf", size: "2.0 KB", image: false }];
    serve(ticked);
    const second = open("/tasks/new?message=7&files=1");
    const box = (await screen.findByText("الملفات اللي هتروح للمترجم")).closest(".card") as HTMLElement;
    expect(within(box).getByText("contract.pdf")).toBeInTheDocument();
    second.unmount();
    vi.unstubAllGlobals();

    const bare = fromMessage();
    bare.messages[0]!.files = [];
    serve(bare);
    open("/tasks/new?message=7");
    expect(await screen.findByText("الرسالة دي مفيهاش ملفات.")).toBeInTheDocument();
  });

  it("calls them client messages when there is a run of them, with when each came", async () => {
    const run = fromMessage();
    run.messages.push({ id: 8, channel: "whatsapp", at: { ar: "10/03 م", en: "10/03 PM" }, subject: "", body: "and this", files: [] });
    serve(run);
    open("/tasks/new?messages=7,8");
    const card = (await screen.findByText("رسايل العميل")).closest(".card") as HTMLElement;
    expect(within(card).getByText("10/02 م")).toBeInTheDocument();
    expect(within(card).getByText("10/03 م")).toBeInTheDocument();
    expect(within(card).getByText("2")).toHaveClass("chip");
  });

  it("is a new request on the files of an old task, which it names and links", async () => {
    serve(start({ from_task: { code: "TSK-00001", title: "Original" }, client_code: "CL-0001", initial: { client: 5, title: "طلب جديد — Original", description: "", source_lang: "EN" } }));
    open("/tasks/new?from=TSK-00001");
    await ready();
    expect(screen.getByRole("link", { name: "TSK-00001" })).toHaveAttribute("href", "/tasks/TSK-00001");
    expect(screen.getByText("التاسك القديمة مش بتتلمس.")).toBeInTheDocument();
    expect((screen.getByLabelText("من لغة") as HTMLInputElement).value).toBe("EN");
  });

  it("draws the client's words as text, never as markup", async () => {
    const bad = fromMessage();
    bad.messages[0]!.body = "<img src=x onerror=alert(1)>";
    serve(bad);
    const { container } = open("/tasks/new?message=7");
    expect(await screen.findByText(/<img src=x onerror=alert\(1\)>/)).toBeInTheDocument();
    expect(container.querySelector(".src-msg img")).toBeNull();
  });

  it("draws a file only as a link to this site", async () => {
    const bad = fromMessage();
    bad.messages[0]!.files = [{ id: 1, url: "https://evil.example/a.pdf", name: "outside.pdf", size: "1 B", image: false }];
    serve(bad);
    const { container } = open("/tasks/new?message=7");
    expect(await screen.findByText("outside.pdf")).toBeInTheDocument();
    expect(container.querySelector(".src-msg a")).toBeNull();
  });

  it("speaks English when asked", async () => {
    serve(start());
    open("/tasks/new", "en");
    expect(await screen.findByLabelText("Task title")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Create task/ })).toBeInTheDocument();
    expect(screen.getByLabelText("Priority")).toBeInTheDocument();
  });

  it("is for the operation and the admin: anybody else is sent home without asking", async () => {
    const mocked = serve(start(), {}, "translator");
    open();
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(mocked.calls.some((c) => c.url.startsWith(START))).toBe(false);
  });

  it("says it could not load, and is loading before that", async () => {
    serve(jsonResponse({ ok: false, error: "server" }, 500));
    const failed = open();
    expect(await screen.findByRole("alert")).toHaveTextContent("حصلت مشكلة في التحميل.");
    failed.unmount();
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", () => new Promise(() => undefined));
    open();
    expect(await screen.findByText("بيحمّل...")).toBeInTheDocument();
  });
});

describe("NewTaskPage: making the task", () => {
  async function fill() {
    await ready();
    await userEvent.selectOptions(screen.getByLabelText("كود العميل"), "6");
    await userEvent.type(screen.getByLabelText("عنوان التاسك"), "Lease agreement");
  }

  it("sends the boxes as they are, says the code, and goes to the task", async () => {
    const mocked = serve(start(), { [CREATE]: () => jsonResponse({ ok: true, code: "TSK-00042" }) });
    open();
    await fill();
    await userEvent.type(screen.getByLabelText("التفاصيل"), "Two pages");
    await userEvent.type(screen.getByLabelText("من لغة"), "en");
    await userEvent.click(screen.getAllByRole("button", { name: "AR" })[1]!);
    await userEvent.selectOptions(screen.getByLabelText("الأولوية"), "high");
    await userEvent.type(screen.getAllByLabelText("يوم")[0]!, "2");
    await userEvent.type(screen.getAllByLabelText("ساعة")[0]!, "3");
    await userEvent.type(screen.getByLabelText("عدد الكلمات"), "1200");
    await userEvent.click(screen.getByLabelText("ملف صعب (استثناء من الحد الأدنى اليومي)"));
    await userEvent.click(screen.getByRole("button", { name: /اعمل التاسك/ }));
    expect(await screen.findByText("one task page")).toBeInTheDocument();
    expect(screen.getByText("TSK-00042")).toBeInTheDocument();
    expect(sent(mocked.calls)).toEqual([
      {
        client: 6, title: "Lease agreement", description: "Two pages", source_lang: "en", target_lang: "AR", priority: "high",
        deadline: { days: "2", hours: "3", minutes: "" }, word_count: 1200, is_difficult: true, is_secondary_language: false,
        messages: [], files: [], from: "", quote: "",
      },
    ]);
  });

  it("fills the form from an accepted quotation, says so, and names it when it makes the task", async () => {
    const fromQuote = start({
      quote: { code: "QT-0003" },
      initial: {
        client: 6, title: "QT-0003 · EN > AR", description: "Translation: 1,000 words.", source_lang: "EN",
        target_lang: "AR", word_count: 1000, deadline_days: 5,
      },
    });
    const mocked = serve(fromQuote, { [CREATE]: () => jsonResponse({ ok: true, code: "TSK-00050" }) });
    const { container } = open("/tasks/new?quote=QT-0003");
    await waitFor(() => expect(container.querySelector('[data-quote="QT-0003"]')).not.toBeNull());
    expect(mocked.calls.some((call) => call.url === `${START}?quote=QT-0003`)).toBe(true);
    expect((screen.getByLabelText("كود العميل") as HTMLSelectElement).value).toBe("6");
    expect((screen.getByLabelText("من لغة") as HTMLInputElement).value).toBe("EN");
    expect((screen.getByLabelText("عدد الكلمات") as HTMLInputElement).value).toBe("1000");
    await userEvent.click(screen.getByRole("button", { name: /اعمل التاسك/ }));
    await screen.findByText("one task page");
    expect(sent(mocked.calls)[0]).toMatchObject({ client: 6, source_lang: "EN", target_lang: "AR", word_count: 1000, quote: "QT-0003", deadline: { days: "5" } });
  });

  it("passes on only a quotation code that looks like one", async () => {
    const mocked = serve(start());
    open("/tasks/new?quote=../../x");
    await screen.findByLabelText("كود العميل");
    expect(mocked.calls.some((call) => call.url.includes("quote"))).toBe(false);
  });

  it("sends what the task is made from: the messages and the files ticked, and the task it repeats", async () => {
    const withFiles = fromMessage();
    withFiles.picked = [{ id: 1, url: "/files/in/contract.pdf", name: "contract.pdf", size: "2.0 KB", image: false }];
    withFiles.from_task = { code: "TSK-00001", title: "Original" };
    const mocked = serve(withFiles, { [CREATE]: () => jsonResponse({ ok: true, code: "TSK-00043" }) });
    open("/tasks/new?message=7&files=1&from=TSK-00001");
    await filled();
    await userEvent.click(screen.getByRole("button", { name: /اعمل التاسك/ }));
    await screen.findByText("one task page");
    const [body] = sent(mocked.calls);
    expect(body).toMatchObject({ client: 5, messages: [7], files: [1], from: "TSK-00001", word_count: null });
  });

  it("sends no word count when none was typed, and one that is not a number is not sent", async () => {
    const mocked = serve(start(), { [CREATE]: () => jsonResponse({ ok: true, code: "TSK-00044" }) });
    open();
    await fill();
    await userEvent.click(screen.getByRole("button", { name: /اعمل التاسك/ }));
    await screen.findByText("one task page");
    expect(sent(mocked.calls)[0]!.word_count).toBeNull();
  });

  it("fills a language from the quick buttons", async () => {
    serve(start());
    open();
    await ready();
    await userEvent.click(screen.getAllByRole("button", { name: "FR" })[0]!);
    expect((screen.getByLabelText("من لغة") as HTMLInputElement).value).toBe("FR");
    await userEvent.click(screen.getAllByRole("button", { name: "AR" })[1]!);
    expect((screen.getByLabelText("للغة") as HTMLInputElement).value).toBe("AR");
  });

  it("offers every language as a suggestion that can still be typed over", async () => {
    serve(start());
    const { container } = open();
    await ready();
    const options = Array.from(container.querySelectorAll("#langOptions option")).map((o) => [o.getAttribute("value"), o.textContent]);
    expect(options).toEqual([["EN", "إنجليزي · English"], ["ZZ", ""]]);
  });

  it("names the boxes that were wrong in the form's own words and keeps what was typed", async () => {
    serve(start(), {
      [CREATE]: () => jsonResponse({ ok: false, error: "invalid", fields: { title: ["This field is required."], deadline: ["مفيش ديدلاين بالسالب."] } }, 400),
    });
    open();
    await fill();
    await userEvent.click(screen.getByRole("button", { name: /اعمل التاسك/ }));
    const alerts = await screen.findAllByRole("alert");
    expect(alerts.map((a) => a.textContent)).toEqual(["This field is required.", "مفيش ديدلاين بالسالب."]);
    expect((screen.getByLabelText("عنوان التاسك") as HTMLInputElement).value).toBe("Lease agreement");
    expect(screen.queryByText("one task page")).toBeNull();
    // The errors go when it is tried again.
    await userEvent.click(screen.getByRole("button", { name: /اعمل التاسك/ }));
    await waitFor(() => expect(screen.getAllByRole("alert").length).toBeGreaterThan(0));
  });

  it("says the messages belong to another client when the server says so", async () => {
    serve(fromMessage(), { [CREATE]: () => jsonResponse({ ok: false, error: "client_mismatch" }, 400) });
    open("/tasks/new?message=7");
    await filled();
    await userEvent.selectOptions(screen.getByLabelText("كود العميل"), "6");
    await userEvent.click(screen.getByRole("button", { name: /اعمل التاسك/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("الرسايل دي لعميل تاني");
  });

  it("is not sure, rather than failed, when nothing came back or the server failed", async () => {
    serve(start(), { [CREATE]: () => Promise.reject(new TypeError("network down")) });
    const first = open();
    await fill();
    await userEvent.click(screen.getByRole("button", { name: /اعمل التاسك/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/مش متأكدين إن التاسك اتعملت/);
    first.unmount();
    vi.unstubAllGlobals();

    serve(start(), { [CREATE]: () => jsonResponse({ ok: false, error: "server" }, 500) });
    open();
    await fill();
    await userEvent.click(screen.getByRole("button", { name: /اعمل التاسك/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/مش متأكدين إن التاسك اتعملت/);
  });

  it("makes one task for a double press", async () => {
    let release: (response: Response) => void = () => undefined;
    const mocked = serve(start(), { [CREATE]: () => new Promise<Response>((resolve) => (release = resolve)) });
    open();
    await fill();
    const button = screen.getByRole("button", { name: /اعمل التاسك/ });
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(sent(mocked.calls)).toHaveLength(1));
    expect(button).toBeDisabled();
    release(jsonResponse({ ok: true, code: "TSK-00045" }));
    await screen.findByText("one task page");
    expect(sent(mocked.calls)).toHaveLength(1);
  });

  it("carries the CSRF token", async () => {
    document.cookie = "csrftoken=tok999";
    const mocked = serve(start(), { [CREATE]: () => jsonResponse({ ok: true, code: "TSK-00046" }) });
    open();
    await fill();
    await userEvent.click(screen.getByRole("button", { name: /اعمل التاسك/ }));
    await screen.findByText("one task page");
    const call = mocked.calls.find((c) => c.url === CREATE)!;
    expect(new Headers(call.init!.headers).get("X-CSRFToken")).toBe("tok999");
    document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });
});
