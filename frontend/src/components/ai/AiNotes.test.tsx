import { QueryClient } from "@tanstack/react-query";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { qk } from "../../api/keys";
import type { AiNote, ChatAiNotes, Role, TaskAiNotes } from "../../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../../test/helpers";
import { ToastProvider } from "../Toasts";
import { AiNotesCard } from "./AiNotesCard";
import { AiNotesPanel } from "./AiNotesPanel";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function note(over: Partial<AiNote> = {}): AiNote {
  return {
    severity: "medium",
    location: "page 2",
    category: { ar: "مصطلحات", en: "Terminology" },
    source: "the source words",
    translation: "the translated words",
    compared: true,
    text: { ar: "المصطلح غلط", en: "The term is wrong" },
    meaning: "المعنى في الأصل",
    ...over,
  };
}

function notes(over: Partial<TaskAiNotes> = {}, check: Partial<NonNullable<TaskAiNotes["check"]>> | null = {}): TaskAiNotes {
  return {
    ok: true,
    task: { code: "TSK-00001", title: "A contract" },
    can_recheck: true,
    check:
      check === null
        ? null
        : { id: 3, status: "issues", count: 2, at: { ar: "10-02 5:30 PM", en: "10-02 5:30 PM" }, automatic: true, old: false, summary: "Mostly fine.", error: "", ...check },
    issues: [note({ severity: "high" }), note({ severity: "low", location: "", category: null })],
    ...over,
  };
}

// ---------------------------------------------------------------------------------------------------------------------
// The box on a task page
// ---------------------------------------------------------------------------------------------------------------------

function openCard(
  body: () => TaskAiNotes | Response,
  recheck: () => Response | Promise<Response> = () => jsonResponse({ ok: true }),
  lang: "ar" | "en" = "ar",
) {
  const mocked = mockFetch({
    "/api/tasks/TSK-00001/ai-recheck/": recheck,
    "/api/v1/tasks/TSK-00001/ai-notes/": () => {
      const answer = body();
      return answer instanceof Response ? answer : jsonResponse(answer);
    },
  });
  vi.stubGlobal("fetch", mocked.fn);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 } } });
  const view = renderWithProviders(
    <ToastProvider>
      <AiNotesCard code="TSK-00001" />
    </ToastProvider>,
    { lang, client },
  );
  return { ...view, calls: mocked.calls };
}

