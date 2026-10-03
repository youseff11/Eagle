import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AdminClientForm, AdminClients, ClientDeletePlan, FormField, Role } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { AdminClientFormPage } from "./AdminClientFormPage";
import { AdminClientsPage } from "./AdminClientsPage";

afterEach(() => vi.unstubAllGlobals());

const row = (id: number, code: string, over: Partial<AdminClients["clients"][number]> = {}): AdminClients["clients"][number] => ({
  id,
  code,
  name: `Name ${code}`,
  company: `Company ${code}`,
  phone: `+2010000000${id}`,
  more_phones: 0,
  email: `c${id}@example.com`,
  more_emails: 0,
  active: true,
  ...over,
});

function list(over: Partial<AdminClients> = {}): AdminClients {
  return {
    ok: true,
    q: "",
    show: "",
    shown: 3,
    all_count: 3,
    robots_count: 1,
    clients: [row(1, "CL-0001", { more_phones: 2, more_emails: 1 }), row(2, "CL-0002", { name: "", company: "", active: false }), row(3, "CL-0003")],
    ...over,
  };
}

function plan(over: Partial<ClientDeletePlan> = {}): ClientDeletePlan {
  return {
    ok: true,
    deletable: [{ id: 2, code: "CL-0002", name: "Plain Buyer", contact: "p@example.com", letters: 4, files: 2, replies: 1, rooms: 0, blocked: "" }],
    blocked: [{ id: 1, code: "CL-0001", name: "Busy", contact: "", letters: 0, files: 0, replies: 0, rooms: 0, blocked: "عليه تاسكات." }],
    ...over,
  };
}

function field(name: string, label: string, over: Partial<FormField> = {}): FormField {
  return { name, label, kind: "text", required: false, help: "", disabled: false, ltr: false, value: "", ...over };
}

function clientForm(code = "CL-0001"): AdminClientForm {
  return {
    ok: true,
    code,
    form: [
      field("name", "Name", { value: code ? "Acme" : "" }),
      field("phone", "Main WhatsApp number", { ltr: true, value: code ? "+201001234567" : "" }),
      field("extra_phones", "Other numbers", { kind: "textarea", ltr: true, help: "One number per line." }),
      field("is_active", "Active", { kind: "checkbox", value: true }),
    ],
  };
}

type Handler = (url: URL, init: RequestInit | undefined) => Response | Promise<Response>;

function serve(who: Role, over: Record<string, Handler> = {}) {
  const posts: { url: string; body: unknown }[] = [];
  const record = (url: URL, init: RequestInit | undefined, answer: unknown, status = 200) => {
    posts.push({ url: url.pathname, body: init?.body ? JSON.parse(String(init.body)) : null });
    return jsonResponse(answer, status);
  };
  const defaults: Record<string, Handler> = {
    "/api/v1/me/": () => jsonResponse(me({ role: who, is_admin: who === "admin" })),
    "/api/v1/admin/clients/delete-plan/": (url, init) => record(url, init, plan()),
    "/api/v1/admin/clients/delete/": (url, init) => record(url, init, { ok: true, deleted: ["CL-0002"], blocked: [], files_removed: 2 }),
    "/api/v1/admin/clients/create/": (url, init) => record(url, init, { ok: true, code: "CL-0044" }),
    "/api/v1/admin/clients/new/": () => jsonResponse(clientForm("")),
    "/api/v1/admin/clients/CL-0001/save/": (url, init) => record(url, init, { ok: true, code: "CL-0001" }),
    "/api/v1/admin/clients/CL-0001/": () => jsonResponse(clientForm()),
    "/api/v1/admin/clients/": (url) => jsonResponse(list({ q: url.searchParams.get("q") ?? "", show: url.searchParams.get("show") === "robots" ? "robots" : "" })),
  };
  const routes = { ...over };
  for (const [prefix, answer] of Object.entries(defaults)) if (!(prefix in routes)) routes[prefix] = answer;
  const mocked = mockFetch(routes);
  vi.stubGlobal("fetch", mocked.fn);
  return { ...mocked, posts };
}

function Where() {
  const where = useLocation();
  return <div data-testid="where">{where.pathname + where.search}</div>;
}

function open(route: string) {
  return renderWithProviders(
    <>
      <Routes>
        <Route path="/admin/clients" element={<AdminClientsPage />} />
        <Route path="/admin/clients/new" element={<AdminClientFormPage />} />
        <Route path="/admin/clients/:code/edit" element={<AdminClientFormPage />} />
        <Route path="/clients/:code" element={<div>client codes page</div>} />
        <Route path="/" element={<div>home page</div>} />
      </Routes>
      <Where />
    </>,
    { route },
  );
}

