import { screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Role, TeamMember, TeamResponse } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { TeamPage } from "./TeamPage";

afterEach(() => vi.unstubAllGlobals());

const URL = "/api/v1/team/";
const seen = (ar: string, en: string) => ({ ar, en });

function member(id: number, over: Partial<TeamMember> = {}): TeamMember {
  return {
    id,
    name: `Translator ${id}`,
    initials: `T${id}`,
    languages: "EN, AR",
    state: "free",
    seen: seen("دلوقتي", "just now"),
    rating: 4.875,
    tasks: [],
    ...over,
  };
}

function board(over: Partial<TeamResponse["leads"][number]> = {}, extra: TeamResponse["leads"] = []): TeamResponse {
  return {
    ok: true,
    leads: [
      {
        id: 10,
        name: "Mona",
        initials: "MS",
        online: true,
        rating: 5,
        tasks: 4,
        counts: { free: 1, busy: 1, offline: 2 },
        members: [
          member(1, { state: "free" }),
          member(2, { state: "busy", tasks: ["TSK-00001", "TSK-00002"] }),
          member(3, { state: "off", seen: seen("من 3 ساعة", "3h ago") }),
          member(4, { state: "shift", seen: seen("من يوم", "1d ago") }),
        ],
        ...over,
      },
      ...extra,
    ],
  };
}

function serve(body: () => Response, role: Role = "operation") {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role, is_admin: role === "admin" })),
    [URL]: body,
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function open(lang: "ar" | "en" = "ar") {
  return renderWithProviders(
    <Routes>
      <Route path="/team" element={<TeamPage />} />
      <Route path="/tasks/:code" element={<div>one task page</div>} />
      <Route path="/" element={<div>home page</div>} />
    </Routes>,
    { route: "/team", lang },
  );
}

