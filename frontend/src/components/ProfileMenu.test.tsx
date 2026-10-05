import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, me, mockFetch, renderWithProviders, type Routes as FetchRoutes } from "../test/helpers";
import { Avatar } from "./Avatar";
import { Shell } from "./Shell";

// The cutting is the browser's (a canvas): here a picked file becomes a small known one, or is not a picture.
const cut = vi.hoisted(() => ({ result: null as File | Error | null }));
vi.mock("../lib/avatarImage", async (original) => ({
  ...(await original<typeof import("../lib/avatarImage")>()),
  squareAvatar: async () => {
    if (cut.result instanceof Error) throw cut.result;
    return cut.result ?? new File(["square"], "avatar.jpg", { type: "image/jpeg" });
  },
}));

afterEach(() => {
  vi.unstubAllGlobals();
  cut.result = null;
  document.documentElement.removeAttribute("dir");
  document.documentElement.removeAttribute("data-theme");
});

const STORED = "/files/avatars/2026/10/0123456789abcdef.jpg";

/** The whole frame, with a server that remembers the picture: what `/me/` says follows what the two doors did. */
function renderFrame(start: string | null = null, extra: FetchRoutes = {}) {
  let avatar = start;
  const mocked = mockFetch({
    "/api/prefs/": () => jsonResponse({ ok: true }),
    "/api/v1/me/avatar/remove/": () => {
      avatar = null;
      return jsonResponse({ ok: true, avatar: null });
    },
    "/api/v1/me/avatar/": () => {
      avatar = STORED;
      return jsonResponse({ ok: true, avatar });
    },
    // Before "/api/v1/me/", which every address under it would otherwise match.
    "/api/v1/me/password/": () => jsonResponse({ ok: true }),
    "/api/v1/me/": () => jsonResponse(me({ role: "translator", short_name: "Mona", name: "Mona Salem", initials: "MS", avatar })),
    ...extra,
  });
  vi.stubGlobal("fetch", mocked.fn);
  const view = renderWithProviders(
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<div>home page</div>} />
      </Route>
    </Routes>,
  );
  return { ...view, calls: mocked.calls };
}

const chip = () => screen.getByTitle("Mona");
const posts = (calls: { url: string; init?: RequestInit }[], path: string) =>
  calls.filter((call) => call.url === path && call.init?.method === "POST");

