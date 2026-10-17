import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { forgetDrafts } from "../components/chat/Composer";
import type { FollowupOffer } from "../api/types";
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

const FOLLOWUP = "/api/v1/clients/CL-0001/followup/";
const OPS = { role: { role: "operation" as const } };
const OFFER: FollowupOffer = {
  language: "ar",
  texts: { ar: "أهلًا CL-0001، معاك فريق EagleLingua بخصوص طلبك معانا.", en: "Hello CL-0001, this is the EagleLingua team." },
  sent_recently: false,
};

/** A client's thread whose window is closed; the follow-up answers `answer` (a status and a body). */
function client(offer: FollowupOffer | null, answer: { status: number; body: unknown } = { status: 200, body: { ok: true, delivered: true, error: "" } }) {
  return {
    "/api/v1/clients/": (url: URL) => {
      if (url.pathname === FOLLOWUP) return jsonResponse(answer.body, answer.status);
      if (url.pathname.endsWith("/read/")) return jsonResponse({ ok: true, moved: false });
      return jsonResponse({
        ok: true,
        client: row("CL-0001", { window_open: false, followup: offer }),
        messages: [entry(1, { uid: "in-1", body: "hello" })],
      });
    },
  };
}

describe("the follow-up message", () => {
  it("is offered under the closed window, shows its words and sends the language picked", async () => {
    const { calls } = render("/chats/CL-0001?type=clients", OPS, client(OFFER));
    await userEvent.click(await screen.findByRole("button", { name: "رسالة متابعة" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByTestId("followupText")).toHaveTextContent(OFFER.texts.ar);
    await userEvent.click(within(dialog).getByRole("button", { name: "English" }));
    expect(within(dialog).getByTestId("followupText")).toHaveTextContent(OFFER.texts.en);
    expect(calls.filter((c) => c.url === FOLLOWUP)).toHaveLength(0);
    await userEvent.click(within(dialog).getByRole("button", { name: "ابعت" }));
    await waitFor(() => expect(calls.filter((c) => c.url === FOLLOWUP)).toHaveLength(1));
    expect(JSON.parse(String(calls.find((c) => c.url === FOLLOWUP)!.init?.body))).toEqual({ language: "en" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("is not offered when the server offers none", async () => {
    render("/chats/CL-0001?type=clients", OPS, client(null));
    expect(await screen.findByText("نافذة الـ24 ساعة قفلت")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "رسالة متابعة" })).not.toBeInTheDocument();
  });

  it("says why nothing went, and does not offer a second one the same day", async () => {
    render("/chats/CL-0001?type=clients", OPS, client(OFFER, { status: 409, body: { ok: false, error: "sent_recently" } }));
    await userEvent.click(await screen.findByRole("button", { name: "رسالة متابعة" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "ابعت" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("رسالة المتابعة اتبعتت في آخر 24 ساعة");
  });

  it("keeps the dialog open with WhatsApp's reason when Meta refused it", async () => {
    render("/chats/CL-0001?type=clients", OPS, client(OFFER, { status: 200, body: { ok: true, delivered: false, error: "واتساب رفض القالب" } }));
    await userEvent.click(await screen.findByRole("button", { name: "رسالة متابعة" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "ابعت" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("واتساب رفض القالب");
  });

  it("turns the send off when one already went today", async () => {
    render("/chats/CL-0001?type=clients", OPS, client({ ...OFFER, sent_recently: true }));
    await userEvent.click(await screen.findByRole("button", { name: "رسالة متابعة" }));
    expect(within(await screen.findByRole("dialog")).getByRole("button", { name: "ابعت" })).toBeDisabled();
  });
});
