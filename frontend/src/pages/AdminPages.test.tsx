import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AdminOverview, Role } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { AdminOverviewPage } from "./AdminOverviewPage";

afterEach(() => vi.unstubAllGlobals());

const stamp = (text: string) => ({ ar: `${text} PM`, en: `${text} PM` });
const STATUS = (value: string, ar: string, en: string, tone = "work") => ({ value, tone, ar, en });

function overview(over: Partial<AdminOverview> = {}): AdminOverview {
  return {
    ok: true,
    counters: { new: 4, open: 7, delivered: 21, clients: 9 },
    blocked: [
      {
        id: 31,
        code: "CL-0003",
        channel: "email",
        at: stamp("10-02 4:10"),
        body: "What is your price per page",
        sender: "buyer@example.com",
        keyword: "price",
        files: [{ id: 5, url: "/files/rates.pdf", name: "rates.pdf", size: "12 KB", image: false, audio: false, length: "" }],
      },
    ],
    pending: [{ id: 2, task: "TSK-00007", assignee: "Sam", seconds_left: 42 }],
    late: [{ code: "TSK-00004", translator: "Nada", deadline: stamp("10-01 2:00") }, { code: "TSK-00005", translator: null, deadline: stamp("10-01 3:00") }],
    recent: [
      {
        code: "TSK-00009",
        title: "Contract",
        origin: { value: "email", icon: "mail", ar: "إيميل", en: "E-mail" },
        status: STATUS("new", "جديد", "New", "new"),
      },
    ],
    ...over,
  };
}

function serve(who: Role, body: () => AdminOverview | Response, extra: Record<string, (url: URL) => Response> = {}) {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role: who, is_admin: who === "admin" })),
    // Before the board's own address: the routes are matched by the start of the path, in this order.
    ...extra,
    "/api/v1/admin/overview/": () => {
      const answer = body();
      return answer instanceof Response ? answer : jsonResponse(answer);
    },
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function open(route: string, lang: "ar" | "en" = "ar") {
  return renderWithProviders(
    <Routes>
      <Route path="/admin" element={<AdminOverviewPage />} />
      <Route path="/tasks/:code" element={<div>one task page</div>} />
      <Route path="/" element={<div>home page</div>} />
    </Routes>,
    { route, lang },
  );
}