const asked = (served: ReturnType<typeof serve>) =>
  served.calls.filter((call) => call.url.startsWith("/api/v1/admin/clients/") && call.init?.method !== "POST").map((call) => call.url);

describe("AdminClientsPage: the list", () => {
  it("shows each client with the real details, how many more numbers and addresses there are, and whether it is on", async () => {
    serve("admin");
    const { container } = open("/admin/clients");
    await screen.findByText("CL-0001");
    const first = container.querySelector('[data-client="CL-0001"]') as HTMLElement;
    expect(within(first).getByText("Name CL-0001")).toBeInTheDocument();
    expect(within(first).getByText("Company CL-0001")).toBeInTheDocument();
    expect(within(first).getByText("+2")).toHaveClass("chip");
    expect(within(first).getByText("+1")).toHaveClass("chip");
    expect(within(first).getByTitle("نشط")).toHaveClass("dot--on");
    const second = container.querySelector('[data-client="CL-0002"]') as HTMLElement;
    expect(within(second).getByTitle("موقوف")).toHaveClass("dot--off");
    expect(within(second).getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });

  it("opens the client's codes page and the identity form from the row", async () => {
    serve("admin");
    const { container } = open("/admin/clients");
    await screen.findByText("CL-0001");
    const first = container.querySelector('[data-client="CL-0001"]') as HTMLElement;
    expect(within(first).getByRole("link", { name: "ملف" })).toHaveAttribute("href", "/clients/CL-0001");
    expect(within(first).getByRole("link", { name: "تعديل" })).toHaveAttribute("href", "/admin/clients/CL-0001/edit");
    expect(screen.getByRole("link", { name: /عميل جديد/ })).toHaveAttribute("href", "/admin/clients/new");
  });

  it("counts the two tabs and says how many of how many are shown", async () => {
    serve("admin", { "/api/v1/admin/clients/": () => jsonResponse(list({ shown: 450, all_count: 450, robots_count: 7 })) });
    const { container } = open("/admin/clients");
    await screen.findByText("CL-0001");
    const tabs = container.querySelectorAll(".tab");
    expect(tabs[0]).toHaveTextContent("الكل 450");
    expect(tabs[0]).toHaveClass("is-active");
    expect(tabs[1]).toHaveTextContent("ميلات وهمية (noreply) 7");
    expect(container.querySelector(".tabs .muted")).toHaveTextContent("بيظهر هنا 3 من 450");
  });

  it("sends the search into the address and asks the server for it", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    open("/admin/clients");
    await screen.findByText("CL-0001");
    await user.type(screen.getByRole("searchbox", { name: "بحث" }), "acme{Enter}");
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/admin/clients?q=acme"));
    await waitFor(() => expect(asked(served)).toContain("/api/v1/admin/clients/?q=acme"));
  });

  it("does not ask on every key - only when the search is sent", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    open("/admin/clients");
    await screen.findByText("CL-0001");
    await user.type(screen.getByRole("searchbox", { name: "بحث" }), "acme");
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(asked(served)).toEqual(["/api/v1/admin/clients/"]);
  });

  it("moves to the robots tab keeping the search, and back", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    open("/admin/clients?q=acme");
    await screen.findByText("CL-0001");
    await user.click(screen.getByRole("link", { name: /ميلات وهمية/ }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/admin/clients?q=acme&show=robots"));
    await waitFor(() => expect(asked(served)).toContain("/api/v1/admin/clients/?q=acme&show=robots"));
    expect(await screen.findByText(/دول عناوين روبوتات/)).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: /الكل/ }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/admin/clients?q=acme"));
  });

  it("does not ask for the list again when the window is focused", async () => {
    const served = serve("admin");
    open("/admin/clients");
    await screen.findByText("CL-0001");
    window.dispatchEvent(new Event("focus"));
    document.dispatchEvent(new Event("visibilitychange"));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(asked(served)).toEqual(["/api/v1/admin/clients/"]);
  });

  it("sends anybody who is not the admin home and asks the server for nothing", async () => {
    const served = serve("sales");
    open("/admin/clients");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/admin/"))).toBe(false);
  });

  it("says so when the list cannot be read", async () => {
    serve("admin", { "/api/v1/admin/clients/": () => jsonResponse({ ok: false, error: "server" }, 500) });
    open("/admin/clients");
    expect(await screen.findByRole("alert")).toHaveTextContent("حصلت مشكلة في التحميل.");
  });

  it("says when there are no clients", async () => {
    serve("admin", { "/api/v1/admin/clients/": () => jsonResponse(list({ clients: [], shown: 0, all_count: 0 })) });
    open("/admin/clients");
    expect(await screen.findByText("مفيش عملاء.")).toBeInTheDocument();
  });
});