describe("TeamPage", () => {
  it("shows a leader with whether they are online, their rating and their tasks", async () => {
    serve(() => jsonResponse(board()));
    const { container } = open();
    const card = (await screen.findByText("Mona")).closest(".card") as HTMLElement;
    expect(within(card).getByText("نشط دلوقتي")).toBeInTheDocument();
    expect(card.querySelector(".card__head .dot--on")).not.toBeNull();
    expect(within(card).getByText("5.00")).toBeInTheDocument();
    expect(within(card).getByText(/تاسكاته/)).toHaveTextContent("تاسكاته 4");
    expect(container.querySelectorAll("[data-lead]")).toHaveLength(1);
  });

  it("says a leader is offline when they are", async () => {
    serve(() => jsonResponse(board({ online: false })));
    open();
    const card = (await screen.findByText("Mona")).closest(".card") as HTMLElement;
    expect(within(card).getByText("أوفلاين", { selector: ".card__head small" })).toBeInTheDocument();
    expect(card.querySelector(".card__head .dot--off")).not.toBeNull();
  });

  it("counts who is free, busy and offline", async () => {
    serve(() => jsonResponse(board()));
    const { container } = open();
    await screen.findByText("Mona");
    const kpis = Array.from(container.querySelectorAll(".grid--3 .kpi")).map((k) => k.textContent);
    expect(kpis).toEqual(["1فاضيين", "1مشغولين", "2أوفلاين"]);
  });

  it("lists each translator with their languages, their state in words, and their rating", async () => {
    serve(() => jsonResponse(board()));
    const { container } = open();
    await screen.findByText("Translator 1");
    const states = Array.from(container.querySelectorAll("[data-member] .presence")).map((p) => p.getAttribute("data-state"));
    expect(states).toEqual(["free", "busy", "off", "shift"]);
    const free = container.querySelector('[data-member="1"]') as HTMLElement;
    expect(within(free).getByText("EN, AR")).toBeInTheDocument();
    expect(within(free).getByText("فاضي")).toBeInTheDocument();
    expect(within(free).getByText("4.88")).toBeInTheDocument();
    expect(within(free).getByText("T1")).toHaveClass("avatar");
    expect(free.querySelector(".dot--on")).not.toBeNull();
  });

  it("says when somebody was last here only for the two states where it matters", async () => {
    serve(() => jsonResponse(board()));
    const { container } = open();
    await screen.findByText("Translator 1");
    expect(container.querySelector('[data-member="1"] .presence__seen')).toBeNull();
    expect(container.querySelector('[data-member="2"] .presence__seen')).toBeNull();
    expect(container.querySelector('[data-member="3"] .presence__seen')).toHaveTextContent("من 3 ساعة");
    expect(container.querySelector('[data-member="4"] .presence__seen')).toHaveTextContent("من يوم");
    expect(within(container.querySelector('[data-member="4"]') as HTMLElement).getByText("في الشيفت — مش فاتح")).toBeInTheDocument();
  });

  it("links the tasks a person has open, as routes made from the code, and says dash for none", async () => {
    serve(() => jsonResponse(board()));
    const { container } = open();
    await screen.findByText("Translator 2");
    const links = within(container.querySelector('[data-member="2"]') as HTMLElement).getAllByRole("link");
    expect(links.map((l) => l.getAttribute("href"))).toEqual(["/tasks/TSK-00001", "/tasks/TSK-00002"]);
    expect(within(container.querySelector('[data-member="1"]') as HTMLElement).getByText("—")).toBeInTheDocument();
  });

  it("says a leader has nobody when they have nobody, and when there are no leaders", async () => {
    serve(() => jsonResponse(board({ members: [], counts: { free: 0, busy: 0, offline: 0 } })));
    const view = open();
    expect(await screen.findByText("مفيش مترجمين تحت التيم ليدر ده.")).toBeInTheDocument();
    view.unmount();
    vi.unstubAllGlobals();
    serve(() => jsonResponse({ ok: true, leads: [] }));
    open();
    expect(await screen.findByText("مفيش تيم ليدرز مسجلين.")).toBeInTheDocument();
  });

  it("draws the words as text, never as markup", async () => {
    serve(() => jsonResponse(board({ name: "<img src=x onerror=alert(1)>", members: [member(1, { name: "<b>x</b>", languages: "<i>y</i>" })] })));
    const { container } = open();
    expect(await screen.findByText(/<img src=x onerror=alert\(1\)>/)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    // The only bold and italic text are the rating's own.
    for (const el of Array.from(container.querySelectorAll("b, i"))) expect(el.closest(".rating")).not.toBeNull();
  });

  it("speaks English when asked", async () => {
    serve(() => jsonResponse(board()));
    open("en");
    expect(await screen.findByText("Online now")).toBeInTheDocument();
    expect(screen.getByText("Team leaders & their teams")).toBeInTheDocument();
    expect(screen.getByText("Free", { selector: ".presence__state" })).toBeInTheDocument();
    expect(screen.getByText("On shift — not open")).toBeInTheDocument();
    expect(screen.getByText("3h ago")).toBeInTheDocument();
  });

  it("is for the operation and the admin: anybody else is sent home without asking", async () => {
    const mocked = serve(() => jsonResponse(board()), "translator");
    open();
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(mocked.calls.some((c) => c.url === URL)).toBe(false);
  });

  it("answers the admin too", async () => {
    serve(() => jsonResponse(board()), "admin");
    open();
    expect(await screen.findByText("Mona")).toBeInTheDocument();
  });

  it("says it could not load on a server failure, and says it is loading before that", async () => {
    serve(() => new Promise<Response>(() => undefined) as unknown as Response);
    const view = open();
    await waitFor(() => expect(screen.getByText("بيحمّل...")).toBeInTheDocument());
    view.unmount();
    vi.unstubAllGlobals();
    serve(() => jsonResponse({ ok: false, error: "server" }, 500));
    open();
    expect(await screen.findByRole("alert")).toHaveTextContent("حصلت مشكلة في التحميل.");
  });
});
