import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AdminSimulate, MailResetCounts, Role, TaskResetCounts } from "../api/types";
import { download } from "../lib/download";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { AdminResetPage } from "./AdminResetPage";
import { AdminSimulatePage } from "./AdminSimulatePage";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

type Handler = (url: URL, init: RequestInit | undefined) => Response | Promise<Response>;

const taskCounts: TaskResetCounts = { tasks: 12, open: 4, assignments: 9, deliveries: 3, ai_checks: 5, rooms: 7 };
const mailCounts: MailResetCounts = { letters: 30, sent: 8, files: 21, kept_letters: 2, kept_sent: 1 };

function simulateData(over: Partial<AdminSimulate> = {}): AdminSimulate {
  return {
    ok: true,
    channels: [
      { value: "whatsapp", label: "WhatsApp" },
      { value: "email", label: "Email" },
    ],
    recent: [
      { id: 2, code: "CL-0002", body: "What is your price", blocked: true },
      { id: 1, code: "CL-0001", body: "Hello there", blocked: false },
    ],
    ...over,
  };
}

function serve(who: Role, over: Record<string, Handler> = {}) {
  const sent: { url: string; body: unknown }[] = [];
  const defaults: Record<string, Handler> = {
    "/api/v1/me/": () => jsonResponse(me({ role: who, is_admin: who === "admin" })),
    "/api/v1/admin/simulate/send/": (url, init) => {
      sent.push({ url: url.pathname, body: init?.body });
      return jsonResponse({ ok: true, id: 9, code: "CL-0009", blocked: false });
    },
    "/api/v1/admin/simulate/": () => jsonResponse(simulateData()),
    "/api/v1/admin/reset/tasks/run/": (url, init) => {
      sent.push({ url: url.pathname, body: JSON.parse(String(init?.body)) });
      return new Response('[{"model":"dashboard.task"}]', {
        status: 200,
        headers: { "Content-Type": "application/json", "Content-Disposition": 'attachment; filename="eagle-tasks-backup-20261003-1200.json"', "X-Eagle-Deleted": "12" },
      });
    },
    "/api/v1/admin/reset/mail/run/": (url, init) => {
      sent.push({ url: url.pathname, body: JSON.parse(String(init?.body)) });
      return new Response("[]", {
        status: 200,
        headers: { "Content-Type": "application/json", "Content-Disposition": 'attachment; filename="eagle-mail-backup-20261003-1200.json"', "X-Eagle-Deleted": "38", "X-Eagle-Files": "21" },
      });
    },
    "/api/v1/admin/reset/tasks/": () => jsonResponse({ ok: true, counts: taskCounts }),
    "/api/v1/admin/reset/mail/": () => jsonResponse({ ok: true, counts: mailCounts }),
  };
  const routes = { ...over };
  for (const [prefix, answer] of Object.entries(defaults)) if (!(prefix in routes)) routes[prefix] = answer;
  const mocked = mockFetch(routes);
  vi.stubGlobal("fetch", mocked.fn);
  return { ...mocked, sent };
}

function open(route: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/admin/simulate" element={<AdminSimulatePage />} />
      <Route path="/admin/reset-tasks" element={<AdminResetPage kind="tasks" />} />
      <Route path="/admin/reset-mail" element={<AdminResetPage kind="mail" />} />
      <Route path="/tasks" element={<div>the task list</div>} />
      <Route path="/inbox" element={<div>the inbox</div>} />
      <Route path="/" element={<div>home page</div>} />
    </Routes>,
    { route },
  );
}

