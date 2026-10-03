import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Role, SalesLine } from "../api/types";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { SalesLinePage } from "./SalesLinePage";

afterEach(() => vi.unstubAllGlobals());

function line(over: Partial<SalesLine> = {}, values: Partial<SalesLine["values"]> = {}): SalesLine {
  return {
    ok: true,
    is_owner: true,
    values: { wa_phone_number_id: "123456", wa_display_number: "+20 100 000 0000", mail_alias: "sales1@company.example", ...values },
    company_mail: "inbox@company.example",
    ...over,
  };
}

function serve(
  body: () => Response | SalesLine,
  who: Role = "sales",
  save: (init: RequestInit | undefined) => Response | Promise<Response> = () => jsonResponse(line()),
) {
  const mocked = mockFetch({
    "/api/v1/me/": () => jsonResponse(me({ role: who, is_admin: who === "admin" })),
    "/api/v1/sales/line/save/": (_url, init) => save(init),
    "/api/v1/sales/line/": () => {
      const answer = body();
      return answer instanceof Response ? answer : jsonResponse(answer);
    },
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function open(lang: "ar" | "en" = "ar") {
  return renderWithProviders(
    <Routes>
      <Route path="/line" element={<SalesLinePage />} />
      <Route path="/" element={<div>home page</div>} />
    </Routes>,
    { route: "/line", lang },
  );
}

const saves = (calls: { url: string }[]) => calls.filter((call) => call.url === "/api/v1/sales/line/save/");

describe("SalesLinePage", () => {
  it("shows the person's own number, how clients dial it, and the address the admin gave them", async () => {
    serve(() => line());
    open();
    expect(await screen.findByRole("textbox", { name: "Phone number ID" })).toHaveValue("123456");
    expect(screen.getByRole("textbox", { name: "الرقم زي ما العميل بيكتبه (للعرض بس)" })).toHaveValue("+20 100 000 0000");
    const address = screen.getByLabelText("عنوانك على ميل الشركة");
    expect(address).toHaveValue("sales1@company.example");
    expect(address).toBeDisabled();
  });

  it("tells where the address has to deliver to: the company mailbox", async () => {
    serve(() => line());
    open();
    await screen.findByRole("textbox", { name: "Phone number ID" });
    expect(screen.getByText("inbox@company.example")).toHaveClass("mono");
  });

  it("does not make up a company mailbox when there is none", async () => {
    serve(() => line({ company_mail: "" }));
    const { container } = open();
    await screen.findByRole("textbox", { name: "Phone number ID" });
    expect(container.querySelector(".mono")).not.toHaveTextContent("@");
  });

  it("saves what was typed, trimmed, as one JSON request, and says so", async () => {
    const user = userEvent.setup();
    const mocked = serve(() => line(), "sales", () => jsonResponse(line({}, { wa_phone_number_id: "987654321", wa_display_number: "+20 1" })));
    open();
    const box = await screen.findByRole("textbox", { name: "Phone number ID" });
    await user.clear(box);
    await user.type(box, "  987654321 ");
    await user.clear(screen.getByRole("textbox", { name: "الرقم زي ما العميل بيكتبه (للعرض بس)" }));
    await user.type(screen.getByRole("textbox", { name: "الرقم زي ما العميل بيكتبه (للعرض بس)" }), "+20 1");
    await user.click(screen.getByRole("button", { name: "حفظ" }));
    expect(await screen.findByText("اتحفظ. أي عميل يكلمك على الرقم أو الإيميل ده هيظهر عندك انت بس.")).toBeInTheDocument();
    const call = mocked.calls.find((one) => one.url === "/api/v1/sales/line/save/")!;
    expect(call.init?.method).toBe("POST");
    expect(JSON.parse(String(call.init?.body))).toEqual({ wa_phone_number_id: "987654321", wa_display_number: "+20 1" });
    expect(box).toHaveValue("987654321");
  });

  it("says why a number was refused, under the box, in the server's words, and does not say it was saved", async () => {
    const user = userEvent.setup();
    serve(() => line(), "sales", () => jsonResponse({ ok: false, error: "invalid", fields: { wa_phone_number_id: "الرقم ده متسجّل لحد تاني." } }, 400));
    open();
    const box = await screen.findByRole("textbox", { name: "Phone number ID" });
    await user.clear(box);
    await user.type(box, "555");
    await user.click(screen.getByRole("button", { name: "حفظ" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("الرقم ده متسجّل لحد تاني.");
    expect(box).toHaveAttribute("aria-invalid", "true");
    expect(box).toHaveValue("555");
    expect(screen.queryByText(/اتحفظ/)).toBeNull();
  });

  it("takes the old problem away and the saved note away when the person tries again", async () => {
    const user = userEvent.setup();
    let ok = false;
    serve(() => line(), "sales", () => (ok ? jsonResponse(line()) : jsonResponse({ ok: false, error: "invalid", fields: { wa_phone_number_id: "غلط" } }, 400)));
    open();
    await screen.findByRole("textbox", { name: "Phone number ID" });
    await user.click(screen.getByRole("button", { name: "حفظ" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("غلط");
    ok = true;
    await user.click(screen.getByRole("button", { name: "حفظ" }));
    await screen.findByText(/اتحفظ/);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says it could not save when the server failed, and does not say it was refused", async () => {
    const user = userEvent.setup();
    serve(() => line(), "sales", () => jsonResponse({ ok: false, error: "server" }, 500));
    open();
    await screen.findByRole("textbox", { name: "Phone number ID" });
    await user.click(screen.getByRole("button", { name: "حفظ" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("مقدرتش أحفظ. جرّب تاني.");
  });

  it("says a value the server calls a bad request is not right", async () => {
    const user = userEvent.setup();
    serve(() => line(), "sales", () => jsonResponse({ ok: false, error: "bad_request" }, 400));
    open();
    await screen.findByRole("textbox", { name: "Phone number ID" });
    await user.click(screen.getByRole("button", { name: "حفظ" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("القيمة مش مظبوطة.");
  });

  it("sends one request for two presses", async () => {
    const user = userEvent.setup();
    let release: (() => void) | undefined;
    const mocked = serve(() => line(), "sales", () => new Promise<Response>((resolve) => (release = () => resolve(jsonResponse(line())))));
    open();
    await screen.findByRole("textbox", { name: "Phone number ID" });
    const button = screen.getByRole("button", { name: "حفظ" });
    await user.click(button);
    await user.click(button);
    expect(saves(mocked.calls)).toHaveLength(1);
    release?.();
    await waitFor(() => expect(button).toBeEnabled());
  });

  it("lets the admin read it and not save it: the boxes are off and there is no save button", async () => {
    const mocked = serve(() => line({ is_owner: false }, { wa_phone_number_id: "", wa_display_number: "", mail_alias: "" }), "admin");
    open();
    expect(await screen.findByRole("textbox", { name: "Phone number ID" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "الرقم زي ما العميل بيكتبه (للعرض بس)" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "حفظ" })).toBeNull();
    expect(screen.getByText("الصفحة دي بيملاها الـSales لنفسه. تقدر تشوفها عشان تعرف هي بتطلب إيه.")).toBeInTheDocument();
    expect(saves(mocked.calls)).toHaveLength(0);
  });

  it("does not offer the person who owns it the note meant for the admin", async () => {
    serve(() => line());
    open();
    await screen.findByRole("textbox", { name: "Phone number ID" });
    expect(screen.queryByText(/بيملاها الـSales لنفسه/)).toBeNull();
  });

  it("sends everybody else home without asking", async () => {
    for (const who of ["operation", "translator", "team_lead", "hr", "accounting", "reviewer"] as Role[]) {
      const mocked = serve(() => line(), who);
      const { unmount } = open();
      expect(await screen.findByText("home page")).toBeInTheDocument();
      expect(mocked.calls.filter((call) => call.url.startsWith("/api/v1/sales/")), who).toEqual([]);
      unmount();
    }
  });

  it("says it could not load", async () => {
    serve(() => jsonResponse({ ok: false, error: "boom" }, 500));
    open();
    expect(await screen.findByText("حصلت مشكلة في التحميل.")).toBeInTheDocument();
  });

  it("is in English too", async () => {
    serve(() => line());
    open("en");
    expect(await screen.findByRole("heading", { name: "My number & mail" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Save" })).toBeInTheDocument();
    expect(screen.getByText("WhatsApp number")).toBeInTheDocument();
    expect(screen.getByLabelText("Your address on the company mailbox")).toBeInTheDocument();
  });
});