describe("AdminOverviewPage", () => {
  it("shows the four numbers the way the classic overview does", async () => {
    serve("admin", () => overview());
    const { container } = open("/admin");
    await screen.findByText("TSK-00009");
    expect(Array.from(container.querySelectorAll(".kpi")).map((one) => one.textContent)).toEqual([
      "4تاسكات جديدة",
      "7شغالة",
      "21اتسلمت",
      "9عملاء",
    ]);
    expect(container.querySelector(".kpi--warn")).toHaveTextContent("شغالة");
    expect(container.querySelector(".kpi--ok")).toHaveTextContent("اتسلمت");
  });

  it("lists a letter held back with its client's code, words, file, sender and the word that held it", async () => {
    serve("admin", () => overview());
    const { container } = open("/admin");
    await screen.findByText("TSK-00009");
    const letter = container.querySelector('[data-letter="31"]') as HTMLElement;
    expect(letter).toHaveClass("is-blocked");
    expect(within(letter).getByText("CL-0003")).toHaveClass("mono");
    expect(within(letter).getByText("What is your price per page")).toBeInTheDocument();
    expect(within(letter).getByText("10-02 4:10 PM")).toBeInTheDocument();
    expect(within(letter).getByRole("link", { name: /rates\.pdf/ })).toHaveAttribute("href", "/files/rates.pdf");
    expect(within(letter).getByText("buyer@example.com · price")).toBeInTheDocument();
  });

  it("opens a held letter's file only from this site", async () => {
    const hostile = overview().blocked[0]!;
    serve("admin", () => overview({ blocked: [{ ...hostile, files: [{ ...hostile.files[0]!, url: "https://elsewhere.example/x.pdf" }] }] }));
    const { container } = open("/admin");
    await screen.findByText("TSK-00009");
    const letter = container.querySelector('[data-letter="31"]') as HTMLElement;
    expect(within(letter).queryByRole("link")).toBeNull();
    expect(within(letter).getByText("rates.pdf")).toBeInTheDocument();
  });

  it("says when nothing is held back, nothing waits, nothing is late and there are no tasks", async () => {
    serve("admin", () => overview({ blocked: [], pending: [], late: [], recent: [], counters: { new: 0, open: 0, delivered: 0, clients: 0 } }));
    open("/admin");
    expect(await screen.findByText("مفيش رسايل محجوبة.")).toBeInTheDocument();
    expect(screen.getByText("كله في ميعاده.")).toBeInTheDocument();
    expect(screen.getAllByText("مفيش.")).toHaveLength(2);
  });

  it("lists the hand-offs waiting, with the seconds left, and opens the task in the app", async () => {
    serve("admin", () => overview());
    const user = userEvent.setup();
    open("/admin");
    const link = await screen.findByRole("link", { name: "TSK-00007" });
    expect(link).toHaveAttribute("href", "/tasks/TSK-00007");
    expect(screen.getByText("Sam")).toBeInTheDocument();
    expect(screen.getByText("42s")).toHaveClass("badge--wait");
    await user.click(link);
    expect(await screen.findByText("one task page")).toBeInTheDocument();
  });

  it("lists the late tasks with the translator or a dash, and the date", async () => {
    serve("admin", () => overview());
    open("/admin");
    const late = (await screen.findByText("تاسكات عدّت الديدلاين")).closest(".card") as HTMLElement;
    expect(within(late).getByText("Nada")).toBeInTheDocument();
    expect(within(late).getByText("—")).toBeInTheDocument();
    expect(within(late).getByText("10-01 2:00 PM")).toHaveClass("badge--dead");
  });

  it("lists the newest tasks with where each came from and where it stands", async () => {
    serve("admin", () => overview());
    open("/admin");
    const latest = (await screen.findByText("آخر التاسكات")).closest(".card") as HTMLElement;
    expect(within(latest).getByText("Contract")).toBeInTheDocument();
    expect(within(latest).getByText("إيميل")).toBeInTheDocument();
    expect(within(latest).getByText("جديد").closest(".badge")).toHaveClass("badge--new");
  });

  it("speaks English when the page is in English", async () => {
    serve("admin", () => overview());
    open("/admin", "en");
    expect(await screen.findByText("Hidden from Operation")).toBeInTheDocument();
    expect(screen.getByText("Late tasks")).toBeInTheDocument();
    expect(screen.getByText("10-02 4:10 PM")).toBeInTheDocument();
  });

  it("sends anybody who is not the admin home, and asks the server for nothing", async () => {
    const mocked = serve("operation", () => overview());
    open("/admin");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(mocked.calls.some((call) => call.url.startsWith("/api/v1/admin/"))).toBe(false);
  });

  it("says so when the board cannot be read", async () => {
    serve("admin", () => jsonResponse({ ok: false, error: "server" }, 500));
    open("/admin");
    expect(await screen.findByRole("alert")).toHaveTextContent("حصلت مشكلة في التحميل.");
  });

  it("puts the held letters in a box of their own that scrolls, so the page does not grow with them", async () => {
    const first = overview().blocked[0]!;
    serve("admin", () => overview({ blocked: Array.from({ length: 20 }, (_, index) => ({ ...first, id: 100 + index })) }));
    const { container } = open("/admin");
    await screen.findByText("TSK-00009");
    const box = screen.getByTestId("held-letters");
    expect(box).toHaveClass("overview-held");
    expect(box.querySelectorAll(".msg-item")).toHaveLength(20);
    // The rule itself: a box with a ceiling and its own scroll (jsdom does not lay out, so the stylesheet is read).
    const sheet = readFileSync(resolve(__dirname, "../styles.css"), "utf-8");
    const rule = /\.overview-held\s*\{([^}]*)\}/.exec(sheet)?.[1] ?? "";
    expect(rule).toMatch(/max-height:\s*\d+px/);
    expect(rule).toMatch(/overflow-y:\s*auto/);
    expect(container.querySelector(".card .overview-held")).not.toBeNull();
  });

  it("offers «سلّم للعميل» only beside a task awaiting delivery, and sends it after the «تأكيد»", async () => {
    const delivered: string[] = [];
    const mocked = serve(
      "admin",
      () =>
        overview({
          recent: [
            { code: "TSK-00034", title: "Ready", origin: null, status: STATUS("reviewed", "بانتظار التسليم للعميل", "Awaiting delivery to the client", "wait") },
            { code: "TSK-00009", title: "Contract", origin: null, status: STATUS("new", "جديد", "New", "new") },
          ],
        }),
      {
        "/api/v1/admin/overview/deliver/": (url) => {
          delivered.push(url.pathname);
          return jsonResponse({ ok: true, status: "sent", channel: "whatsapp", files: 1 });
        },
      },
    );
    const user = userEvent.setup();
    open("/admin");
    const latest = (await screen.findByText("آخر التاسكات")).closest(".card") as HTMLElement;
    const buttons = within(latest).getAllByRole("button", { name: "سلّم للعميل" });
    expect(buttons).toHaveLength(1);
    expect(buttons[0]!.closest("li")).toHaveTextContent("TSK-00034");
    await user.click(buttons[0]!);
    // Nothing leaves before the question is answered.
    expect(delivered).toEqual([]);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("تسلّم TSK-00034 للعميل؟");
    await user.click(within(dialog).getByRole("button", { name: "سلّم للعميل" }));
    await waitFor(() => expect(delivered).toEqual(["/api/v1/admin/overview/deliver/TSK-00034/"]));
    const call = mocked.calls.find((one) => one.url.startsWith("/api/v1/admin/overview/deliver/"))!;
    expect(call.init?.method).toBe("POST");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("keeps the question open with the server's words when the delivery is refused", async () => {
    serve(
      "admin",
      () => overview({ recent: [{ code: "TSK-00034", title: "Ready", origin: null, status: STATUS("reviewed", "بانتظار التسليم للعميل", "Awaiting delivery", "wait") }] }),
      { "/api/v1/admin/overview/deliver/": () => jsonResponse({ ok: false, error: "مفيش ملف نهائي على التاسك. افتحها واختار الملفات من صفحتها." }, 400) },
    );
    const user = userEvent.setup();
    open("/admin");
    await user.click(await screen.findByRole("button", { name: "سلّم للعميل" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "سلّم للعميل" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("مفيش ملف نهائي على التاسك.");
  });

  it("offers «الغِ التاسك» beside each late task, and cancels through the task's own door after the «تأكيد»", async () => {
    const cancelled: string[] = [];
    serve("admin", () => overview(), {
      "/api/tasks/": (url) => {
        cancelled.push(url.pathname);
        return jsonResponse({ ok: true, status: "cancelled" });
      },
    });
    const user = userEvent.setup();
    open("/admin");
    const late = (await screen.findByText("تاسكات عدّت الديدلاين")).closest(".card") as HTMLElement;
    const buttons = within(late).getAllByRole("button", { name: "الغِ التاسك" });
    expect(buttons).toHaveLength(2);
    await user.click(buttons[0]!);
    expect(cancelled).toEqual([]);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("إلغاء TSK-00004؟");
    await user.click(within(dialog).getByRole("button", { name: "ألغي التاسك" }));
    await waitFor(() => expect(cancelled).toEqual(["/api/tasks/TSK-00004/cancel/"]));
    // The latest tasks have no cancel button: only the late ones do.
    const latest = screen.getByText("آخر التاسكات").closest(".card") as HTMLElement;
    expect(within(latest).queryByRole("button", { name: "الغِ التاسك" })).toBeNull();
  });
});
