import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { HelpAnswer, HelpGuide, HelpHome, HelpOrder } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders, type Routes as FetchRoutes } from "../test/helpers";
import { HelpBot } from "./HelpBot";
import { Shell } from "./Shell";

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute("dir");
  document.documentElement.removeAttribute("data-theme");
});

const ACCEPT: HelpGuide = { id: "tr-accept", title: "إزاي أستلم تاسك اتبعتتلي", path: "/translator" };
const WORK: HelpGuide = { id: "tr-work", title: "فين شغلي وإزاي أفتح التاسك", path: "/translator" };
const CHECKIN: HelpGuide = { id: "attendance-checkin", title: "إزاي أسجل حضور", path: "/attendance" };

const STEPS = [
  "إزاي أستلم تاسك اتبعتتلي",
  "1. لما تتبعتلك تاسك بتظهر شاشة «تاسك جديدة ليك» وفيها عداد.",
  "2. اضغط «استلمت» قبل ما العداد يخلص.",
].join("\n");

function home(overrides: Partial<HelpHome> = {}): HelpHome {
  return { ok: true, support: null, ai: false, orders: false, starters: [ACCEPT, WORK, CHECKIN], ...overrides };
}

function answer(overrides: Partial<HelpAnswer> = {}): HelpAnswer {
  return { ok: true, answer: STEPS, answered: true, source: "guide", open: ACCEPT, related: [], order: null, keep: true, ...overrides };
}

function order(overrides: Partial<HelpOrder> = {}): HelpOrder {
  return { id: 5, title: "عمل شيفت", summary: "عمل شيفت جديد «الصبح» من 9:00 ص لـ 5:00 م.", danger: false, expires_in: 600, ...overrides };
}

/** The assistant alone, with a server that gives `home` and answers each question with the next of `answers`. */
function renderBot(options: { home?: HelpHome; answers?: (HelpAnswer | Response)[]; extra?: FetchRoutes; route?: string; lang?: "ar" | "en" } = {}) {
  const queue = [...(options.answers ?? [answer()])];
  const asked: Record<string, unknown>[] = [];
  const mocked = mockFetch({
    "/api/v1/help/ask/": (_url, init) => {
      asked.push(JSON.parse(String(init?.body)));
      const next = queue.shift() ?? answer();
      return next instanceof Response ? next : jsonResponse(next);
    },
    ...(options.extra ?? {}),
    "/api/v1/help/": () => jsonResponse(options.home ?? home()),
  });
  vi.stubGlobal("fetch", mocked.fn);
  const view = renderWithProviders(<HelpBot />, { route: options.route ?? "/tasks/TSK-00012", lang: options.lang });
  return { ...view, calls: mocked.calls, asked };
}

const openIt = async (user = userEvent.setup()) => {
  await user.click(screen.getByTitle(/مساعد النظام|System assistant/));
  return user;
};