describe("the profile picture, from the person's own chip in the top bar", () => {
  it("shows the initials until there is a picture, and nothing is open until the chip is pressed", async () => {
    renderFrame();
    expect(await screen.findByText("MS")).toBeInTheDocument();
    expect(chip().querySelector("img")).toBeNull();
    expect(screen.queryByRole("dialog", { name: "البروفايل" })).toBeNull();
  });

  it("opens the panel with one thing to do when there is no picture: put one there", async () => {
    renderFrame();
    await screen.findByText("MS");
    await userEvent.click(chip());
    const panel = screen.getByRole("dialog", { name: "البروفايل" });
    expect(within(panel).getByRole("button", { name: "ارفع صورة" })).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "احذف الصورة" })).toBeNull();
    expect(chip()).toHaveAttribute("aria-expanded", "true");
  });

  it("draws the picture in the bar, and offers to change it or to take it off", async () => {
    renderFrame(STORED);
    await waitFor(() => expect(chip().querySelector("img")).not.toBeNull());
    expect(chip().querySelector("img")).toHaveAttribute("src", STORED);
    expect(screen.queryByText("MS")).toBeNull();
    await userEvent.click(chip());
    const panel = screen.getByRole("dialog", { name: "البروفايل" });
    expect(within(panel).getByRole("button", { name: "غيّر الصورة" })).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "احذف الصورة" })).toBeInTheDocument();
  });

  it("sends the cut square as the file of a multipart request, and the picture appears at once", async () => {
    const view = renderFrame();
    await screen.findByText("MS");
    await userEvent.click(chip());
    cut.result = new File(["the square"], "avatar.jpg", { type: "image/jpeg" });
    await userEvent.upload(view.getByTestId("avatar-file"), new File(["a big photo"], "holiday.heic", { type: "image/heic" }), {
      applyAccept: false,
    });

    await waitFor(() => expect(posts(view.calls, "/api/v1/me/avatar/")).toHaveLength(1));
    const body = posts(view.calls, "/api/v1/me/avatar/")[0]!.init!.body as FormData;
    expect(body).toBeInstanceOf(FormData);
    const sent = body.get("file") as File;
    expect(sent.name).toBe("avatar.jpg");
    expect(await sent.text()).toBe("the square");
    // The token goes with it, and the browser writes the content type (the boundary) itself.
    const headers = posts(view.calls, "/api/v1/me/avatar/")[0]!.init!.headers as Record<string, string>;
    expect(headers).toHaveProperty("X-CSRFToken");
    expect(headers).not.toHaveProperty("Content-Type");

    await waitFor(() => expect(chip().querySelector("img")).toHaveAttribute("src", STORED));
    expect(screen.getByRole("button", { name: "احذف الصورة" })).toBeInTheDocument();
  });

  it("takes the picture off with one press, and the initials come back", async () => {
    const view = renderFrame(STORED);
    await waitFor(() => expect(chip().querySelector("img")).not.toBeNull());
    await userEvent.click(chip());
    await userEvent.click(screen.getByRole("button", { name: "احذف الصورة" }));

    await waitFor(() => expect(posts(view.calls, "/api/v1/me/avatar/remove/")).toHaveLength(1));
    await waitFor(() => expect(chip().querySelector("img")).toBeNull());
    expect(within(chip()).getByText("MS")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "احذف الصورة" })).toBeNull();
    expect(screen.getByRole("button", { name: "ارفع صورة" })).toBeInTheDocument();
  });

  it("says so, and sends nothing, when the file is not a picture the browser can read", async () => {
    const { NotAPicture } = await import("../lib/avatarImage");
    const view = renderFrame();
    await screen.findByText("MS");
    await userEvent.click(chip());
    cut.result = new NotAPicture();
    await userEvent.upload(view.getByTestId("avatar-file"), new File(["%PDF"], "cv.pdf", { type: "application/pdf" }), { applyAccept: false });

    expect(await screen.findByRole("alert")).toHaveTextContent("الملف ده مش صورة");
    expect(posts(view.calls, "/api/v1/me/avatar/")).toHaveLength(0);
    expect(chip().querySelector("img")).toBeNull();
  });

  it("says so when the server refuses the file, and the picture there stays as it was", async () => {
    const view = renderFrame(STORED, { "/api/v1/me/avatar/": () => jsonResponse({ ok: false, error: "bad_file" }, 400) });
    await waitFor(() => expect(chip().querySelector("img")).not.toBeNull());
    await userEvent.click(chip());
    await userEvent.upload(view.getByTestId("avatar-file"), new File(["x"], "x.png", { type: "image/png" }), { applyAccept: false });

    expect(await screen.findByRole("alert")).toHaveTextContent("الملف ده مش صورة");
    expect(chip().querySelector("img")).toHaveAttribute("src", STORED);
  });

  it("says that the picture was not saved when the server fails", async () => {
    const view = renderFrame(null, { "/api/v1/me/avatar/": () => jsonResponse({ ok: false, error: "server" }, 500) });
    await screen.findByText("MS");
    await userEvent.click(chip());
    await userEvent.upload(view.getByTestId("avatar-file"), new File(["x"], "x.png", { type: "image/png" }), { applyAccept: false });
    expect(await screen.findByRole("alert")).toHaveTextContent("الصورة ماتحفظتش");
  });

  it("closes on Escape (the focus goes back to the chip) and on a press anywhere else, not on a press inside", async () => {
    renderFrame();
    await screen.findByText("MS");
    await userEvent.click(chip());
    const panel = () => screen.queryByRole("dialog", { name: "البروفايل" });
    expect(panel()).not.toBeNull();

    await userEvent.click(within(panel()!).getByText("صورة البروفايل", { selector: ".profile__title" }));
    expect(panel()).not.toBeNull();

    await userEvent.keyboard("{Escape}");
    expect(panel()).toBeNull();
    expect(chip()).toHaveFocus();

    await userEvent.click(chip());
    expect(panel()).not.toBeNull();
    fireEvent.mouseDown(screen.getByText("home page"));
    expect(panel()).toBeNull();

    // And the chip itself shuts it again.
    await userEvent.click(chip());
    await userEvent.click(chip());
    expect(panel()).toBeNull();
  });

  it("speaks English when the page does", async () => {
    const mocked = mockFetch({
      "/api/prefs/": () => jsonResponse({ ok: true }),
      "/api/v1/me/": () => jsonResponse(me({ short_name: "Mona", avatar: STORED })),
    });
    vi.stubGlobal("fetch", mocked.fn);
    renderWithProviders(
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<div>home page</div>} />
        </Route>
      </Routes>,
      { lang: "en" },
    );
    await userEvent.click(await screen.findByTitle("Mona"));
    const panel = screen.getByRole("dialog", { name: "Profile" });
    expect(within(panel).getByRole("button", { name: "Change picture" })).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Remove picture" })).toBeInTheDocument();
  });
});

