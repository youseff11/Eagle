import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Role, StaffAccount } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { StaffAccountsPage } from "./StaffAccountsPage";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const LIST = "/api/v1/support/accounts/";

const ACCOUNTS: StaffAccount[] = [
  { id: 7, username: "asmaa", name: "Asmaa Hasan", initials: "AH", avatar: null, role: "translator" },
  { id: 9, username: "raghda", name: "Raghda Ali", initials: "RA", avatar: null, role: "team_lead" },
];

function serve(role: Role = "support", password: (body: unknown) => Response = () => jsonResponse({ ok: true })) {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role, is_admin: role === "admin" })),
    // Matched by prefix, first one wins: the list's address is the start of the others.
    "/api/v1/support/accounts/7/enter/": () => jsonResponse({ ok: true }),
    "/api/v1/support/accounts/7/password/": (_url, init) => password(JSON.parse(String(init?.body))),
    [LIST]: () => jsonResponse({ ok: true, accounts: ACCOUNTS }),
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function open() {
  return renderWithProviders(
    <Routes>
      <Route path="/staff-accounts" element={<StaffAccountsPage />} />
      <Route path="/" element={<div>home page</div>} />
    </Routes>,
    { route: "/staff-accounts" },
  );
}

const posts = (mocked: ReturnType<typeof serve>, url: string) => mocked.calls.filter((call) => call.url === url && call.init?.method === "POST");

describe("StaffAccountsPage", () => {
  it("lists the accounts and finds one by name or username", async () => {
    const user = userEvent.setup();
    serve();
    open();
    expect(await screen.findByText("Asmaa Hasan")).toBeInTheDocument();
    expect(screen.getByText("Raghda Ali")).toBeInTheDocument();
    await user.type(screen.getByLabelText("دوّر بالاسم أو اليوزرنيم"), "ragh");
    expect(screen.queryByText("Asmaa Hasan")).toBeNull();
    expect(screen.getByText("Raghda Ali")).toBeInTheDocument();
  });

  it("opens a person's account and starts the app again on it", async () => {
    const user = userEvent.setup();
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const mocked = serve();
    open();
    await screen.findByText("Asmaa Hasan");
    const row = document.querySelector('[data-account="7"]') as HTMLElement;
    await user.click(row.querySelector("button.btn--primary") as HTMLElement);
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/app/"));
    expect(posts(mocked, "/api/v1/support/accounts/7/enter/")).toHaveLength(1);
  });

  it("gives a new password typed twice, and says the server's reason when refused", async () => {
    const user = userEvent.setup();
    let answer = jsonResponse({ ok: false, error: "invalid", errors: { new_password2: ["The two password fields didn't match."] } }, 400);
    const mocked = serve("support", () => answer);
    open();
    await screen.findByText("Asmaa Hasan");
    const row = document.querySelector('[data-account="7"]') as HTMLElement;
    await user.click(row.querySelectorAll("button")[1] as HTMLElement);
    await user.type(await screen.findByLabelText("الباسورد الجديد"), "Brand-new-7731");
    await user.type(screen.getByLabelText("الجديد تاني"), "Brand-new-7732");
    await user.click(screen.getByRole("button", { name: "احفظ الباسورد" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("didn't match");
    answer = jsonResponse({ ok: true });
    await user.click(screen.getByRole("button", { name: "احفظ الباسورد" }));
    await waitFor(() => expect(screen.queryByLabelText("الباسورد الجديد")).toBeNull());
    const sent = posts(mocked, "/api/v1/support/accounts/7/password/").map((call) => JSON.parse(String(call.init?.body)));
    expect(sent.at(-1)).toEqual({ new_password1: "Brand-new-7731", new_password2: "Brand-new-7732" });
  });

  it("sends anybody else home", async () => {
    serve("translator");
    open();
    expect(await screen.findByText("home page")).toBeInTheDocument();
  });
});