describe("the assistant's button and panel", () => {
  it("is closed until the button is pressed, and then offers the role's first questions", async () => {
    const view = renderBot();
    expect(screen.queryByRole("dialog")).toBeNull();
    // Nothing is asked of the server before it is opened.
    expect(view.calls).toHaveLength(0);
    await openIt();
    const panel = screen.getByRole("dialog", { name: "مساعد النظام" });
    expect(await within(panel).findByRole("button", { name: ACCEPT.title })).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: WORK.title })).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: CHECKIN.title })).toBeInTheDocument();
    expect(view.calls.map((call) => call.url)).toEqual(["/api/v1/help/?lang=ar"]);
    expect(screen.getByRole("textbox")).toHaveFocus();
  });

  it("closes with Escape and gives the focus back to the button", async () => {
    renderBot();
    const user = await openIt();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByTitle(/مساعد النظام/)).toHaveFocus();
  });

  it("closes with its own button", async () => {
    renderBot();
    const user = await openIt();
    await user.click(screen.getByRole("button", { name: "اقفل المساعد" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("speaks English when the page does", async () => {
    renderBot({ lang: "en", home: home({ starters: [{ ...ACCEPT, title: "How do I accept a task I was sent" }] }) });
    await userEvent.click(screen.getByTitle("System assistant: ask how to do anything"));
    expect(await screen.findByRole("button", { name: "How do I accept a task I was sent" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/how do I check in/)).toBeInTheDocument();
    expect(screen.getByText("Do not type client details or passwords here.")).toBeInTheDocument();
  });

  it("tells the server which language the page is in, when asking and when an order is run", async () => {
    const run = vi.fn((_url: URL, _init?: RequestInit) => jsonResponse({ ok: true, done: true, status: "done", message: "The shift was made." }));
    const view = renderBot({
      lang: "en",
      home: home({ orders: true }),
      answers: [answer({ answer: "Made.", source: "action", open: null, order: order({ title: "Make a shift", summary: "Make a new company shift." }) })],
      extra: { "/api/v1/help/orders/5/run/": run },
    });
    const user = userEvent.setup();
    await user.click(screen.getByTitle("System assistant: ask how to do anything"));
    await user.type(screen.getByRole("textbox"), "make a shift{Enter}");
    expect(view.asked[0]).toMatchObject({ lang: "en" });
    await user.click(await screen.findByRole("button", { name: "Run" }));
    expect(await screen.findByText("The shift was made.")).toBeInTheDocument();
    expect(JSON.parse(String(run.mock.calls[0]![1]?.body))).toEqual({ lang: "en" });
  });

  it("tells the owner who has switched orders on that orders can be given, and nobody else", async () => {
    renderBot({ home: home({ orders: true }) });
    await openIt();
    expect(await screen.findByText(/تقدر كمان تديني أوامر/)).toBeInTheDocument();
  });

  it("does not mention orders to anybody else", async () => {
    renderBot();
    await openIt();
    await screen.findByRole("button", { name: ACCEPT.title });
    expect(screen.queryByText(/أوامر/)).toBeNull();
  });
});

describe("asking", () => {
  it("answers a picked question from that guide, as numbered steps with the names set apart, and a button to the page", async () => {
    const view = renderBot();
    const user = await openIt();
    await user.click(await screen.findByRole("button", { name: ACCEPT.title }));
    expect(view.asked[0]).toMatchObject({ question: "", guide: "tr-accept", lang: "ar", page: "/tasks/TSK-00012", history: [] });
    const items = await screen.findAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(items[1]!).getByText("«استلمت»")).toHaveClass("help__name");
    // The title above the list is bold; the picked question is in the conversation as what the person said.
    expect(screen.getAllByText(ACCEPT.title).some((one) => one.classList.contains("help__title"))).toBe(true);
    const go = screen.getByRole("link", { name: "افتح الصفحة" });
    expect(go).toHaveAttribute("href", "/translator");
  });

  it("sends what was typed with Enter, the page, and the conversation so far", async () => {
    const view = renderBot({ answers: [answer(), answer({ answer: "تمام.", open: null })] });
    const user = await openIt();
    await user.type(screen.getByRole("textbox"), "ازاي استلم تاسك{Enter}");
    await screen.findAllByRole("listitem");
    expect(view.asked[0]).toMatchObject({ question: "ازاي استلم تاسك", page: "/tasks/TSK-00012", history: [] });
    expect(screen.getByRole("textbox")).toHaveValue("");

    await user.type(screen.getByRole("textbox"), "وبعدين{Enter}");
    await waitFor(() => expect(view.asked).toHaveLength(2));
    expect(view.asked[1]).toMatchObject({ question: "وبعدين" });
    const history = view.asked[1]!.history as { role: string; text: string }[];
    expect(history.map((turn) => turn.role)).toEqual(["user", "assistant"]);
    expect(history[0]!.text).toBe("ازاي استلم تاسك");
  });

  it("does not send on Shift+Enter, or when there is nothing to send", async () => {
    const view = renderBot();
    const user = await openIt();
    const box = screen.getByRole("textbox");
    await user.type(box, "{Enter}");
    await user.type(box, "سطر{Shift>}{Enter}{/Shift}تاني");
    expect(view.asked).toHaveLength(0);
    expect(box).toHaveValue("سطر\nتاني");
    expect(screen.getByRole("button", { name: "إرسال" })).toBeEnabled();
    await user.clear(box);
    expect(screen.getByRole("button", { name: "إرسال" })).toBeDisabled();
  });

  it("offers the closest guides when nothing answers, and asks from the one picked", async () => {
    const view = renderBot({ answers: [answer({ answer: "مالقيتش خطوات.", answered: false, source: "none", open: null, related: [WORK, CHECKIN] }), answer()] });
    const user = await openIt();
    await user.type(screen.getByRole("textbox"), "كام سعر الدولار{Enter}");
    expect(await screen.findByText("مالقيتش خطوات.")).toBeInTheDocument();
    const bubble = screen.getByText("مالقيتش خطوات.").closest(".help__bubble") as HTMLElement;
    await user.click(within(bubble).getByRole("button", { name: CHECKIN.title }));
    await waitFor(() => expect(view.asked).toHaveLength(2));
    expect(view.asked[1]).toMatchObject({ guide: "attendance-checkin", question: "" });
  });

  it("says so when the server cannot answer, and does not send that error back as part of the conversation", async () => {
    const view = renderBot({ answers: [jsonResponse({ ok: false, error: "server" }, 500), answer()] });
    const user = await openIt();
    await user.type(screen.getByRole("textbox"), "ازاي{Enter}");
    expect(await screen.findByText("مقدرتش أرد دلوقتي. جرّب تاني.")).toBeInTheDocument();
    await user.type(screen.getByRole("textbox"), "ازاي استلم تاسك{Enter}");
    await waitFor(() => expect(view.asked).toHaveLength(2));
    expect((view.asked[1]!.history as { role: string }[]).map((turn) => turn.role)).toEqual(["user"]);
  });

  it("does not send back, as conversation, an answer the server said names people", async () => {
    const view = renderBot({
      answers: [answer({ answer: "فيه أكتر من واحد: Ali Mostafa، Ahmed Samir.", open: null, keep: false, source: "ai" }), answer()],
    });
    const user = await openIt();
    await user.type(screen.getByRole("textbox"), "وقّف ahmed{Enter}");
    expect(await screen.findByText(/Ali Mostafa/)).toBeInTheDocument();
    await user.type(screen.getByRole("textbox"), "Ahmed Samir{Enter}");
    await waitFor(() => expect(view.asked).toHaveLength(2));
    expect((view.asked[1]!.history as { role: string }[]).map((turn) => turn.role)).toEqual(["user"]);
    expect(JSON.stringify(view.asked[1])).not.toContain("Ali Mostafa");
  });

  it("says when it is asked too fast", async () => {
    renderBot({ answers: [jsonResponse({ ok: false, error: "slow_down" }, 429)] });
    const user = await openIt();
    await user.type(screen.getByRole("textbox"), "ازاي{Enter}");
    expect(await screen.findByText("بتسأل بسرعة. استنى شوية وجرّب تاني.")).toBeInTheDocument();
  });

  it("draws an answer as text, never as markup", async () => {
    renderBot({ answers: [answer({ answer: "1. <img src=x onerror=alert(1)> و«زرار»\n<b>bold</b>", open: null })] });
    const user = await openIt();
    await user.type(screen.getByRole("textbox"), "x{Enter}");
    expect(await screen.findByText(/<img src=x/)).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText("<b>bold</b>")).toBeInTheDocument();
    expect(document.querySelector(".help__log b:not(.help__name)")).toBeNull();
  });

  it("keeps the person's own words as they wrote them, in either direction", async () => {
    renderBot();
    const user = await openIt();
    await user.type(screen.getByRole("textbox"), "how do I check in{Enter}");
    await screen.findAllByRole("listitem");
    expect(screen.getByText("how do I check in")).toHaveAttribute("dir", "auto");
  });
});

describe("technical support", () => {
  it("is one button away: it opens the chat with them and puts the assistant away", async () => {
    renderBot({ home: home({ support: { id: 9, name: "Sami" } }) });
    const user = await openIt();
    await user.click(await screen.findByRole("button", { name: "تواصل مع الدعم الفني" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("goes to the staff chat with that person", async () => {
    const mocked = mockFetch({ "/api/v1/help/": () => jsonResponse(home({ support: { id: 9, name: "Sami" } })) });
    vi.stubGlobal("fetch", mocked.fn);
    function Where() {
      const here = useLocation();
      return <div data-testid="where">{here.pathname + here.search}</div>;
    }
    renderWithProviders(
      <>
        <HelpBot />
        <Where />
      </>,
    );
    const user = await openIt();
    await user.click(await screen.findByRole("button", { name: "تواصل مع الدعم الفني" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/chats/u9?type=staff");
  });

  it("is not offered when there is no support account, or to the support person themself", async () => {
    renderBot({ home: home({ support: null }) });
    await openIt();
    await screen.findByRole("button", { name: ACCEPT.title });
    expect(screen.queryByRole("button", { name: "تواصل مع الدعم الفني" })).toBeNull();
  });

  it("says it in English too", async () => {
    renderBot({ lang: "en", home: home({ support: { id: 9, name: "Sami" } }) });
    await userEvent.click(screen.getByTitle("System assistant: ask how to do anything"));
    expect(await screen.findByRole("button", { name: "Contact technical support" })).toBeInTheDocument();
  });
});

describe("an order for the owner", () => {
  const prepared = () => answer({ answer: "جهّزت الأمر ده. راجعه، ولو تمام اضغط «نفّذ»:", source: "action", open: null, order: order() });

  it("shows the card the server wrote and does nothing until it is pressed", async () => {
    const view = renderBot({ home: home({ orders: true }), answers: [prepared()] });
    const user = await openIt();
    await user.type(screen.getByRole("textbox"), "اعمل شيفت من 9 ل 5{Enter}");
    expect(await screen.findByText("عمل شيفت")).toBeInTheDocument();
    expect(screen.getByText(/عمل شيفت جديد «الصبح»/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "نفّذ" })).toBeEnabled();
    expect(view.calls.filter((call) => call.url.includes("/orders/"))).toHaveLength(0);
  });

  it("runs it on «نفّذ», once, and says what was done", async () => {
    const run = vi.fn(() => jsonResponse({ ok: true, done: true, status: "done", message: "الشيفت اتعمل." }));
    const view = renderBot({ home: home({ orders: true }), answers: [prepared()], extra: { "/api/v1/help/orders/5/run/": run } });
    const user = await openIt();
    await user.type(screen.getByRole("textbox"), "اعمل شيفت{Enter}");
    await user.click(await screen.findByRole("button", { name: "نفّذ" }));
    expect(await screen.findByText("الشيفت اتعمل.")).toBeInTheDocument();
    expect(run).toHaveBeenCalledTimes(1);
    const call = view.calls.find((one) => one.url === "/api/v1/help/orders/5/run/")!;
    expect(call.init?.method).toBe("POST");
    expect(JSON.parse(String(call.init?.body))).toEqual({ lang: "ar" });
    // Nothing left to press.
    expect(screen.queryByRole("button", { name: "نفّذ" })).toBeNull();
    expect(screen.queryByRole("button", { name: "إلغاء" })).toBeNull();
  });

  it("says why when the door refused", async () => {
    renderBot({
      home: home({ orders: true }),
      answers: [prepared()],
      extra: { "/api/v1/help/orders/5/run/": () => jsonResponse({ ok: true, done: false, status: "failed", message: "بداية الشيفت ونهايته نفس الوقت." }) },
    });
    const user = await openIt();
    await user.type(screen.getByRole("textbox"), "اعمل شيفت{Enter}");
    await user.click(await screen.findByRole("button", { name: "نفّذ" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("بداية الشيفت ونهايته نفس الوقت.");
  });

  it("says what happened to an order that expired, was done already, or was switched off", async () => {
    const cases: [string, number, string][] = [
      ["expired", 409, "الأمر انتهت مدته. اطلبه تاني."],
      ["already_done", 409, "الأمر ده اتنفّذ أو اتلغى قبل كده."],
      ["orders_off", 403, "الأوامر مقفولة من الإعدادات."],
    ];
    for (const [code, status, words] of cases) {
      const view = renderBot({
        home: home({ orders: true }),
        answers: [prepared()],
        extra: { "/api/v1/help/orders/5/run/": () => jsonResponse({ ok: false, error: code }, status) },
      });
      const user = await openIt();
      await user.type(screen.getByRole("textbox"), "اعمل شيفت{Enter}");
      await user.click(await screen.findByRole("button", { name: "نفّذ" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(words);
      view.unmount();
    }
  });

  it("withdraws it on «إلغاء»", async () => {
    const cancel = vi.fn(() => jsonResponse({ ok: true }));
    renderBot({ home: home({ orders: true }), answers: [prepared()], extra: { "/api/v1/help/orders/5/cancel/": cancel } });
    const user = await openIt();
    await user.type(screen.getByRole("textbox"), "اعمل شيفت{Enter}");
    await user.click(await screen.findByRole("button", { name: "إلغاء" }));
    expect(await screen.findByText("اتلغى.")).toBeInTheDocument();
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "نفّذ" })).toBeNull();
  });

  it("withdraws the card before it when a newer order comes, so only the newest can be pressed", async () => {
    renderBot({
      home: home({ orders: true }),
      answers: [prepared(), answer({ answer: "جهّزت الأمر ده.", source: "action", open: null, order: order({ id: 6, title: "إلغاء تاسك", summary: "إلغاء التاسك TSK-00001.", danger: true }) })],
    });
    const user = await openIt();
    await user.type(screen.getByRole("textbox"), "اعمل شيفت{Enter}");
    await screen.findByRole("button", { name: "نفّذ" });
    await user.type(screen.getByRole("textbox"), "الغي التاسك{Enter}");
    expect(await screen.findByText("اتلغى: فيه أمر أحدث.")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "نفّذ" })).toHaveLength(1);
  });

  it("draws a card that stops something in red", async () => {
    renderBot({
      home: home({ orders: true }),
      answers: [answer({ answer: "جهّزت.", source: "action", open: null, order: order({ danger: true, title: "إلغاء تاسك" }) })],
    });
    const user = await openIt();
    await user.type(screen.getByRole("textbox"), "الغي{Enter}");
    const run = await screen.findByRole("button", { name: "نفّذ" });
    expect(run).toHaveClass("btn--danger");
    expect(run.closest(".help__order")).toHaveClass("is-danger");
  });
});

describe("in the top bar", () => {
  it("is in the frame of every page, beside the bell", async () => {
    const mocked = mockFetch({
      "/api/prefs/": () => jsonResponse({ ok: true }),
      "/api/v1/me/": () => jsonResponse(me({ role: "translator", short_name: "Mona", name: "Mona Salem", initials: "MS" })),
    });
    vi.stubGlobal("fetch", mocked.fn);
    renderWithProviders(
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<div>home page</div>} />
        </Route>
      </Routes>,
    );
    const button = await screen.findByTitle(/مساعد النظام/);
    expect(button.compareDocumentPosition(screen.getByTitle("التنبيهات")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
