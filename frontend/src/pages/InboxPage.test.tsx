import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { MailListResponse, MailRow, Role } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { InboxPage } from "./InboxPage";

afterEach(() => vi.unstubAllGlobals());

const URL_LIST = "/api/v1/mail/threads/";

function row(key: string, over: Partial<MailRow> = {}): MailRow {
  return {
    key,
    id: 11,
    from: "CL-0001",
    code: "CL-0001",
    count: 1,
    at: { ar: "2026-10-02 5:30 م", en: "2026-10-02 5:30 PM" },
    subject: `Subject of ${key}`,
    snippet: `Snippet of ${key}`,
    unread: false,
    blocked: false,
    answered: false,
    tasks: [],
    files: 0,
    claimers: [],
    ...over,
  };
}

function list(over: Partial<MailListResponse> = {}): MailListResponse {
  return {
    ok: true,
    state: "",
    q: "",
    threads: [row("k1", { id: 12, count: 3, unread: true }), row("k2", { id: 21, from: "", code: "" })],
    unseen: 1,
    unclaimed: 2,
    blocked: 0,
    mail: { configured: true, last_fetch: { ar: "2026-10-02 5:00 م", en: "2026-10-02 5:00 PM" }, last_count: 4, last_error: "" },
    ...over,
  };
}

function serve(body: (url: URL) => Response, role: Role = "operation", extra: Record<string, () => Response> = {}) {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role, is_admin: role === "admin" })),
    ...extra,
    [URL_LIST]: body,
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function Where() {
  const location = useLocation();
  return <div data-testid="where">{location.pathname + location.search}</div>;
}

function open(route = "/inbox", lang: "ar" | "en" = "ar") {
  return renderWithProviders(
    <>
      <Where />
      <Routes>
        <Route path="/inbox" element={<InboxPage />} />
        <Route path="/inbox/thread/:id" element={<div>one conversation</div>} />
        <Route path="/tasks/new" element={<div>new task page</div>} />
        <Route path="/" element={<div>home page</div>} />
      </Routes>
    </>,
    { route, lang },
  );
}

const listCalls = (calls: { url: string }[]) => calls.filter((call) => call.url.startsWith(URL_LIST)).map((call) => call.url);

