import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AiChatLine, OpsTask } from "../../api/types";
import { ToastProvider } from "../Toasts";
import { jsonResponse, mockFetch, renderWithProviders } from "../../test/helpers";
import { AiChatCard } from "./AiChatCard";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const CODE = "TSK-00001";
const DOOR = `/api/v1/tasks/${CODE}/ai-chat/`;
const SEND = `${DOOR}send/`;

const task = (chat: boolean | undefined = true) => ({ code: CODE, lead: { ai_chat: chat } }) as unknown as OpsTask;
const line = (over: Partial<AiChatLine> & { id: number }): AiChatLine => ({
  role: "user",
  body: "",
  status: "done",
  at: "10:15",
  file: null,
  ...over,
});

function open(messages: AiChatLine[], pending = false, extra: Record<string, () => Response> = {}, chat: boolean | undefined = true) {
  // The server remembers what was sent: the page asks again after a send and must find it there.
  const state = { messages, pending };
  const mocked = mockFetch({
    [SEND]: () => {
      state.messages = [...messages, line({ id: 90, body: "سؤالي" }), line({ id: 91, role: "assistant", status: "pending" })];
      state.pending = true;
      return jsonResponse({ ok: true, ...state });
    },
    ...extra,
    [DOOR]: () => jsonResponse({ ok: true, ...state }),
  });
  vi.stubGlobal("fetch", mocked.fn);
  renderWithProviders(
    <ToastProvider>
      <AiChatCard task={task(chat)} />
    </ToastProvider>,
  );
  return mocked;
}

const sent = (mocked: { calls: { url: string; init?: RequestInit }[] }) => mocked.calls.filter((call) => call.url === SEND && call.init?.method === "POST");

describe("AiChatCard: the team leader talks to the AI", () => {
  it("is not drawn, and asks for nothing, where the task is not the AI's", () => {
    const mocked = open([], false, {}, false);
    expect(screen.queryByText("اتكلم مع الـAI")).toBeNull();
    expect(mocked.calls).toHaveLength(0);
  });

  it("shows the talk, each line on its own side, and a file the leader sent", async () => {
    open([
      line({ id: 1, body: "ليه اخترت الكلمة دي؟", file: { id: 5, url: "/files/aichat/p.png", name: "p.png", size: "1 KB", image: true } }),
      line({ id: 2, role: "assistant", body: "عشان السياق" }),
    ]);
    expect(await screen.findByText("ليه اخترت الكلمة دي؟")).toBeInTheDocument();
    expect(screen.getByText("عشان السياق").closest("[data-line]")).toHaveAttribute("data-line", "assistant");
    expect(screen.getByAltText("p.png")).toHaveAttribute("src", "/files/aichat/p.png");
  });

  it("says so when there is nothing yet", async () => {
    open([]);
    expect(await screen.findByText("لسه مفيش كلام. اكتب للـAI.")).toBeInTheDocument();
  });

  it("sends the words with no question asked first, and empties the box", async () => {
    const user = userEvent.setup();
    const mocked = open([]);
    await screen.findByText("لسه مفيش كلام. اكتب للـAI.");
    const box = screen.getByLabelText("رسالتك للـAI");
    await user.type(box, "  سؤالي ");
    await user.click(screen.getByRole("button", { name: "ابعت" }));
    await waitFor(() => expect(sent(mocked)).toHaveLength(1));
    const body = sent(mocked)[0]!.init!.body as FormData;
    expect(body.get("text")).toBe("سؤالي");
    expect(body.get("file")).toBeNull();
    // No dialog stood in the way.
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(box).toHaveValue(""));
    expect(await screen.findByText("الـAI بيكتب...")).toBeInTheDocument();
  });

  it("sends a picture with the words", async () => {
    const user = userEvent.setup();
    const mocked = open([]);
    await screen.findByText("لسه مفيش كلام. اكتب للـAI.");
    await user.upload(screen.getByLabelText("ملف للـAI"), new File(["x"], "page.png", { type: "image/png" }));
    expect(screen.getByText("page.png")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "ابعت" }));
    await waitFor(() => expect(sent(mocked)).toHaveLength(1));
    expect((sent(mocked)[0]!.init!.body as FormData).get("file")).toBeInstanceOf(File);
    await waitFor(() => expect(screen.queryByText("page.png")).toBeNull());
  });

  it("cannot send nothing, nor while an answer is being written", async () => {
    const user = userEvent.setup();
    open([line({ id: 1, body: "سؤال" }), line({ id: 2, role: "assistant", status: "pending" })], true);
    expect(await screen.findByText("الـAI بيكتب...")).toBeInTheDocument();
    await user.type(screen.getByLabelText("رسالتك للـAI"), "كمان سؤال");
    expect(screen.getByRole("button", { name: "استنى..." })).toBeDisabled();
  });

  it("keeps what was typed and says why when the server refuses", async () => {
    const user = userEvent.setup();
    const mocked = open([], false, { [SEND]: () => jsonResponse({ ok: false, error: "الـAI لسه بيكتب الرد. استنى لما يخلص.", code: "busy" }, 400) });
    await screen.findByText("لسه مفيش كلام. اكتب للـAI.");
    await user.type(screen.getByLabelText("رسالتك للـAI"), "سؤالي");
    await user.click(screen.getByRole("button", { name: "ابعت" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("الـAI لسه بيكتب الرد.");
    expect(screen.getByLabelText("رسالتك للـAI")).toHaveValue("سؤالي");
    expect(sent(mocked)).toHaveLength(1);
  });

  it("refuses a file over 10 MB before sending anything", async () => {
    const user = userEvent.setup();
    const mocked = open([]);
    await screen.findByText("لسه مفيش كلام. اكتب للـAI.");
    const big = new File(["x"], "big.pdf", { type: "application/pdf" });
    Object.defineProperty(big, "size", { value: 11 * 1024 * 1024 });
    await user.upload(screen.getByLabelText("ملف للـAI"), big);
    expect(await screen.findByRole("alert")).toHaveTextContent("الملف أكبر من 10 ميجا.");
    expect(sent(mocked)).toHaveLength(0);
  });

  it("marks an answer that failed", async () => {
    open([line({ id: 1, body: "سؤال" }), line({ id: 2, role: "assistant", status: "error" })]);
    expect(await screen.findByText(/الـAI مردّش/)).toBeInTheDocument();
  });
});
