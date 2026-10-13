import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { forgetDrafts } from "../components/chat/Composer";
import { entry, renderChats as render, row, visible } from "../test/chat";
import { jsonResponse } from "../test/helpers";

beforeEach(() => {
  visible("visible");
  forgetDrafts();
});
afterEach(() => {
  vi.unstubAllGlobals();
  visible("visible");
});

const BLOCK = "/api/v1/clients/CL-0001/block/";
const ADMIN = { role: { role: "admin" as const, is_admin: true } };

/** A client's thread that a test can change under the page: the row says whether the client is blocked. */
function client(blocked = false) {
  const state = { blocked };
  const routes = {
    "/api/v1/clients/": (url: URL, init?: RequestInit) => {
      if (url.pathname === BLOCK) {
        state.blocked = JSON.parse(String(init?.body)).blocked;
        return jsonResponse({ ok: true, code: "CL-0001", blocked: state.blocked });
      }
      if (url.pathname.endsWith("/read/")) return jsonResponse({ ok: true, moved: false });
      return jsonResponse({ ok: true, client: row("CL-0001", { blocked: state.blocked }), messages: [entry(1, { uid: "in-1", body: "hello" })] });
    },
  };
  return { state, routes };
}

describe("blocking a client", () => {
  it("asks first, then blocks: the note says so and the box is off", async () => {
    const { routes } = client();
    const { calls } = render("/chats/CL-0001?type=clients", ADMIN, routes);
    await userEvent.click(await screen.findByRole("button", { name: /^حظر$/ }));
    expect(calls.filter((c) => c.url === BLOCK)).toHaveLength(0);
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "احظر" }));
    await waitFor(() => expect(calls.filter((c) => c.url === BLOCK)).toHaveLength(1));
    expect(JSON.parse(String(calls.find((c) => c.url === BLOCK)!.init?.body))).toEqual({ blocked: true });
    expect(await screen.findByText("العميل ده محظور")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("العميل ده محظور: مينفعش تبعت له.")).toBeDisabled();
    expect(screen.getByRole("button", { name: /فك الحظر/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("unblocks from the same button", async () => {
    const { routes } = client(true);
    const { calls } = render("/chats/CL-0001?type=clients", ADMIN, routes);
    await userEvent.click(await screen.findByRole("button", { name: /فك الحظر/ }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "فك الحظر" }));
    await waitFor(() => expect(calls.filter((c) => c.url === BLOCK)).toHaveLength(1));
    expect(JSON.parse(String(calls.find((c) => c.url === BLOCK)!.init?.body))).toEqual({ blocked: false });
    await waitFor(() => expect(screen.queryByText("العميل ده محظور")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: /^حظر$/ })).toHaveAttribute("aria-pressed", "false");
  });

  it("is the admin's: the operation sees a blocked client's note and no button", async () => {
    const { routes } = client(true);
    render("/chats/CL-0001?type=clients", {}, routes);
    expect(await screen.findByText("العميل ده محظور")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /حظر/ })).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("العميل ده محظور: مينفعش تبعت له.")).toBeDisabled();
  });

  it("marks a blocked client in the list with a lock", async () => {
    render("/chats?type=clients", {
      lists: { clients: [row("CL-0001", { blocked: true }), row("CL-0002")] },
    });
    const blocked = (await screen.findByText("CL-0001")).closest("a") as HTMLElement;
    const other = screen.getByText("CL-0002").closest("a") as HTMLElement;
    expect(within(blocked).getByTitle("محظور")).toBeInTheDocument();
    expect(within(other).queryByTitle("محظور")).toBeNull();
  });
});