describe("AdminClientsPage: deleting", () => {
  async function tick(...codes: string[]) {
    open("/admin/clients");
    const user = userEvent.setup();
    for (const code of codes) await user.click(await screen.findByRole("checkbox", { name: code }));
    return user;
  }

  it("cannot delete with nothing ticked", async () => {
    serve("admin");
    open("/admin/clients");
    await screen.findByText("CL-0001");
    expect(screen.getByRole("button", { name: /امسح المحدّد/ })).toBeDisabled();
  });

  it("counts what is ticked, and the box in the header ticks everything shown and clears it", async () => {
    serve("admin");
    const user = userEvent.setup();
    const { container } = open("/admin/clients");
    await screen.findByText("CL-0001");
    await user.click(screen.getByRole("checkbox", { name: "حدّد الكل" }));
    expect(container.querySelector("[data-selected-count]")).toHaveTextContent("3");
    await user.click(screen.getByRole("checkbox", { name: "حدّد الكل" }));
    expect(container.querySelector("[data-selected-count]")).toHaveTextContent("0");
  });

  it("asks what would go first - and deletes nothing yet", async () => {
    const served = serve("admin");
    const user = await tick("CL-0001", "CL-0002");
    await user.click(screen.getByRole("button", { name: /امسح المحدّد/ }));
    const dialog = await screen.findByRole("dialog");
    const asking = served.posts.find((post) => post.url === "/api/v1/admin/clients/delete-plan/")!;
    expect(asking.body).toEqual({ ids: [1, 2] });
    expect(served.posts.some((post) => post.url === "/api/v1/admin/clients/delete/")).toBe(false);
    const goes = dialog.querySelector('[data-plan-row="CL-0002"]') as HTMLElement;
    expect(within(goes).getByText("Plain Buyer")).toBeInTheDocument();
    expect(within(goes).getByText("4")).toBeInTheDocument();
    const blocked = dialog.querySelector('[data-plan="blocked"]') as HTMLElement;
    expect(within(blocked).getByText("CL-0001")).toBeInTheDocument();
    expect(within(blocked).getByText("عليه تاسكات.")).toBeInTheDocument();
  });

  it("keeps the delete button off until the box that says it is for good is ticked", async () => {
    const served = serve("admin");
    const user = await tick("CL-0002");
    await user.click(screen.getByRole("button", { name: /امسح المحدّد/ }));
    const dialog = await screen.findByRole("dialog");
    const button = within(dialog).getByRole("button", { name: /امسح العملاء دول/ });
    expect(button).toBeDisabled();
    await user.click(button);
    expect(served.posts.some((post) => post.url === "/api/v1/admin/clients/delete/")).toBe(false);
    await user.click(within(dialog).getByRole("checkbox"));
    expect(button).toBeEnabled();
  });

  it("deletes only the ones that can go, with the explicit yes, then reads the list again", async () => {
    const served = serve("admin");
    const user = await tick("CL-0001", "CL-0002");
    await user.click(screen.getByRole("button", { name: /امسح المحدّد/ }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("checkbox"));
    await user.click(within(dialog).getByRole("button", { name: /امسح العملاء دول/ }));
    await waitFor(() => expect(served.posts.some((post) => post.url === "/api/v1/admin/clients/delete/")).toBe(true));
    expect(served.posts.find((post) => post.url === "/api/v1/admin/clients/delete/")!.body).toEqual({ ids: [2], confirm: true });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(asked(served).length).toBe(2));
  });

  it("shows the server's reason in the box when it refuses, and leaves the box open", async () => {
    serve("admin", {
      "/api/v1/admin/clients/delete/": () => jsonResponse({ ok: false, error: "refused", message: "فيه تاسك لسه ماسك واحد من العملاء دول. محدش اتمسح.", blocked: [] }, 409),
    });
    const user = await tick("CL-0002");
    await user.click(screen.getByRole("button", { name: /امسح المحدّد/ }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("checkbox"));
    await user.click(within(dialog).getByRole("button", { name: /امسح العملاء دول/ }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("فيه تاسك لسه ماسك واحد من العملاء دول");
  });

  it("goes back without deleting", async () => {
    const served = serve("admin");
    const user = await tick("CL-0002");
    await user.click(screen.getByRole("button", { name: /امسح المحدّد/ }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "رجوع" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(served.posts.some((post) => post.url === "/api/v1/admin/clients/delete/")).toBe(false);
  });

  it("offers no delete button at all when nothing chosen can go", async () => {
    serve("admin", { "/api/v1/admin/clients/delete-plan/": () => jsonResponse(plan({ deletable: [] })) });
    const user = await tick("CL-0001");
    await user.click(screen.getByRole("button", { name: /امسح المحدّد/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByRole("button", { name: /امسح العملاء دول/ })).toBeNull();
    expect(within(dialog).getByText("مفيش عميل من اللي اخترتهم ينفع يتمسح.")).toBeInTheDocument();
  });

  it("says so when the plan cannot be worked out, and opens nothing", async () => {
    serve("admin", { "/api/v1/admin/clients/delete-plan/": () => jsonResponse({ ok: false, error: "server" }, 500) });
    const user = await tick("CL-0002");
    await user.click(screen.getByRole("button", { name: /امسح المحدّد/ }));
    expect(await screen.findByText("حصلت مشكلة، ماتعرفش اللي هيتمسح.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("clears the ticks when a new search is sent", async () => {
    serve("admin");
    const user = await tick("CL-0002");
    await user.type(screen.getByRole("searchbox", { name: "بحث" }), "x{Enter}");
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "CL-0002" })).not.toBeChecked());
  });
});

describe("AdminClientFormPage", () => {
  it("draws the identity form with the client's values", async () => {
    serve("admin");
    open("/admin/clients/CL-0001/edit");
    expect(await screen.findByLabelText("Name")).toHaveValue("Acme");
    expect(screen.getByLabelText("Main WhatsApp number")).toHaveAttribute("dir", "ltr");
    expect(screen.getByLabelText("Other numbers").tagName).toBe("TEXTAREA");
    expect(screen.getByText("One number per line.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("CL-0001");
  });

  it("saves only what was touched and stays on the page", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    open("/admin/clients/CL-0001/edit");
    const save = await screen.findByRole("button", { name: "حفظ" });
    expect(save).toBeDisabled();
    await user.type(screen.getByLabelText("Other numbers"), "+201555000111");
    await user.click(save);
    await waitFor(() => expect(served.posts.some((post) => post.url === "/api/v1/admin/clients/CL-0001/save/")).toBe(true));
    expect(served.posts.find((post) => post.url === "/api/v1/admin/clients/CL-0001/save/")!.body).toEqual({ values: { extra_phones: "+201555000111" } });
    expect(screen.getByTestId("where")).toHaveTextContent("/admin/clients/CL-0001/edit");
  });

  it("shows the form's refusal beside the field - a number that belongs to another client", async () => {
    serve("admin", {
      "/api/v1/admin/clients/CL-0001/save/": () => jsonResponse({ ok: false, error: "invalid", errors: { phone: ["+201009998888 متسجل بالفعل للعميل CL-0002."] } }, 400),
    });
    const user = userEvent.setup();
    open("/admin/clients/CL-0001/edit");
    await user.clear(await screen.findByLabelText("Main WhatsApp number"));
    await user.type(screen.getByLabelText("Main WhatsApp number"), "+201009998888");
    await user.click(screen.getByRole("button", { name: "حفظ" }));
    expect(await screen.findByText(/متسجل بالفعل للعميل CL-0002/)).toBeInTheDocument();
    expect(screen.getByLabelText("Main WhatsApp number")).toHaveValue("+201009998888");
  });

  it("makes a new client and opens their codes page", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    open("/admin/clients/new");
    await user.type(await screen.findByLabelText("Name"), "Fresh Co");
    await user.click(screen.getByRole("button", { name: "حفظ" }));
    await waitFor(() => expect(served.posts.some((post) => post.url === "/api/v1/admin/clients/create/")).toBe(true));
    expect(served.posts.find((post) => post.url === "/api/v1/admin/clients/create/")!.body).toEqual({ values: { name: "Fresh Co" } });
    expect(await screen.findByText("client codes page")).toBeInTheDocument();
  });

  it("says so when the client cannot be read", async () => {
    serve("admin", { "/api/v1/admin/clients/CL-0001/": () => jsonResponse({ ok: false, error: "not_found" }, 404) });
    open("/admin/clients/CL-0001/edit");
    expect(await screen.findByRole("alert")).toHaveTextContent("حصلت مشكلة في التحميل.");
  });

  it("sends anybody who is not the admin home and asks the server for nothing", async () => {
    const served = serve("operation");
    open("/admin/clients/CL-0001/edit");
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/admin/"))).toBe(false);
  });
});