describe("AdminSimulatePage", () => {
  it("draws the form with the server's channels and the latest messages, held-back ones marked", async () => {
    serve("admin");
    const { container } = open("/admin/simulate");
    expect(await screen.findByLabelText("القناة")).toHaveValue("whatsapp");
    await waitFor(() => expect(within(screen.getByLabelText("القناة")).getAllByRole("option")).toHaveLength(2));
    const held = (await screen.findByText("CL-0002")).closest("li") as HTMLElement;
    expect(within(held).getByText("What is your price")).toBeInTheDocument();
    expect(within(held).getByText("محجوبة")).toHaveClass("badge--dead");
    expect(within(container.querySelector('[data-message="1"]') as HTMLElement).queryByText("محجوبة")).toBeNull();
    expect(screen.getByLabelText("رقم / إيميل العميل")).toHaveAttribute("dir", "ltr");
  });

  it("sends the fields and the files as a form, then empties the form and reads the latest again", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    open("/admin/simulate");
    await waitFor(() => expect(within(screen.getByLabelText("القناة")).getAllByRole("option")).toHaveLength(2));
    await user.selectOptions(screen.getByLabelText("القناة"), "email");
    await user.type(screen.getByLabelText("رقم / إيميل العميل"), "buyer@example.com");
    await user.type(screen.getByLabelText("الموضوع"), "Rates");
    await user.type(screen.getByLabelText("نص الرسالة"), "Please send the price");
    await user.upload(screen.getByLabelText("مرفقات"), [new File(["a"], "a.pdf"), new File(["b"], "b.pdf")]);
    await user.click(screen.getByRole("button", { name: "ابعت" }));
    await waitFor(() => expect(served.sent.length).toBe(1));
    const form = served.sent[0]!.body as FormData;
    expect(form.get("channel")).toBe("email");
    expect(form.get("sender_identity")).toBe("buyer@example.com");
    expect(form.get("subject")).toBe("Rates");
    expect(form.get("body")).toBe("Please send the price");
    expect(form.getAll("files").map((file) => (file as File).name)).toEqual(["a.pdf", "b.pdf"]);
    await waitFor(() => expect(screen.getByLabelText("نص الرسالة")).toHaveValue(""));
    expect(screen.getByLabelText("رقم / إيميل العميل")).toHaveValue("");
    expect(screen.getByLabelText("القناة")).toHaveValue("email");
    await waitFor(() => expect(served.calls.filter((call) => call.url === "/api/v1/admin/simulate/").length).toBe(2));
  });

  it("shows the form's refusals beside their fields and keeps what was typed", async () => {
    serve("admin", {
      "/api/v1/admin/simulate/send/": () => jsonResponse({ ok: false, error: "invalid", errors: { body: ["This field is required."], sender_identity: ["This field is required."] } }, 400),
    });
    const user = userEvent.setup();
    open("/admin/simulate");
    await user.type(await screen.findByLabelText("الموضوع"), "Only a subject");
    await user.click(screen.getByRole("button", { name: "ابعت" }));
    expect(await screen.findAllByText("This field is required.")).toHaveLength(2);
    expect(screen.getByLabelText("الموضوع")).toHaveValue("Only a subject");
  });

  it("says so when the message could not be sent for another reason", async () => {
    serve("admin", { "/api/v1/admin/simulate/send/": () => jsonResponse({ ok: false, error: "server" }, 500) });
    const user = userEvent.setup();
    open("/admin/simulate");
    await user.type(await screen.findByLabelText("نص الرسالة"), "x");
    await user.click(screen.getByRole("button", { name: "ابعت" }));
    expect(await screen.findByText("حصلت مشكلة، الرسالة ماوصلتش.")).toBeInTheDocument();
  });

  it("warns that a word about rates holds the message back", async () => {
    serve("admin");
    open("/admin/simulate");
    expect(await screen.findByText(/لو النص فيه كلمة rate/)).toBeInTheDocument();
  });

  it("sends anybody who is not the admin home and asks the server for nothing", async () => {
    const served = serve("operation");
    open("/admin/simulate");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/admin/"))).toBe(false);
  });
});

describe("AdminResetPage: what is counted", () => {
  it("counts the tasks, with how many are still running", async () => {
    serve("admin");
    const { container } = open("/admin/reset-tasks");
    await screen.findByText("تسليم لتيم ليدر/مترجم");
    const counts = container.querySelector('[data-counts="tasks"]') as HTMLElement;
    expect(counts.textContent).toContain("12");
    expect(within(counts).getByText("4 شغالة دلوقتي")).toHaveClass("chip");
    expect(counts.textContent).toContain("9");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("ريستارت التاسكات");
  });

  it("counts the mail and says what stays because tasks stand on it, only when something does", async () => {
    serve("admin");
    const { container } = open("/admin/reset-mail");
    await screen.findByText("ميل وارد");
    expect((container.querySelector('[data-counts="mail"]') as HTMLElement).textContent).toContain("30");
    expect(container.querySelector("[data-kept]")).toHaveTextContent("2");
    expect(screen.getByText(/المسح من الداشبورد بس/)).toBeInTheDocument();
  });

  it("leaves out the note about what stays when nothing does", async () => {
    serve("admin", { "/api/v1/admin/reset/mail/": () => jsonResponse({ ok: true, counts: { ...mailCounts, kept_letters: 0, kept_sent: 0 } }) });
    const { container } = open("/admin/reset-mail");
    await screen.findByText("ميل وارد");
    expect(container.querySelector("[data-kept]")).toBeNull();
  });

  it("asks nothing of the server but the counts when it opens", async () => {
    const served = serve("admin");
    open("/admin/reset-tasks");
    await screen.findByText("تسليم لتيم ليدر/مترجم");
    expect(served.calls.map((call) => call.url)).toEqual(["/api/v1/me/", "/api/v1/admin/reset/tasks/"]);
  });
});

