import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AnnounceResponse, Role } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { SupportAnnouncePage } from "./SupportAnnouncePage";

afterEach(() => vi.unstubAllGlobals());

const URL = "/api/v1/announce/";

function state(over: Partial<AnnounceResponse> = {}): AnnounceResponse {
  return {
    ok: true,
    reach: 12,
    limits: { title: 200, body: 400 },
    recent: [{ id: 1, title: "Restart at 6", body: "Save your work", reached: 11, by: "Sami", at: { ar: "5:00 م", en: "5:00 PM" } }],
    ...over,
  };
}

function serve(role: Role = "support", send: (body: unknown) => Response = () => jsonResponse({ ok: true, reached: 12 })) {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role, is_admin: role === "admin" })),
    [URL]: (_url, init) => (init?.method === "POST" ? send(JSON.parse(String(init.body))) : jsonResponse(state())),
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function open() {
  return renderWithProviders(
    <Routes>
      <Route path="/announce" element={<SupportAnnouncePage />} />
      <Route path="/" element={<div>home page</div>} />
    </Routes>,
    { route: "/announce" },
  );
}

const posts = (mocked: ReturnType<typeof serve>) => mocked.calls.filter((call) => call.url === URL && call.init?.method === "POST");

describe("SupportAnnouncePage", () => {
  it("lists the latest announcements", async () => {
    serve();
    open();
    expect(await screen.findByText("Restart at 6")).toBeInTheDocument();
    expect(screen.getByText("Save your work")).toBeInTheDocument();
  });

  it("draws what is typed as the employees will see it, from the sender, lines and all", async () => {
    const user = userEvent.setup();
    serve();
    open();
    await screen.findByText("Restart at 6");
    const preview = () => document.querySelector("[data-preview]") as HTMLElement;
    expect(within(preview()).getByText("عنوان الإشعار")).toBeInTheDocument();
    expect(within(preview()).getByText("Nour")).toBeInTheDocument();
    await user.type(screen.getByLabelText("العنوان"), "تحديث في النظام");
    await user.type(screen.getByLabelText("التفاصيل (اختياري)"), "1- أول حاجة{Enter}2- تاني حاجة");
    expect(within(preview()).getByText("تحديث في النظام")).toBeInTheDocument();
    expect((preview().querySelector(".notice__body") as HTMLElement).textContent).toBe("1- أول حاجة\n2- تاني حاجة");
    await user.selectOptions(screen.getByLabelText("النوع"), "warning");
    expect(preview().querySelector(".note")).toHaveClass("note--warn");
    // Nothing of it can be pressed: it is to be looked at.
    expect(within(preview()).queryByRole("button")).toBeNull();
    expect(within(preview()).queryByRole("link")).toBeNull();
  });

  it("sends the lines as typed", async () => {
    const user = userEvent.setup();
    const mocked = serve();
    open();
    await screen.findByText("Restart at 6");
    await user.type(screen.getByLabelText("العنوان"), "List");
    await user.type(screen.getByLabelText("التفاصيل (اختياري)"), "one{Enter}two{Enter}{Enter}three");
    await user.click(screen.getByRole("button", { name: "ابعت للكل" }));
    await user.click(await screen.findByRole("button", { name: "ابعت" }));
    await waitFor(() => expect(posts(mocked)).toHaveLength(1));
    expect(JSON.parse(String(posts(mocked)[0]!.init!.body)).body).toBe("one\ntwo\n\nthree");
  });

  it("asks before it sends, says how many it reaches, and sends nothing on a no", async () => {
    const user = userEvent.setup();
    const mocked = serve();
    open();
    await screen.findByText("Restart at 6");
    await user.type(screen.getByLabelText("العنوان"), "Server down");
    await user.click(screen.getByRole("button", { name: "ابعت للكل" }));
    expect(await screen.findByText("تبعت الإشعار للكل؟")).toBeInTheDocument();
    expect(screen.getByText("هيوصل لـ 12 موظف ومينفعش يتسحب.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "إلغاء" }));
    expect(screen.queryByText("تبعت الإشعار للكل؟")).toBeNull();
    expect(posts(mocked)).toHaveLength(0);
  });

  it("sends the words, the kind and the sound once it is said yes to, and empties the form", async () => {
    const user = userEvent.setup();
    const mocked = serve();
    open();
    await screen.findByText("Restart at 6");
    await user.type(screen.getByLabelText("العنوان"), "  Server down ");
    await user.type(screen.getByLabelText("التفاصيل (اختياري)"), "Back in ten minutes");
    await user.selectOptions(screen.getByLabelText("النوع"), "warning");
    await user.click(screen.getByLabelText("رنّة مع الإشعار"));
    await user.click(screen.getByRole("button", { name: "ابعت للكل" }));
    await user.click(await screen.findByRole("button", { name: "ابعت" }));
    await waitFor(() => expect(posts(mocked)).toHaveLength(1));
    expect(JSON.parse(String(posts(mocked)[0]!.init!.body))).toEqual({
      title: "Server down",
      body: "Back in ten minutes",
      level: "warning",
      sound: true,
    });
    await waitFor(() => expect(screen.queryByText("تبعت الإشعار للكل؟")).toBeNull());
    expect(screen.getByLabelText("العنوان")).toHaveValue("");
  });

  it("does not even ask when there is no title", async () => {
    const user = userEvent.setup();
    const mocked = serve();
    open();
    await screen.findByText("Restart at 6");
    await user.click(screen.getByRole("button", { name: "ابعت للكل" }));
    expect(screen.getByRole("alert")).toHaveTextContent("اكتب عنوان للإشعار.");
    expect(screen.queryByText("تبعت الإشعار للكل؟")).toBeNull();
    expect(posts(mocked)).toHaveLength(0);
  });

  it("says why when the server refuses a repeat", async () => {
    const user = userEvent.setup();
    serve("support", () => jsonResponse({ ok: false, error: "repeat" }, 409));
    open();
    await screen.findByText("Restart at 6");
    await user.type(screen.getByLabelText("العنوان"), "Same again");
    await user.click(screen.getByRole("button", { name: "ابعت للكل" }));
    await user.click(await screen.findByRole("button", { name: "ابعت" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("نفس الإشعار اتبعت من أقل من دقيقة.");
    expect(screen.getByLabelText("العنوان")).toHaveValue("Same again");
  });

  it("is for technical support and the admin: anybody else is sent home without asking", async () => {
    const mocked = serve("operation");
    open();
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(mocked.calls.some((call) => call.url === URL)).toBe(false);
  });
});