describe("InboxPage", () => {
  it("shows a row per conversation the way the classic list does", async () => {
    serve(() => jsonResponse(list()));
    const { container } = open();
    expect(await screen.findByText("Subject of k1")).toBeInTheDocument();
    const first = container.querySelector('[data-thread="k1"]') as HTMLElement;
    expect(within(first).getByText("CL-0001")).toHaveClass("mail__from");
    expect(within(first).getByText("3")).toHaveClass("mail__count");
    expect(within(first).getByText("2026-10-02 5:30 م")).toHaveClass("mono");
    expect(within(first).getByText("Snippet of k1")).toBeInTheDocument();
    expect(first).toHaveClass("is-unread");
    const second = container.querySelector('[data-thread="k2"]') as HTMLElement;
    expect(second).not.toHaveClass("is-unread");
    // A single letter has no count, and a sender nobody knows is said so.
    expect(second.querySelector(".mail__count")).toBeNull();
    expect(within(second).getByText("مرسل غير معروف")).toBeInTheDocument();
  });

  it("tags a row with what happened to it: replied, hidden, its tasks, its files, who took it", async () => {
    serve(() =>
      jsonResponse(
        list({
          threads: [
            row("k1", { answered: true, blocked: true, tasks: ["TSK-00007"], files: 2, claimers: ["Mona"] }),
            row("k2"),
            row("k3", { answered: true }),
          ],
        }),
      ),
    );
    const { container } = open();
    await screen.findByText("Subject of k1");
    const first = container.querySelector('[data-thread="k1"]') as HTMLElement;
    expect(within(first).getByText("اتردّ عليها")).toBeInTheDocument();
    expect(within(first).getByText("محجوبة — سعر")).toBeInTheDocument();
    expect(first).toHaveClass("is-blocked");
    expect(within(first).getByText("TSK-00007")).toHaveClass("badge--ok");
    expect(within(first).getByText("2")).toBeInTheDocument();
    expect(within(first).getByText("Mona")).toBeInTheDocument();
    expect(within(first).queryByText("محدش استلمها")).toBeNull();
    // Nobody took it and nobody answered: it says so. Once somebody answered, it does not.
    expect(within(container.querySelector('[data-thread="k2"]') as HTMLElement).getByText("محدش استلمها")).toBeInTheDocument();
    expect(within(container.querySelector('[data-thread="k3"]') as HTMLElement).queryByText("محدش استلمها")).toBeNull();
  });

  it("says the two numbers over the list, and nothing when they are zero", async () => {
    serve(() => jsonResponse(list()));
    const { container, unmount } = open();
    await screen.findByText("Subject of k1");
    const head = container.querySelector(".page-head") as HTMLElement;
    expect(within(head).getByTitle("محادثات لسه مفتحتهاش")).toHaveTextContent("1");
    expect(within(head).getByTitle("محادثات محدش استلمها")).toHaveTextContent("2");
    unmount();
    serve(() => jsonResponse(list({ unseen: 0, unclaimed: 0 })));
    const again = open();
    await screen.findByText("Subject of k1");
    expect(again.container.querySelector(".page-head [title]")).toBeNull();
  });

  it("opens a conversation by the id of its newest letter, and takes the filters along", async () => {
    serve(() => jsonResponse(list()));
    const user = userEvent.setup();
    const { container } = open("/inbox?state=mine&q=lease");
    await screen.findByText("Subject of k1");
    const link = container.querySelector('[data-thread="k1"] a') as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/inbox/thread/12?state=mine&q=lease");
    await user.click(link);
    expect(await screen.findByText("one conversation")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("/inbox/thread/12?state=mine&q=lease");
  });

  it("asks the server for the filter that was chosen and keeps it in the address", async () => {
    const { calls } = serve(() => jsonResponse(list()));
    const user = userEvent.setup();
    open();
    await screen.findByText("Subject of k1");
    await user.selectOptions(screen.getByRole("combobox", { name: "الفلتر" }), "unclaimed");
    await waitFor(() => expect(listCalls(calls)).toContain("/api/v1/mail/threads/?state=unclaimed"));
    expect(screen.getByTestId("where")).toHaveTextContent("/inbox?state=unclaimed");
  });

  it("searches on submit, with the filter that is on", async () => {
    const { calls } = serve(() => jsonResponse(list()));
    const user = userEvent.setup();
    open("/inbox?state=notask");
    await screen.findByText("Subject of k1");
    await user.type(screen.getByRole("textbox", { name: "بحث" }), "  lease  {Enter}");
    await waitFor(() => expect(listCalls(calls)).toContain("/api/v1/mail/threads/?state=notask&q=lease"));
    expect(screen.getByTestId("where")).toHaveTextContent("/inbox?state=notask&q=lease");
    // No filter and no search is the plain address again.
    await user.selectOptions(screen.getByRole("combobox", { name: "الفلتر" }), "");
    await user.clear(screen.getByRole("textbox", { name: "بحث" }));
    await user.click(screen.getByRole("button", { name: "بحث" }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(/^\/inbox$/));
  });

  it("sends only a filter it knows and a search of a sensible length, whatever the address says", async () => {
    const { calls } = serve(() => jsonResponse(list()));
    open(`/inbox?state=evil&q=${"x".repeat(201)}`);
    await screen.findByText("Subject of k1");
    expect(listCalls(calls)).toEqual(["/api/v1/mail/threads/"]);
  });

  it("keeps the old list on the screen while a new search is on its way", async () => {
    let release: (() => void) | undefined;
    const { calls } = serve((url) => {
      if (!url.searchParams.get("q")) return jsonResponse(list());
      return new Promise<Response>((resolve) => {
        release = () => resolve(jsonResponse(list({ threads: [row("k9", { subject: "Found one" })] })));
      }) as unknown as Response;
    });
    const user = userEvent.setup();
    open();
    await screen.findByText("Subject of k1");
    await user.type(screen.getByRole("textbox", { name: "بحث" }), "found{Enter}");
    await waitFor(() => expect(listCalls(calls)).toContain("/api/v1/mail/threads/?q=found"));
    expect(screen.getByText("Subject of k1")).toBeInTheDocument();
    release?.();
    expect(await screen.findByText("Found one")).toBeInTheDocument();
    expect(screen.queryByText("Subject of k1")).toBeNull();
  });

  it("says so when there is no mail", async () => {
    serve(() => jsonResponse(list({ threads: [], unseen: 0, unclaimed: 0 })));
    open();
    expect(await screen.findByText("مفيش ميلات هنا دلوقتي.")).toBeInTheDocument();
  });

  it("says what state the mailbox is in: not set up, the last fetch failed, or when it last brought mail", async () => {
    serve(() => jsonResponse(list({ mail: { configured: false, last_fetch: null, last_count: 0, last_error: "" } })));
    const first = open();
    expect(await screen.findByText("صندوق البريد مش متظبّط")).toBeInTheDocument();
    first.unmount();

    serve(() => jsonResponse(list({ mail: { configured: true, last_fetch: null, last_count: 0, last_error: "Login refused" } })));
    const second = open();
    expect(await screen.findByText("آخر محاولة جلب فشلت")).toBeInTheDocument();
    expect(screen.getByText("Login refused")).toBeInTheDocument();
    second.unmount();

    serve(() => jsonResponse(list()));
    open();
    expect(await screen.findByText("آخر جلب:")).toBeInTheDocument();
    expect(screen.getByText("2026-10-02 5:00 م")).toBeInTheDocument();
    expect(screen.getByText("4")).toHaveClass("mono");
  });

  it("tells the admin, and nobody else, how many letters the rate rule hides", async () => {
    serve(() => jsonResponse(list({ blocked: 3 })), "admin");
    const first = open();
    expect(await screen.findByText("ميلات محجوبة عن الأوبريشن:")).toBeInTheDocument();
    first.unmount();
    serve(() => jsonResponse(list({ blocked: 0 })), "operation");
    open();
    await screen.findByText("Subject of k1");
    expect(screen.queryByText("ميلات محجوبة عن الأوبريشن:")).toBeNull();
  });

  it("brings the mail in now, and says how many letters came", async () => {
    const mocked = serve(() => jsonResponse(list()), "operation", {
      "/api/mail/fetch/": () => jsonResponse({ ok: true, created: 5, error: "" }),
    });
    const user = userEvent.setup();
    open();
    await screen.findByText("Subject of k1");
    await user.click(screen.getByRole("button", { name: "جيب الميلات دلوقتي" }));
    expect(await screen.findByText("اتجاب 5 ميل جديد.")).toBeInTheDocument();
    const call = mocked.calls.find((one) => one.url === "/api/mail/fetch/");
    expect(call?.init?.method).toBe("POST");
    // The list is asked again: the letters that came are on it.
    await waitFor(() => expect(listCalls(mocked.calls).length).toBeGreaterThan(1));
  });

  it("shows why the fetch failed in the server's words", async () => {
    serve(() => jsonResponse(list()), "operation", {
      "/api/mail/fetch/": () => jsonResponse({ ok: false, created: 0, error: "السيرفر مرفضش الدخول" }, 400),
    });
    const user = userEvent.setup();
    open();
    await screen.findByText("Subject of k1");
    await user.click(screen.getByRole("button", { name: "جيب الميلات دلوقتي" }));
    expect(await screen.findByText("السيرفر مرفضش الدخول")).toBeInTheDocument();
  });

  it("leaves the fetch and the new task to the operation: the Sales have neither", async () => {
    serve(() => jsonResponse(list()), "sales");
    open();
    await screen.findByText("Subject of k1");
    expect(screen.queryByRole("button", { name: "جيب الميلات دلوقتي" })).toBeNull();
    expect(screen.queryByRole("link", { name: /تاسك جديدة/ })).toBeNull();
  });

  it("links the new task button to the form", async () => {
    serve(() => jsonResponse(list()));
    const user = userEvent.setup();
    open();
    await screen.findByText("Subject of k1");
    await user.click(screen.getByRole("link", { name: /تاسك جديدة/ }));
    expect(await screen.findByText("new task page")).toBeInTheDocument();
  });

  it("sends everybody else home without asking the mailbox", async () => {
    for (const role of ["translator", "team_lead", "hr", "accounting", "reviewer"] as Role[]) {
      const mocked = serve(() => jsonResponse(list()), role);
      const { unmount } = open();
      expect(await screen.findByText("home page")).toBeInTheDocument();
      expect(listCalls(mocked.calls), role).toEqual([]);
      unmount();
    }
  });

  it("says it could not load, and says it in English too", async () => {
    serve(() => jsonResponse({ ok: false, error: "boom" }, 500));
    const first = open();
    expect(await screen.findByText("حصلت مشكلة في التحميل.")).toBeInTheDocument();
    first.unmount();
    serve(() => jsonResponse(list()));
    open("/inbox", "en");
    expect(await screen.findByText("Incoming mail")).toBeInTheDocument();
    expect((await screen.findAllByText("Nobody claimed it")).length).toBe(2);
    expect(screen.getAllByText("2026-10-02 5:30 PM").length).toBe(2);
  });
});