const PASSWORD = "/api/v1/me/password/";
const sent = (calls: { url: string; init?: RequestInit }[]) => posts(calls, PASSWORD).map((call) => JSON.parse(String(call.init?.body)));

async function openPassword() {
  await screen.findByText("MS");
  await userEvent.click(chip());
  await userEvent.click(within(screen.getByRole("dialog", { name: "البروفايل" })).getByRole("button", { name: "غيّر كلمة السر" }));
}

async function fillPassword(old = "old-one-11", fresh = "Quiet-harbour-77", again = fresh) {
  await userEvent.type(screen.getByLabelText("كلمة السر الحالية"), old);
  await userEvent.type(screen.getByLabelText("كلمة السر الجديدة"), fresh);
  await userEvent.type(screen.getByLabelText("الجديدة تاني"), again);
}

const SAVE = { name: "احفظ كلمة السر" };

describe("a person's own password, from the menu", () => {
  it("is closed until it is asked for, and then draws three password boxes the browser can fill in", async () => {
    renderFrame();
    await screen.findByText("MS");
    await userEvent.click(chip());
    expect(screen.queryByLabelText("كلمة السر الحالية")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "غيّر كلمة السر" }));
    expect(screen.getByLabelText("كلمة السر الحالية")).toHaveAttribute("type", "password");
    expect(screen.getByLabelText("كلمة السر الحالية")).toHaveAttribute("autocomplete", "current-password");
    expect(screen.getByLabelText("كلمة السر الجديدة")).toHaveAttribute("autocomplete", "new-password");
    expect(screen.getByLabelText("الجديدة تاني")).toHaveAttribute("type", "password");
  });

  it("keeps Save off until all three boxes have something in them", async () => {
    renderFrame();
    await openPassword();
    const save = screen.getByRole("button", SAVE);
    expect(save).toBeDisabled();
    await userEvent.type(screen.getByLabelText("كلمة السر الحالية"), "x");
    await userEvent.type(screen.getByLabelText("كلمة السر الجديدة"), "y");
    expect(save).toBeDisabled();
    await userEvent.type(screen.getByLabelText("الجديدة تاني"), "y");
    expect(save).toBeEnabled();
  });

  it("sends the three boxes, says it is done, and closes with the boxes empty", async () => {
    const view = renderFrame();
    await openPassword();
    await fillPassword();
    await userEvent.click(screen.getByRole("button", SAVE));
    await waitFor(() => expect(sent(view.calls)).toHaveLength(1));
    expect(sent(view.calls)[0]).toEqual({ old_password: "old-one-11", new_password1: "Quiet-harbour-77", new_password2: "Quiet-harbour-77" });
    expect(await screen.findByText("كلمة السر اتغيّرت")).toBeInTheDocument();
    expect(screen.queryByLabelText("كلمة السر الحالية")).toBeNull();
    // Opened again, nothing of it is left in the boxes.
    await userEvent.click(screen.getByRole("button", { name: "غيّر كلمة السر" }));
    expect(screen.getByLabelText("كلمة السر الحالية")).toHaveValue("");
    expect(screen.getByLabelText("كلمة السر الجديدة")).toHaveValue("");
  });

  it("says the current password is wrong, and keeps what was typed", async () => {
    renderFrame(null, { [PASSWORD]: () => jsonResponse({ ok: false, error: "wrong_password" }, 400) });
    await openPassword();
    await fillPassword();
    await userEvent.click(screen.getByRole("button", SAVE));
    expect(await screen.findByRole("alert")).toHaveTextContent("كلمة السر الحالية غلط.");
    expect(screen.getByLabelText("كلمة السر الجديدة")).toHaveValue("Quiet-harbour-77");
  });

  it("says the door is shut after too many wrong tries", async () => {
    renderFrame(null, { [PASSWORD]: () => jsonResponse({ ok: false, error: "too_many_attempts" }, 429) });
    await openPassword();
    await fillPassword();
    await userEvent.click(screen.getByRole("button", SAVE));
    expect(await screen.findByRole("alert")).toHaveTextContent("محاولات غلط كتير. الباب اتقفل 15 دقيقة واتسجّل خروجك.");
  });

  it("shows the server's own reasons for a new password it refuses", async () => {
    renderFrame(null, {
      [PASSWORD]: () => jsonResponse({ ok: false, error: "invalid", errors: { new_password2: ["The two password fields did not match."] } }, 400),
    });
    await openPassword();
    await fillPassword("old-one-11", "Quiet-harbour-77", "Quiet-harbour-78");
    await userEvent.click(screen.getByRole("button", SAVE));
    expect(await screen.findByRole("alert")).toHaveTextContent("The two password fields did not match.");
    expect(screen.getByLabelText("كلمة السر الجديدة")).toBeInTheDocument();
  });

  it("says so when it fails for a reason that is not the password's", async () => {
    renderFrame(null, { [PASSWORD]: () => jsonResponse({ ok: false, error: "server" }, 500) });
    await openPassword();
    await fillPassword();
    await userEvent.click(screen.getByRole("button", SAVE));
    expect(await screen.findByRole("alert")).toHaveTextContent("كلمة السر ماتغيّرتش. جرّب تاني.");
  });

  it("is dropped by Cancel, with the boxes emptied and nothing sent", async () => {
    const view = renderFrame();
    await openPassword();
    await fillPassword();
    await userEvent.click(screen.getByRole("button", { name: "إلغاء" }));
    expect(screen.queryByLabelText("كلمة السر الحالية")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "غيّر كلمة السر" }));
    expect(screen.getByLabelText("كلمة السر الحالية")).toHaveValue("");
    expect(sent(view.calls)).toHaveLength(0);
  });

  it("is on the menu of every role", async () => {
    for (const role of ["admin", "hr", "operation", "sales", "accounting", "reviewer", "team_lead", "translator"] as const) {
      const mocked = mockFetch({
        "/api/prefs/": () => jsonResponse({ ok: true }),
        "/api/v1/me/": () => jsonResponse(me({ role, short_name: "Mona", name: "Mona Salem", initials: "MS", is_admin: role === "admin" })),
      });
      vi.stubGlobal("fetch", mocked.fn);
      const view = renderWithProviders(
        <Routes>
          <Route element={<Shell />}>
            <Route index element={<div>home page</div>} />
          </Route>
        </Routes>,
      );
      await userEvent.click(await screen.findByTitle("Mona"));
      expect(screen.getByRole("button", { name: "غيّر كلمة السر" }), role).toBeInTheDocument();
      view.unmount();
    }
  });

  it("speaks English when the page does", async () => {
    const mocked = mockFetch({
      "/api/prefs/": () => jsonResponse({ ok: true }),
      "/api/v1/me/": () => jsonResponse(me({ short_name: "Mona" })),
    });
    vi.stubGlobal("fetch", mocked.fn);
    renderWithProviders(
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<div>home page</div>} />
        </Route>
      </Routes>,
      { lang: "en" },
    );
    await userEvent.click(await screen.findByTitle("Mona"));
    await userEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect(screen.getByLabelText("Current password")).toBeInTheDocument();
    expect(screen.getByLabelText("New password")).toBeInTheDocument();
    expect(screen.getByLabelText("New password again")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save password" })).toBeInTheDocument();
  });
});

describe("Avatar", () => {
  it("falls back to the initials when the picture is not there any more, not a broken image", () => {
    const { container } = renderWithProviders(<Avatar src="/files/avatars/gone.jpg" initials="MS" />);
    const image = container.querySelector("img")!;
    expect(image).not.toBeNull();
    act(() => void fireEvent.error(image));
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("MS")).toBeInTheDocument();
  });

  it("tries a new address after one that failed", () => {
    const view = renderWithProviders(<Avatar src="/files/avatars/gone.jpg" initials="MS" />);
    act(() => void fireEvent.error(view.container.querySelector("img")!));
    view.rerender(<Avatar src="/files/avatars/new.jpg" initials="MS" />);
    expect(view.container.querySelector("img")).toHaveAttribute("src", "/files/avatars/new.jpg");
  });
});