describe("AiNotesCard", () => {
  it("is not there when no check has run, and not there for an answer that is not one", async () => {
    const first = openCard(() => notes({}, null));
    await waitFor(() => expect(first.calls.length).toBeGreaterThan(0));
    expect(document.querySelector("#aiNotes")).toBeNull();
    first.unmount();
    const second = openCard(() => jsonResponse({ ok: true }));
    await waitFor(() => expect(second.calls.length).toBeGreaterThan(0));
    expect(document.querySelector("#aiNotes")).toBeNull();
  });

  it("says how many notes, when, and that it ran by itself", async () => {
    openCard(() => notes());
    expect(await screen.findByText("ملاحظات الـ AI على الترجمة")).toBeInTheDocument();
    const box = document.querySelector("#aiNotes") as HTMLElement;
    expect(box).toHaveClass("ai-notes--issues");
    expect(box.querySelector(".card__head .badge")).toHaveTextContent("2 ملاحظة");
    expect(box.querySelector(".ai-notes__when")).toHaveTextContent("10-02 5:30 PM · تلقائي");
    expect(within(box).getByText("Mostly fine.")).toBeInTheDocument();
  });

  it("does not say automatic of a check somebody asked for", async () => {
    openCard(() => notes({}, { automatic: false }));
    await screen.findByText("ملاحظات الـ AI على الترجمة");
    expect(document.querySelector(".ai-notes__when")).not.toHaveTextContent("تلقائي");
  });

  it("lists the notes most serious first as the server sent them, with the two texts side by side and what the source means", async () => {
    openCard(() => notes());
    await screen.findByText("ملاحظات الـ AI على الترجمة");
    const items = Array.from(document.querySelectorAll("li.ai-issue"));
    expect(items.map((item) => item.getAttribute("data-severity"))).toEqual(["high", "low"]);
    const first = items[0] as HTMLElement;
    expect(within(first).getByText("مهم")).toHaveClass("ai-issue__sev");
    expect(within(first).getByText("مصطلحات")).toHaveClass("ai-issue__cat");
    expect(within(first).getByText("page 2")).toHaveClass("ai-issue__where");
    expect(within(first).getByText("the source words")).toBeInTheDocument();
    expect(within(first).getByText("the translated words")).toBeInTheDocument();
    expect(within(first).getByText("المصطلح غلط")).toBeInTheDocument();
    expect(within(first).getByText("المعنى في الأصل")).toBeInTheDocument();
    // The second has no place and no category: nothing is drawn for them.
    const second = items[1] as HTMLElement;
    expect(second.querySelector(".ai-issue__where")).toBeNull();
    expect(second.querySelector(".ai-issue__cat")).toBeNull();
  });

  it("says a translation that is missing from the pair, and draws no pair for a check that did not quote them", async () => {
    openCard(() =>
      notes({ issues: [note({ translation: "" }), note({ compared: false, source: "", translation: "" })] }),
    );
    await screen.findByText("ملاحظات الـ AI على الترجمة");
    expect(screen.getByText("(مش موجودة في الترجمة)")).toBeInTheDocument();
    const items = Array.from(document.querySelectorAll("li.ai-issue"));
    expect(items[1]!.querySelector(".ai-issue__pair")).toBeNull();
  });

  it("is in the page's language", async () => {
    openCard(() => notes(), undefined, "en");
    expect(await screen.findByText("AI notes on the translation")).toBeInTheDocument();
    expect(screen.getAllByText("The term is wrong")).toHaveLength(2);
    expect(screen.getByText("High")).toBeInTheDocument();
    expect(screen.getByText("Terminology")).toBeInTheDocument();
    expect(screen.getByText("Suggestions only - the AI never edits the translation; the team leader decides.")).toBeInTheDocument();
  });

  it("says nothing obvious was found, and that a person's own review still stands", async () => {
    openCard(() => notes({ issues: [] }, { status: "clean", count: 0 }));
    expect(await screen.findByText("الـ AI مالقاش أخطاء واضحة. المراجعة البشرية لسه مطلوبة.")).toBeInTheDocument();
    expect(document.querySelector("#aiNotes")).toHaveClass("ai-notes--clean");
    expect(screen.getByText("مفيش أخطاء واضحة")).toHaveClass("badge--ok");
  });

  it("says a check did not finish, with why, and tells the leader to review it themselves", async () => {
    openCard(() => notes({ issues: [] }, { status: "error", count: 0, error: "HTTP 529: overloaded", summary: "" }));
    expect(await screen.findByText("الفحص مخلصش — راجعها بنفسك.")).toBeInTheDocument();
    expect(screen.getByText("HTTP 529: overloaded")).toHaveClass("mono");
    expect(document.querySelector("#aiNotes")).toHaveClass("ai-notes--error");
    // No "suggestions only" line under an error: there are no suggestions.
    expect(screen.queryByText(/دي اقتراحات بس/)).toBeNull();
  });

  it("says the AI is reading while it runs, and asks again on its own until it has finished", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    let running = true;
    const view = openCard(() => (running ? notes({ issues: [], can_recheck: false }, { status: "running", count: 0, summary: "" }) : notes()));
    expect(await screen.findByText("الـ AI بيقرا الملفات دلوقتي. الصفحة هتتحدث لوحدها أول ما يخلص.")).toBeInTheDocument();
    // No button while it runs (the server said so): the same page cannot start a second one.
    expect(screen.queryByRole("button", { name: "أعد الفحص" })).toBeNull();
    expect(screen.getByText("شغال دلوقتي")).toHaveClass("badge--wait");
    running = false;
    await act(async () => void (await vi.advanceTimersByTimeAsync(5200)));
    expect(await screen.findByText("Mostly fine.")).toBeInTheDocument();
    expect(view.calls.filter((call) => call.url === "/api/v1/tasks/TSK-00001/ai-notes/").length).toBeGreaterThan(1);
  });

  it("warns that a check from before the comparison is old and says what to do", async () => {
    openCard(() => notes({}, { old: true }));
    expect(await screen.findByText(/الملاحظات دي من الفحص القديم/)).toBeInTheDocument();
  });

  it("asks for the check again, and says it has started", async () => {
    const user = userEvent.setup();
    const view = openCard(() => notes());
    await user.click(await screen.findByRole("button", { name: "أعد الفحص" }));
    expect(await screen.findByText("الفحص بدأ. الملاحظات هتظهر هنا أول ما يخلص.")).toBeInTheDocument();
    const call = view.calls.find((one) => one.url === "/api/tasks/TSK-00001/ai-recheck/")!;
    expect(call.init?.method).toBe("POST");
    await waitFor(() => expect(view.calls.filter((one) => one.url === "/api/v1/tasks/TSK-00001/ai-notes/").length).toBeGreaterThan(1));
  });

  it("says why it was refused in the server's own words", async () => {
    const user = userEvent.setup();
    openCard(() => notes(), () => jsonResponse({ ok: false, error: "فحص الـAI متوقف من الإعدادات." }, 400));
    await user.click(await screen.findByRole("button", { name: "أعد الفحص" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("فحص الـAI متوقف من الإعدادات.");
  });

  it("says it is not allowed on a 403, and does not call it a failure to reach the server", async () => {
    const user = userEvent.setup();
    openCard(() => notes(), () => jsonResponse({ ok: false, error: "forbidden" }, 403));
    await user.click(await screen.findByRole("button", { name: "أعد الفحص" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("مش مسموحلك.");
  });

  it("offers no button when the server says a check cannot be asked for", async () => {
    openCard(() => notes({ can_recheck: false }));
    await screen.findByText("ملاحظات الـ AI على الترجمة");
    expect(screen.queryByRole("button", { name: "أعد الفحص" })).toBeNull();
  });

  it("draws nothing for a person the door refused", async () => {
    const view = openCard(() => jsonResponse({ ok: false, error: "not_found" }, 404));
    await waitFor(() => expect(view.calls.length).toBeGreaterThan(0));
    expect(document.querySelector("#aiNotes")).toBeNull();
    // And is not asked again every few seconds: a refusal is written to the audit log each time.
    expect(view.calls.filter((call) => call.url === "/api/v1/tasks/TSK-00001/ai-notes/")).toHaveLength(1);
  });

  it("asks nothing when it is not enabled", async () => {
    const mocked = mockFetch({});
    vi.stubGlobal("fetch", mocked.fn);
    renderWithProviders(
      <ToastProvider>
        <AiNotesCard code="TSK-00001" enabled={false} />
      </ToastProvider>,
    );
    await act(async () => void (await new Promise((resolve) => setTimeout(resolve, 20))));
    expect(mocked.calls).toEqual([]);
  });
});

// ---------------------------------------------------------------------------------------------------------------------
// The panel beside a leader's chat
// ---------------------------------------------------------------------------------------------------------------------

function panel(over: Partial<NonNullable<ChatAiNotes["notes"]>> | null = {}) {
  return {
    ok: true,
    notes: over === null ? null : { task: { code: "TSK-00001", title: "A contract" }, count: 2, issues: [note({ severity: "high" }), note({ location: "" })], ...over },
  } as ChatAiNotes;
}

function openPanel(code: string, body: () => ChatAiNotes | Response, enabled = true, lang: "ar" | "en" = "ar", role: Role = "team_lead") {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role })),
    "/api/v1/groups/12/ai-notes/": () => {
      const answer = body();
      return answer instanceof Response ? answer : jsonResponse(answer);
    },
    "/api/v1/staff/5/ai-notes/": () => {
      const answer = body();
      return answer instanceof Response ? answer : jsonResponse(answer);
    },
  });
  vi.stubGlobal("fetch", mocked.fn);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 } } });
  const view = renderWithProviders(<AiNotesPanel code={code} enabled={enabled} />, { lang, client });
  return { ...view, calls: mocked.calls };
}

