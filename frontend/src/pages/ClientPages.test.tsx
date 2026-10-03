import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ClientResponse, ClientRow, ClientsResponse, Role } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { ClientPage } from "./ClientPage";
import { ClientsPage } from "./ClientsPage";

afterEach(() => vi.unstubAllGlobals());

function Where() {
  const location = useLocation();
  return <div data-testid="where">{location.pathname + location.search}</div>;
}

function shell(route: string, lang: "ar" | "en" = "ar") {
  return renderWithProviders(
    <>
      <Where />
      <Routes>
        <Route path="/clients" element={<ClientsPage />} />
        <Route path="/clients/:code" element={<ClientPage />} />
        <Route path="/tasks/:code" element={<div>one task page</div>} />
        <Route path="/" element={<div>home page</div>} />
      </Routes>
    </>,
    { route, lang },
  );
}

const role = (value: Role) => ({ "/api/v1/me/": () => jsonResponse(me({ role: value, is_admin: value === "admin" })) });

// ---------------------------------------------------------------------------------------------------------------------
// The list
// ---------------------------------------------------------------------------------------------------------------------

function row(code: string, over: Partial<ClientRow> = {}): ClientRow {
  return { code, tasks: 3, requirements: 2, ...over };
}

function list(over: Partial<ClientsResponse> = {}): ClientsResponse {
  return { ok: true, q: "", sees_identity: false, clients: [row("CL-0001"), row("CL-0002", { tasks: 0, requirements: 0 })], ...over };
}