describe("AdminResetPage: the run", () => {
  it("cannot be pressed without the password and the tick, together", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    open("/admin/reset-tasks");
    const button = await screen.findByRole("button", { name: /امسح كل التاسكات/ });
    expect(button).toBeDisabled();
    await user.type(screen.getByLabelText("باسورد الأدمن بتاعك"), "some-password");
    expect(button).toBeDisabled();
    await user.click(screen.getByRole("checkbox"));
    expect(button).toBeEnabled();
    await user.clear(screen.getByLabelText("باسورد الأدمن بتاعك"));
    expect(button).toBeDisabled();
    expect(served.sent).toEqual([]);
  });

  it("sends the password with the explicit yes, saves the backup, and moves on to the task list", async () => {
    const served = serve("admin");
    const save = vi.spyOn(download, "save").mockImplementation(() => undefined);
    const user = userEvent.setup();
    open("/admin/reset-tasks");
    await user.type(await screen.findByLabelText("باسورد الأدمن بتاعك"), "my-admin-password");
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /امسح كل التاسكات/ }));
    await waitFor(() => expect(served.sent.length).toBe(1));
    expect(served.sent[0]).toEqual({ url: "/api/v1/admin/reset/tasks/run/", body: { password: "my-admin-password", confirm: true } });
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(save.mock.calls[0]![1]).toBe("eagle-tasks-backup-20261003-1200.json");
    expect(await screen.findByText("the task list")).toBeInTheDocument();
  });

  it("clears the mail and moves on to the inbox", async () => {
    const served = serve("admin");
    const save = vi.spyOn(download, "save").mockImplementation(() => undefined);
    const user = userEvent.setup();
    open("/admin/reset-mail");
    await user.type(await screen.findByLabelText("باسورد الأدمن بتاعك"), "my-admin-password");
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /امسح كل الميلات/ }));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(served.sent[0]!.url).toBe("/api/v1/admin/reset/mail/run/");
    expect(await screen.findByText("the inbox")).toBeInTheDocument();
  });

  it("shows the server's reason for a wrong password, empties the box, saves nothing and stays", async () => {
    serve("admin", {
      "/api/v1/admin/reset/tasks/run/": () => jsonResponse({ ok: false, error: "refused", message: "الباسورد غلط." }, 400),
    });
    const save = vi.spyOn(download, "save").mockImplementation(() => undefined);
    const user = userEvent.setup();
    open("/admin/reset-tasks");
    await user.type(await screen.findByLabelText("باسورد الأدمن بتاعك"), "wrong-guess");
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /امسح كل التاسكات/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("الباسورد غلط.");
    expect(screen.getByLabelText("باسورد الأدمن بتاعك")).toHaveValue("");
    expect(screen.queryByText("the task list")).toBeNull();
    expect(save).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toContain("wrong-guess");
  });

  it("says the clear-out is shut after too many wrong passwords, and saves nothing", async () => {
    serve("admin", {
      "/api/v1/admin/reset/mail/run/": () => jsonResponse({ ok: false, error: "too_many_attempts", message: "محاولات باسورد غلط كتير. المسح اتقفل 15 دقيقة." }, 429),
    });
    const save = vi.spyOn(download, "save").mockImplementation(() => undefined);
    const user = userEvent.setup();
    open("/admin/reset-mail");
    await user.type(await screen.findByLabelText("باسورد الأدمن بتاعك"), "the-right-one");
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /امسح كل الميلات/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("المسح اتقفل 15 دقيقة");
    expect(screen.getByLabelText("باسورد الأدمن بتاعك")).toHaveValue("");
    expect(save).not.toHaveBeenCalled();
    expect(screen.queryByText("the inbox")).toBeNull();
  });

  it("says nothing was deleted when the connection fails", async () => {
    serve("admin", { "/api/v1/admin/reset/tasks/run/": () => jsonResponse({ ok: false, error: "server" }, 500) });
    const user = userEvent.setup();
    open("/admin/reset-tasks");
    await user.type(await screen.findByLabelText("باسورد الأدمن بتاعك"), "x");
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /امسح كل التاسكات/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("حصلت مشكلة وماعرفناش النتيجة");
    expect(screen.getByRole("alert")).not.toHaveTextContent("محدش اتمسح");
  });

  it("says it does not know the result when the connection drops before the answer", async () => {
    serve("admin", { "/api/v1/admin/reset/tasks/run/": () => Promise.reject(new TypeError("Failed to fetch")) });
    const save = vi.spyOn(download, "save").mockImplementation(() => undefined);
    const user = userEvent.setup();
    open("/admin/reset-tasks");
    await user.type(await screen.findByLabelText("باسورد الأدمن بتاعك"), "x");
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /امسح كل التاسكات/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("ممكن يكون اتمسح");
    expect(save).not.toHaveBeenCalled();
  });

  it("is sure nothing was deleted when the server said no before doing anything", async () => {
    serve("admin", { "/api/v1/admin/reset/tasks/run/": () => jsonResponse({ ok: false, error: "bad_body" }, 400) });
    const user = userEvent.setup();
    open("/admin/reset-tasks");
    await user.type(await screen.findByLabelText("باسورد الأدمن بتاعك"), "x");
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /امسح كل التاسكات/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("محدش اتمسح");
  });

  it("keeps the password out of the address and out of the page", async () => {
    serve("admin");
    const user = userEvent.setup();
    open("/admin/reset-tasks");
    await user.type(await screen.findByLabelText("باسورد الأدمن بتاعك"), "very-secret-pw");
    expect(screen.getByLabelText("باسورد الأدمن بتاعك")).toHaveAttribute("type", "password");
    expect(window.location.href).not.toContain("very-secret-pw");
  });

  it("sends anybody who is not the admin home and asks the server for nothing", async () => {
    const served = serve("sales");
    open("/admin/reset-mail");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/admin/"))).toBe(false);
  });
});
