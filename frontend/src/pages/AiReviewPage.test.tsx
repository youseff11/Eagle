import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AiReviewBoard, AiReviewDetail, AiReviewLine, AiReviewSession } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { ToastProvider } from "../components/Toasts";
import { AiReviewPage } from "./AiReviewPage";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const DOOR = "/api/v1/ai-review/";
const LIMITS = { files: 50, megabytes: 22, message_megabytes: 90, text: 6000 };

const session = (over: Partial<AiReviewSession> & { id: number }): AiReviewSession => ({
  title: `جلسة ${over.id}`,
  at: { ar: "10:15 ص", en: "10:15 AM" },
  pending: false,
  ...over,
});
const line = (over: Partial<AiReviewLine> & { id: number }): AiReviewLine => ({
  role: "user",
  body: "",
  status: "done",
  at: { ar: "10:15 ص", en: "10:15 AM" },
  files: [],
  ...over,
});

interface Server {
  sessions: AiReviewSession[];
  talks: Record<number, AiReviewLine[]>;
  available: boolean;
}

function open(server: Server, options: { route?: string; role?: string; extra?: Record<string, () => Response> } = {}) {
  const detail = (id: number): AiReviewDetail => {
    const one = server.sessions.find((row) => row.id === id)!;
    return { ok: true, session: one, messages: server.talks[id] ?? [] };
  };
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role: (options.role ?? "team_lead") as "team_lead" })),
    [`${DOOR}send/`]: (_url, init) => {
      const form = init!.body as FormData;
      const id = form.get("session") ? Number(form.get("session")) : 90;
      if (!server.sessions.some((row) => row.id === id)) {
        server.sessions = [session({ id, title: String(form.get("text")) || "ملف", pending: true }), ...server.sessions];
      }
      server.talks[id] = [
        ...(server.talks[id] ?? []),
        line({ id: 500 + (server.talks[id]?.length ?? 0), body: String(form.get("text")) }),
        line({ id: 600 + (server.talks[id]?.length ?? 0), role: "assistant", status: "pending" }),
      ];
      return jsonResponse(detail(id));
    },
    ...(options.extra ?? {}),
    [DOOR]: (url) => {
      const match = url.pathname.match(/\/ai-review\/(\d+)\/$/);
      if (match) return jsonResponse(detail(Number(match[1])));
      const board: AiReviewBoard = { ok: true, available: server.available, limits: LIMITS, sessions: server.sessions };
      return jsonResponse(board);
    },
  });
  vi.stubGlobal("fetch", mocked.fn);
  renderWithProviders(
    <ToastProvider>
      <AiReviewPage />
    </ToastProvider>,
    { route: options.route ?? "/lead/ai-review" },
  );
  return mocked;
}

const posts = (mocked: { calls: { url: string; init?: RequestInit }[] }, path: string) =>
  mocked.calls.filter((call) => call.url === path && call.init?.method === "POST");

const server = (over: Partial<Server> = {}): Server => ({ sessions: [], talks: {}, available: true, ...over });