function serveList(body: (url: URL) => Response, who: Role = "operation") {
  // The page of one client, for the tests that follow a link (the prefix of the list would answer it otherwise).
  const mocked = mockFetch({ ...role(who), "/api/v1/clients/CL-": () => jsonResponse({ ok: false, error: "not_found" }, 404), "/api/v1/clients/": body });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

const listCalls = (calls: { url: string }[]) => calls.filter((call) => call.url.startsWith("/api/v1/clients/")).map((call) => call.url);

describe("ClientsPage", () => {
  it("shows the codes with their counts, and nothing that names a client, when the server sent no identity", async () => {
    serveList(() => jsonResponse(list()));
    const { container } = shell("/clients");
    expect(await screen.findByText("CL-0001")).toBeInTheDocument();
    const headers = Array.from(container.querySelectorAll("th")).map((th) => th.textContent);
    expect(headers).toEqual(["الكود", "عدد التاسكات", "المتطلبات", ""]);
    const first = container.querySelector('[data-client="CL-0001"]') as HTMLElement;
    expect(Array.from(first.querySelectorAll("td")).slice(0, 3).map((td) => td.textContent)).toEqual(["CL-0001", "3", "2"]);
  });

  it("adds the name, the company and the phone for whoever the server says may know", async () => {
    serveList(
      () => jsonResponse(list({ sees_identity: true, clients: [row("CL-0001", { name: "ACME Ltd", company: "ACME Holdings", phone: "+2010" }), row("CL-0002", { name: "", company: "", phone: "" })] })),
      "admin",
    );
    const { container } = shell("/clients");
    expect(await screen.findByText("ACME Ltd")).toBeInTheDocument();
    expect(Array.from(container.querySelectorAll("th")).map((th) => th.textContent)).toEqual(["الكود", "الاسم", "التليفون", "عدد التاسكات", "المتطلبات", ""]);
    const first = container.querySelector('[data-client="CL-0001"]') as HTMLElement;
    expect(within(first).getByText("ACME Holdings")).toBeInTheDocument();
    expect(within(first).getByText("+2010")).toHaveClass("mono");
    // A client with no name says nothing is there, not that it is empty.
    const second = container.querySelector('[data-client="CL-0002"]') as HTMLElement;
    expect(within(second).getAllByText("—")).toHaveLength(2);
  });

  it("opens a client by its code", async () => {
    serveList(() => jsonResponse(list()));
    const user = userEvent.setup();
    const { container } = shell("/clients");
    await screen.findByText("CL-0001");
    const link = within(container.querySelector('[data-client="CL-0001"]') as HTMLElement).getByRole("link", { name: "افتح" });
    expect(link.getAttribute("href")).toBe("/clients/CL-0001");
    await user.click(link);
    expect(screen.getByTestId("where")).toHaveTextContent("/clients/CL-0001");
  });

  it("searches on submit and keeps the search in the address", async () => {
    const mocked = serveList(() => jsonResponse(list()));
    const user = userEvent.setup();
    shell("/clients");
    await screen.findByText("CL-0001");
    await user.type(screen.getByRole("textbox", { name: "بحث" }), "  CL-0002 {Enter}");
    await waitFor(() => expect(listCalls(mocked.calls)).toContain("/api/v1/clients/?q=CL-0002"));
    expect(screen.getByTestId("where")).toHaveTextContent("/clients?q=CL-0002");
    await user.clear(screen.getByRole("textbox", { name: "بحث" }));
    await user.click(screen.getByRole("button", { name: "بحث" }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(/^\/clients$/));
  });

  it("starts from the search in the address, and does not send one that is too long", async () => {
    const mocked = serveList(() => jsonResponse(list()));
    shell("/clients?q=CL-0002");
    await screen.findByText("CL-0001");
    expect(listCalls(mocked.calls)).toEqual(["/api/v1/clients/?q=CL-0002"]);
    expect(screen.getByRole("textbox", { name: "بحث" })).toHaveValue("CL-0002");
    const long = serveList(() => jsonResponse(list()));
    shell(`/clients?q=${"x".repeat(201)}`);
    await waitFor(() => expect(listCalls(long.calls).length).toBeGreaterThan(0));
    expect(listCalls(long.calls)).toEqual(["/api/v1/clients/"]);
  });

  it("says so when there are no clients", async () => {
    serveList(() => jsonResponse(list({ clients: [] })));
    shell("/clients");
    expect(await screen.findByText("مفيش عملاء.")).toBeInTheDocument();
  });

  it("sends everybody else home without asking", async () => {
    for (const who of ["translator", "team_lead", "hr", "accounting", "reviewer", "sales"] as Role[]) {
      const mocked = serveList(() => jsonResponse(list()), who);
      const { unmount } = shell("/clients");
      expect(await screen.findByText("home page")).toBeInTheDocument();
      expect(listCalls(mocked.calls), who).toEqual([]);
      unmount();
    }
  });

  it("says it could not load, and speaks English too", async () => {
    serveList(() => jsonResponse({ ok: false, error: "boom" }, 500));
    const first = shell("/clients");
    expect(await screen.findByText("حصلت مشكلة في التحميل.")).toBeInTheDocument();
    first.unmount();
    serveList(() => jsonResponse(list()));
    shell("/clients", "en");
    expect(await screen.findByText("Clients", { selector: "h1" })).toBeInTheDocument();
    expect(await screen.findByRole("columnheader", { name: "Tasks" })).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------------------------------------------------
// One client
// ---------------------------------------------------------------------------------------------------------------------

const KIND = { like: { value: "like", ar: "بيحب", en: "Likes" }, dislike: { value: "dislike", ar: "بيكره", en: "Dislikes" }, rule: { value: "rule", ar: "قاعدة", en: "Rule" } };
const STATUS = { value: "in_progress", tone: "work", ar: "شغل جاري", en: "In progress" };

function client(over: Partial<ClientResponse> = {}): ClientResponse {
  return {
    ok: true,
    client: { code: "CL-0001" },
    sees_identity: false,
    may_edit: true,
    activity: null,
    requirements: [
      { id: 2, kind: KIND.dislike, author: "Nour", text: "No abbreviations", at: { ar: "2026-10-02", en: "2026-10-02" } },
      { id: 1, kind: KIND.like, author: "Mona", text: "Likes tables", at: { ar: "2026-10-01", en: "2026-10-01" } },
    ],
    tasks: [
      { code: "TSK-00001", title: "A short title", origin: { value: "whatsapp", icon: "message", ar: "واتساب", en: "WhatsApp" }, status: STATUS },
      { code: "TSK-00002", title: "A title that is much longer than twenty-six characters", origin: null, status: STATUS },
    ],
    ...over,
  };
}

function serveOne(
  body: (url: URL) => Response,
  who: Role = "operation",
  extra: Record<string, (url: URL, init: RequestInit | undefined) => Response | Promise<Response>> = {},
) {
  const mocked = mockFetch({ ...role(who), ...extra, "/api/v1/clients/CL-0001/": body });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

describe("ClientPage", () => {
  it("shows the code, and says the identity is hidden when the server sent none", async () => {
    serveOne(() => jsonResponse(client()));
    shell("/clients/CL-0001");
    expect(await screen.findByText("بيانات العميل مخفية")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "CL-0001" })).toHaveClass("mono");
    expect(screen.queryByText("بيانات العميل")).toBeNull();
  });

  it("lists the requirements with the kind, who wrote them and the day", async () => {
    const { container } = (serveOne(() => jsonResponse(client())), shell("/clients/CL-0001"));
    expect(await screen.findByText("No abbreviations")).toBeInTheDocument();
    const notes = Array.from(container.querySelectorAll(".note")).map((note) => note.textContent);
    expect(notes[0]).toContain("بيكره · Nour · 2026-10-02");
    expect(notes[1]).toContain("بيحب · Mona · 2026-10-01");
    expect(container.querySelectorAll(".note")[0]).toHaveClass("note--high");
  });

  it("says there are no requirements yet", async () => {
    serveOne(() => jsonResponse(client({ requirements: [] })));
    shell("/clients/CL-0001");
    expect(await screen.findByText("مفيش متطلبات مسجلة لحد دلوقتي.")).toBeInTheDocument();
  });

  it("lists the tasks, with a link to each and a long title cut", async () => {
    serveOne(() => jsonResponse(client()));
    const user = userEvent.setup();
    shell("/clients/CL-0001");
    const link = await screen.findByRole("link", { name: "TSK-00001" });
    const cut = screen.getByText(/A title that is much/);
    expect(cut.textContent).toContain("…");
    expect(cut.textContent).not.toContain("characters");
    expect(screen.getByText("واتساب")).toBeInTheDocument();
    await user.click(link);
    expect(await screen.findByText("one task page")).toBeInTheDocument();
  });

  it("says there are no tasks", async () => {
    serveOne(() => jsonResponse(client({ tasks: [] })));
    shell("/clients/CL-0001");
    expect(await screen.findByText("مفيش تاسكات.")).toBeInTheDocument();
  });

  it("draws who the client is, for whoever the server told", async () => {
    serveOne(
      () =>
        jsonResponse(
          client({
            sees_identity: true,
            client: { code: "CL-0001", name: "ACME Ltd", company: "ACME Holdings", phones: ["+2010", "+2011"], emails: ["a@acme.example"], admin_notes: "Pays late" },
            activity: { total: 9, active: 2, delivered: 6, last: { ar: "2026-10-01", en: "2026-10-01" } },
            edit_url: "/panel/clients/CL-0001/edit/",
          }),
        ),
      "admin",
    );
    const { container } = shell("/clients/CL-0001");
    expect(await screen.findByText("Pays late")).toBeInTheDocument();
    expect(container.querySelector(".page-head .badge")).toHaveTextContent("ACME Ltd ACME Holdings");
    expect(screen.getByText("+2011")).toBeInTheDocument();
    expect(screen.getByText("a@acme.example")).toBeInTheDocument();
    const edit = screen.getByRole("link", { name: "تعديل البيانات" });
    expect(edit.getAttribute("href")).toBe("/panel/clients/CL-0001/edit/");
    // The follow-up numbers.
    const card = screen.getByText("متابعة العميل").closest(".card") as HTMLElement;
    expect(Array.from(card.querySelectorAll(".kv strong")).map((one) => one.textContent)).toEqual(["2", "6", "9", "2026-10-01"]);
  });

  it("does not follow an edit address that is not on this site", async () => {
    serveOne(() => jsonResponse(client({ edit_url: "https://evil.example/edit/" })), "admin");
    shell("/clients/CL-0001");
    await screen.findByText("No abbreviations");
    expect(screen.queryByRole("link", { name: "تعديل البيانات" })).toBeNull();
  });

  it("adds a requirement, clears the box, and asks the client again", async () => {
    let added = false;
    const mocked = serveOne(
      () => jsonResponse(client({ requirements: added ? [{ id: 3, kind: KIND.rule, author: "Nour", text: "Formal tone", at: null }] : [] })),
      "operation",
      {
        "/api/v1/clients/CL-0001/requirements/": () => {
          added = true;
          return jsonResponse({ ok: true, requirement: { id: 3 } });
        },
      },
    );
    const user = userEvent.setup();
    shell("/clients/CL-0001");
    const box = await screen.findByRole("textbox", { name: "المتطلب" });
    await user.selectOptions(screen.getByRole("combobox", { name: "النوع" }), "rule");
    await user.type(box, "  Formal tone ");
    await user.click(screen.getByRole("button", { name: "ضيف متطلب" }));
    await waitFor(() => expect(mocked.calls.some((call) => call.url === "/api/v1/clients/CL-0001/requirements/")).toBe(true));
    const call = mocked.calls.find((one) => one.url === "/api/v1/clients/CL-0001/requirements/")!;
    expect(call.init?.method).toBe("POST");
    expect(JSON.parse(String(call.init?.body))).toEqual({ kind: "rule", text: "Formal tone" });
    expect(await screen.findByText("Formal tone")).toBeInTheDocument();
    expect(box).toHaveValue("");
  });

  it("says why a requirement was refused and keeps what was written", async () => {
    serveOne(() => jsonResponse(client()), "operation", {
      "/api/v1/clients/CL-0001/requirements/": () => jsonResponse({ ok: false, error: "bad_requirement", fields: ["text"] }, 400),
    });
    const user = userEvent.setup();
    shell("/clients/CL-0001");
    const box = await screen.findByRole("textbox", { name: "المتطلب" });
    await user.type(box, "Something");
    await user.click(screen.getByRole("button", { name: "ضيف متطلب" }));
    expect(await screen.findByText("اكتب المتطلب.")).toBeInTheDocument();
    expect(box).toHaveValue("Something");
  });

  it("draws no form for somebody who may read but not write", async () => {
    serveOne(() => jsonResponse(client({ may_edit: false })));
    const { container } = shell("/clients/CL-0001");
    await screen.findByText("No abbreviations");
    expect(screen.queryByRole("textbox", { name: "المتطلب" })).toBeNull();
    // And the tasks are not links to a page they may not open.
    expect(screen.queryByRole("link", { name: "TSK-00001" })).toBeNull();
    expect(container.querySelector("li .mono")).toHaveTextContent("TSK-00001");
  });

  it("says a client that is not there is not there", async () => {
    serveOne(() => jsonResponse({ ok: false, error: "not_found" }, 404));
    shell("/clients/CL-0001");
    expect(await screen.findByText("العميل ده مش موجود.")).toBeInTheDocument();
  });

  it("says it could not load when the server failed", async () => {
    serveOne(() => jsonResponse({ ok: false, error: "boom" }, 500));
    shell("/clients/CL-0001");
    expect(await screen.findByText("حصلت مشكلة في التحميل.")).toBeInTheDocument();
  });

  it("goes back to the list", async () => {
    serveOne(() => jsonResponse(client()));
    shell("/clients/CL-0001");
    expect((await screen.findByRole("link", { name: /العملاء/ })).getAttribute("href")).toBe("/clients");
  });

  it("sends everybody else home without asking", async () => {
    for (const who of ["translator", "team_lead", "hr", "accounting", "reviewer", "sales"] as Role[]) {
      const mocked = serveOne(() => jsonResponse(client()), who);
      const { unmount } = shell("/clients/CL-0001");
      expect(await screen.findByText("home page")).toBeInTheDocument();
      expect(mocked.calls.filter((call) => call.url.startsWith("/api/v1/clients/")), who).toEqual([]);
      unmount();
    }
  });

  it("is in English too", async () => {
    serveOne(() => jsonResponse(client()));
    shell("/clients/CL-0001", "en");
    expect(await screen.findByText("Client identity hidden")).toBeInTheDocument();
    expect(screen.getByText("Requirements & notes")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add requirement" })).toBeInTheDocument();
  });
});