const panelCalls = (calls: { url: string }[]) => calls.filter((call) => call.url.endsWith("/ai-notes/")).map((call) => call.url);

describe("AiNotesPanel", () => {
  it("is open beside a work group, with the task, how many notes, and who is the only one who sees them", async () => {
    openPanel("g12", () => panel());
    const box = await screen.findByText("اقتراحات الـAI");
    const details = box.closest("details") as HTMLElement;
    expect(details).toHaveAttribute("open");
    expect(within(details).getByText("TSK-00001")).toHaveClass("mono");
    expect(within(details).getByText("2")).toHaveClass("chip");
    expect(within(details).getByText("دي اقتراحات مش تصحيحات. المراجعة قرارك إنت، ومحدش غيرك شايف الكلام ده.")).toBeInTheDocument();
  });

  it("lists each note with where it is and how serious", async () => {
    openPanel("u5", () => panel());
    await screen.findByText("اقتراحات الـAI");
    const items = Array.from(document.querySelectorAll(".ai-notes__list li"));
    expect(items).toHaveLength(2);
    expect(within(items[0] as HTMLElement).getByText("page 2")).toHaveClass("mono");
    expect(within(items[0] as HTMLElement).getByText("high")).toHaveClass("chip");
    expect(items[1]!.querySelector("b")).toBeNull();
    expect(items[1]).toHaveTextContent("المصطلح غلط");
  });

  it("asks the room the code names: a group by its id, a colleague by theirs", async () => {
    const group = openPanel("g12", () => panel());
    await screen.findByText("اقتراحات الـAI");
    expect(panelCalls(group.calls)).toEqual(["/api/v1/groups/12/ai-notes/"]);
    group.unmount();
    const staff = openPanel("u5", () => panel());
    await screen.findByText("اقتراحات الـAI");
    expect(panelCalls(staff.calls)).toEqual(["/api/v1/staff/5/ai-notes/"]);
  });

  it("asks nothing for a client's conversation, an address that is not a room, or a person who is not a leader", async () => {
    for (const [code, enabled] of [["CL-0001", true], ["g12abc", true], ["x5", true], ["g12", false]] as [string, boolean][]) {
      const view = openPanel(code, () => panel(), enabled);
      await act(async () => void (await new Promise((resolve) => setTimeout(resolve, 20))));
      expect(panelCalls(view.calls), code).toEqual([]);
      expect(document.querySelector("[data-ai-panel]")).toBeNull();
      view.unmount();
    }
  });

  it("is not there when there is nothing to say", async () => {
    const view = openPanel("g12", () => panel(null));
    await waitFor(() => expect(panelCalls(view.calls)).toHaveLength(1));
    expect(document.querySelector("[data-ai-panel]")).toBeNull();
  });

  it("is not there for a conversation the door refused, and is not asked again", async () => {
    const view = openPanel("g12", () => jsonResponse({ ok: false, error: "not_found" }, 404));
    await waitFor(() => expect(panelCalls(view.calls)).toHaveLength(1));
    expect(document.querySelector("[data-ai-panel]")).toBeNull();
  });

  it("opens the task on the classic page, where the leader's own page still is", async () => {
    openPanel("g12", () => panel());
    const link = await screen.findByRole("link", { name: "افتح التاسك" });
    expect(link.getAttribute("href")).toBe("/tasks/TSK-00001/");
  });

  it("asks again when the chat's doorbell rings, and the panel goes when the notes do", async () => {
    const state: { now: ChatAiNotes } = { now: panel() };
    const view = openPanel("g12", () => state.now);
    await screen.findByText("اقتراحات الـAI");
    state.now = panel(null);
    await act(async () => {
      await view.client.invalidateQueries({ queryKey: qk.chats });
    });
    await waitFor(() => expect(document.querySelector("[data-ai-panel]")).toBeNull());
  });

  it("is in English too", async () => {
    openPanel("g12", () => panel(), true, "en");
    expect(await screen.findByText("AI suggestions")).toBeInTheDocument();
    expect(screen.getByText("Suggestions, not corrections. The review is yours, and nobody else sees this.")).toBeInTheDocument();
    for (const item of Array.from(document.querySelectorAll(".ai-notes__list li"))) expect(item).toHaveTextContent("The term is wrong");
    expect(screen.getByRole("link", { name: "Open the task" })).toBeInTheDocument();
  });
});

describe("the two surfaces share one reading", () => {
  it("keeps the query keys where a doorbell reaches them: the box with the boards, the panel with the chats", () => {
    expect(qk.aiNotes("TSK-00001").slice(0, 1)).toEqual(qk.boards);
    expect(qk.chatAiNotes("g12").slice(0, 1)).toEqual(qk.chats);
  });
});