describe("AiReviewPage: the leader chats with the AI", () => {
  it("starts on a new session with suggestions that fill the box", async () => {
    const user = userEvent.setup();
    open(server());
    expect(await screen.findByText("ابدأ مراجعة جديدة")).toBeInTheDocument();
    expect(screen.getByText("لسه مفيش جلسات.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "دوّر على الأرقام والتواريخ والأسماء بس." }));
    expect(screen.getByLabelText("رسالتك للـAI")).toHaveValue("دوّر على الأرقام والتواريخ والأسماء بس.");
  });

  it("lists the sessions and opens one with its talk, files and all", async () => {
    const user = userEvent.setup();
    open(
      server({
        sessions: [session({ id: 5, title: "عقد الإيجار" }), session({ id: 4, title: "تقرير طبي" })],
        talks: {
          5: [
            line({ id: 1, body: "راجع", files: [{ id: 9, url: "/files/aireview/a.pdf", name: "a.pdf", size: "1 KB", image: false, label: "source" }] }),
            line({ id: 2, role: "assistant", body: "1. الرقم غلط" }),
          ],
          4: [line({ id: 3, body: "سؤال تاني" })],
        },
      }),
    );
    const list = await screen.findByRole("complementary");
    expect(within(list).getByText("عقد الإيجار")).toBeInTheDocument();
    await user.click(within(list).getByText("عقد الإيجار"));
    expect(await screen.findByText("1. الرقم غلط")).toBeInTheDocument();
    expect(screen.getByText("راجع").closest("[data-line]")).toHaveAttribute("data-line", "user");
    expect(screen.getByText("1. الرقم غلط").closest("[data-line]")).toHaveAttribute("data-line", "assistant");
    expect(screen.getByRole("link", { name: /a\.pdf/ })).toHaveAttribute("href", "/files/aireview/a.pdf");
    expect(screen.getByText(/· أصل/)).toBeInTheDocument();
    await user.click(within(list).getByText("تقرير طبي"));
    expect(await screen.findByText("سؤال تاني")).toBeInTheDocument();
    expect(screen.queryByText("1. الرقم غلط")).toBeNull();
  });

  it("opens the session named in the address", async () => {
    open(server({ sessions: [session({ id: 5 })], talks: { 5: [line({ id: 1, body: "من الإشعار" })] } }), { route: "/lead/ai-review?s=5" });
    expect(await screen.findByText("من الإشعار")).toBeInTheDocument();
  });

  it("sends files with what each is, opens the new session, and empties the box", async () => {
    const user = userEvent.setup();
    const mocked = open(server());
    await screen.findByText("ابدأ مراجعة جديدة");
    await user.upload(screen.getByLabelText("ملفات للـAI"), [
      new File(["a"], "src.docx"),
      new File(["b"], "tr.docx"),
    ]);
    await user.selectOptions(screen.getByLabelText("إيه src.docx؟"), "source");
    await user.selectOptions(screen.getByLabelText("إيه tr.docx؟"), "translation");
    await user.type(screen.getByLabelText("رسالتك للـAI"), "  قارن ");
    await user.click(screen.getByRole("button", { name: "ابعت" }));
    await waitFor(() => expect(posts(mocked, `${DOOR}send/`)).toHaveLength(1));
    const form = posts(mocked, `${DOOR}send/`)[0]!.init!.body as FormData;
    expect(form.get("text")).toBe("قارن");
    expect(form.get("session")).toBeNull();
    expect(form.getAll("labels")).toEqual(["source", "translation"]);
    expect(form.getAll("files").map((file) => (file as File).name)).toEqual(["src.docx", "tr.docx"]);
    await waitFor(() => expect(screen.getByLabelText("رسالتك للـAI")).toHaveValue(""));
    expect(screen.queryByText("src.docx")).toBeNull();
    // The new session is the open one, and the AI is shown writing in it.
    expect(await screen.findByText(/الـAI بيقرا ويكتب الرد/)).toBeInTheDocument();
    expect(within(screen.getByRole("complementary")).getByText("قارن")).toBeInTheDocument();
  });

  it("goes on in the open session", async () => {
    const user = userEvent.setup();
    const mocked = open(server({ sessions: [session({ id: 5 })], talks: { 5: [line({ id: 1, body: "أول" }), line({ id: 2, role: "assistant", body: "رد" })] } }), {
      route: "/lead/ai-review?s=5",
    });
    await screen.findByText("رد");
    await user.type(screen.getByLabelText("رسالتك للـAI"), "وبعدين؟");
    await user.click(screen.getByRole("button", { name: "ابعت" }));
    await waitFor(() => expect(posts(mocked, `${DOOR}send/`)).toHaveLength(1));
    expect((posts(mocked, `${DOOR}send/`)[0]!.init!.body as FormData).get("session")).toBe("5");
  });

  it("cannot send nothing, nor while the AI is answering in the session", async () => {
    const user = userEvent.setup();
    open(
      server({ sessions: [session({ id: 5, pending: true })], talks: { 5: [line({ id: 1, body: "سؤال" }), line({ id: 2, role: "assistant", status: "pending" })] } }),
      { route: "/lead/ai-review?s=5" },
    );
    expect(await screen.findByText(/الـAI بيقرا ويكتب الرد/)).toBeInTheDocument();
    expect(screen.getByText("الـAI بيرد دلوقتي. تقدر تكتب رسالتك وتبعتها لما يخلص.")).toBeInTheDocument();
    await user.type(screen.getByLabelText("رسالتك للـAI"), "كمان");
    expect(screen.getByRole("button", { name: "ابعت" })).toBeDisabled();
  });

  it("keeps what was typed and says why when the server refuses", async () => {
    const user = userEvent.setup();
    open(server(), { extra: { [`${DOOR}send/`]: () => jsonResponse({ ok: false, error: "فيه 3 جلسات الـAI بيرد فيها دلوقتي. استنى لما واحدة تخلص.", code: "too_busy" }, 400) } });
    await screen.findByText("ابدأ مراجعة جديدة");
    await user.type(screen.getByLabelText("رسالتك للـAI"), "سؤالي");
    await user.click(screen.getByRole("button", { name: "ابعت" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("فيه 3 جلسات");
    expect(screen.getByLabelText("رسالتك للـAI")).toHaveValue("سؤالي");
  });

  it("refuses a file over the limit before sending anything", async () => {
    const user = userEvent.setup();
    const mocked = open(server());
    await screen.findByText("ابدأ مراجعة جديدة");
    const big = new File(["x"], "big.pdf", { type: "application/pdf" });
    Object.defineProperty(big, "size", { value: 23 * 1024 * 1024 });
    await user.upload(screen.getByLabelText("ملفات للـAI"), big);
    expect(await screen.findByText("فيه 1 ملف أكبر من 22 ميجا ومااتضافش.")).toBeInTheDocument();
    expect(screen.queryByText("big.pdf")).toBeNull();
    expect(posts(mocked, `${DOOR}send/`)).toHaveLength(0);
  });

  it("takes files into one message until the message is full, and says which did not fit", async () => {
    const user = userEvent.setup();
    open(server());
    await screen.findByText("ابدأ مراجعة جديدة");
    const sized = (name: string, megabytes: number) => {
      const file = new File(["x"], name, { type: "application/pdf" });
      Object.defineProperty(file, "size", { value: megabytes * 1024 * 1024 });
      return file;
    };
    // 4 x 22 MB is 88 MB: the fifth would pass the 90 MB a message carries.
    await user.upload(screen.getByLabelText("ملفات للـAI"), [sized("a.pdf", 22), sized("b.pdf", 22), sized("c.pdf", 22), sized("d.pdf", 22), sized("e.pdf", 22)]);
    expect(await screen.findByText(/الملفات في الرسالة الواحدة لحد 90 ميجا. 1 ملف/)).toBeInTheDocument();
    expect(screen.getByText("d.pdf")).toBeInTheDocument();
    expect(screen.queryByText("e.pdf")).toBeNull();
  });

  it("asks again for an answer that failed", async () => {
    const user = userEvent.setup();
    const state = server({ sessions: [session({ id: 5 })], talks: { 5: [line({ id: 1, body: "سؤال" }), line({ id: 2, role: "assistant", status: "error" })] } });
    const mocked = open(state, {
      route: "/lead/ai-review?s=5",
      extra: {
        [`${DOOR}5/retry/`]: () => {
          state.talks[5] = [line({ id: 1, body: "سؤال" }), line({ id: 3, role: "assistant", status: "pending" })];
          return jsonResponse({ ok: true, session: state.sessions[0], messages: state.talks[5] });
        },
      },
    });
    expect(await screen.findByText(/الـAI مردّش/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "جرّب تاني" }));
    await waitFor(() => expect(posts(mocked, `${DOOR}5/retry/`)).toHaveLength(1));
    expect(await screen.findByText(/الـAI بيقرا ويكتب الرد/)).toBeInTheDocument();
  });

  it("deletes a session after asking once", async () => {
    const user = userEvent.setup();
    const state = server({ sessions: [session({ id: 5, title: "هتتمسح" }), session({ id: 4, title: "تفضل" })] });
    const mocked = open(state, {
      extra: {
        [`${DOOR}5/delete/`]: () => {
          state.sessions = state.sessions.filter((row) => row.id !== 5);
          return jsonResponse({ ok: true });
        },
      },
    });
    await screen.findByText("هتتمسح");
    await user.click(screen.getByRole("button", { name: "امسح جلسة هتتمسح" }));
    expect(posts(mocked, `${DOOR}5/delete/`)).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "امسح" }));
    await waitFor(() => expect(posts(mocked, `${DOOR}5/delete/`)).toHaveLength(1));
    await waitFor(() => expect(screen.queryByText("هتتمسح")).toBeNull());
    expect(screen.getByText("تفضل")).toBeInTheDocument();
  });

  it("says why a session cannot be deleted while the AI is answering in it", async () => {
    const user = userEvent.setup();
    open(server({ sessions: [session({ id: 5, title: "شغالة" })] }), {
      extra: { [`${DOOR}5/delete/`]: () => jsonResponse({ ok: false, error: "running" }, 409) },
    });
    await screen.findByText("شغالة");
    await user.click(screen.getByRole("button", { name: "امسح جلسة شغالة" }));
    await user.click(screen.getByRole("button", { name: "امسح" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("الـAI لسه بيرد في الجلسة دي");
    expect(screen.getByText("شغالة")).toBeInTheDocument();
  });

  it("says so, and sends nothing, when the AI check is off", async () => {
    const mocked = open(server({ available: false }));
    expect(await screen.findByText(/فحص الـAI مقفول/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ابعت" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "ارفع ملفات" })).toBeDisabled();
    expect(posts(mocked, `${DOOR}send/`)).toHaveLength(0);
  });

  it("is not for a translator: nothing is asked of the server", async () => {
    const mocked = open(server(), { role: "translator" });
    await waitFor(() => expect(mocked.calls.some((call) => call.url === "/api/v1/me/")).toBe(true));
    expect(mocked.calls.filter((call) => call.url.startsWith(DOOR))).toHaveLength(0);
  });
});
