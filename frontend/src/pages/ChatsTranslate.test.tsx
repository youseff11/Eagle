import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { foreignWords } from "../components/chat/Bubble";
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

const TRANSLATE = "/api/v1/clients/CL-0001/messages/1/translate/";
const SALES = { role: { role: "sales" as const } };

/** A client's thread: one message in English, one in Arabic, and one of ours in English. */
function client({ offered = true, refusal = "" }: { offered?: boolean; refusal?: string } = {}) {
  const routes = {
    "/api/v1/clients/": (url: URL) => {
      if (url.pathname === TRANSLATE) {
        if (refusal) return jsonResponse({ ok: false, error: refusal }, refusal === "too_fast" ? 429 : 503);
        return jsonResponse({ ok: true, uid: "in-1", text: "من فضلك سعّرلي الملف ده" });
      }
      if (url.pathname.endsWith("/read/")) return jsonResponse({ ok: true, moved: false });
      return jsonResponse({
        ok: true,
        client: row("CL-0001", { translate: offered }),
        messages: [
          entry(1, { uid: "in-1", body: "Please quote this file" }),
          entry(2, { uid: "in-2", body: "ممكن سعر الملف ده؟" }),
          entry(3, { uid: "out-3", kind: "out", body: "We can do it", sender: "Abeer", mine: true }),
        ],
      });
    },
  };
  return routes;
}

function bubble(text: string): HTMLElement {
  return screen.getByText(text).closest(".bub") as HTMLElement;
}

describe("translating a client's message", () => {
  it("shows the Arabic under the words, asked once, and hides it again", async () => {
    const { calls } = render("/chats/CL-0001?type=clients", SALES, client());
    await screen.findByText("Please quote this file");
    const english = bubble("Please quote this file");
    await userEvent.click(within(english).getByRole("button", { name: "ترجم" }));
    expect(await within(english).findByText("من فضلك سعّرلي الملف ده")).toHaveAttribute("lang", "ar");
    expect(calls.filter((c) => c.url === TRANSLATE)).toHaveLength(1);
    expect(calls.find((c) => c.url === TRANSLATE)!.init?.method).toBe("POST");

    await userEvent.click(within(english).getByRole("button", { name: "اخفي الترجمة" }));
    expect(within(english).queryByText("من فضلك سعّرلي الملف ده")).not.toBeInTheDocument();
    await userEvent.click(within(english).getByRole("button", { name: "ترجم" }));
    expect(within(english).getByText("من فضلك سعّرلي الملف ده")).toBeInTheDocument();
    expect(calls.filter((c) => c.url === TRANSLATE)).toHaveLength(1);
  });

  it("is offered only beside the client's words that are not Arabic", async () => {
    render("/chats/CL-0001?type=clients", SALES, client());
    await screen.findByText("Please quote this file");
    expect(within(bubble("ممكن سعر الملف ده؟")).queryByRole("button", { name: "ترجم" })).not.toBeInTheDocument();
    expect(within(bubble("We can do it")).queryByRole("button", { name: "ترجم" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "ترجم" })).toHaveLength(1);
  });

  it("is not offered when the server says there is no key", async () => {
    render("/chats/CL-0001?type=clients", SALES, client({ offered: false }));
    await screen.findByText("Please quote this file");
    expect(screen.queryByRole("button", { name: "ترجم" })).not.toBeInTheDocument();
  });

  it("says why when there is no translation", async () => {
    render("/chats/CL-0001?type=clients", SALES, client({ refusal: "too_fast" }));
    await screen.findByText("Please quote this file");
    const english = bubble("Please quote this file");
    await userEvent.click(within(english).getByRole("button", { name: "ترجم" }));
    expect(await within(english).findByRole("alert")).toHaveTextContent("ترجمت رسايل كتير في دقيقة");
    await waitFor(() => expect(within(english).getByRole("button", { name: "ترجم" })).toBeEnabled());
  });
});

describe("foreignWords", () => {
  it("is true for any letter that is not Arabic, and false for Arabic, numbers and marks", () => {
    expect(foreignWords("Hola, ¿cómo estás?")).toBe(true);
    expect(foreignWords("Привет")).toBe(true);
    expect(foreignWords("你好")).toBe(true);
    expect(foreignWords("تمام، شكرا")).toBe(false);
    expect(foreignWords("123 - 4.5 !")).toBe(false);
    expect(foreignWords("")).toBe(false);
  });
});
