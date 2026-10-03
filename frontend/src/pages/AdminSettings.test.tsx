import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AdminSettings, FormField, Role } from "../api/types";
import { ToastProvider } from "../components/Toasts";
import { jsonResponse, me, mockFetch, renderWithProviders } from "../test/helpers";
import { AdminSettingsPage } from "./AdminSettingsPage";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

type Handler = (url: URL, init: RequestInit | undefined) => Response | Promise<Response>;

function field(name: string, over: Partial<FormField> = {}): FormField {
  return { name, label: name, kind: "text", required: false, help: "", disabled: false, ltr: false, value: "", ...over };
}

function secret(name: string, saved: boolean, label: [string, string] = [name, name]): FormField {
  return field(name, { kind: "password", ltr: true, saved, label_ar: label[0], label_en: label[1], value: undefined });
}

function settings(over: Partial<AdminSettings> = {}): AdminSettings {
  return {
    ok: true,
    fields: [
      field("ai_check_enabled", { kind: "checkbox", value: false, label_ar: "فعّل مراجعة الـ AI", label_en: "Enable the AI check" }),
      secret("claude_api_key", true, ["مفتاح Claude API", "Claude API key"]),
      field("claude_model", { value: "claude-old", label_ar: "الموديل", label_en: "Model" }),
      field("response_window_seconds", { kind: "number", value: 60, label_ar: "مهلة تأكيد الاستلام (ثانية)", label_en: "Confirmation window (seconds)" }),
      field("rate_keywords", { kind: "textarea", value: "price, rate", label_ar: "الكلمات اللي بتخفي الرسالة عن الأوبريشن", label_en: "Keywords", hint_ar: "افصل بينهم بفاصلة.", hint_en: "Comma separated." }),
      field("whatsapp_phone_number_id", { value: "12345", label_ar: "Phone number ID", label_en: "Phone number ID" }),
      secret("whatsapp_access_token", true, ["Access token", "Access token"]),
      secret("imap_password", false, ["Password", "Password"]),
      field("imap_host", { value: "imap.example.com", label_ar: "Host", label_en: "Host" }),
      field("mail_aliases", { kind: "textarea", value: "a@example.com", label_ar: "العناوين الموجودة على ميل الشركة", label_en: "Aliases on the company mailbox" }),
      field("google_client_id", { value: "cid", label_ar: "Client ID", label_en: "Client ID" }),
      secret("google_client_secret", true, ["Client Secret", "Client Secret"]),
      field("newui_operation_roles", {
        kind: "multi",
        value: ["admin"],
        choices: [
          { value: "admin", label: "أدمن · Admin" },
          { value: "operation", label: "أوبريشن · Operation" },
        ],
      }),
      field("newui_operation_users", { kind: "multi", value: [], choices: [{ value: "7", label: "Nour Operation" }] }),
      field("newui_admin_roles", { kind: "multi", value: [], choices: [{ value: "admin", label: "أدمن · Admin" }] }),
      field("newui_admin_users", { kind: "multi", value: [], choices: [] }),
    ],
    sections: [
      { key: "ai", icon: "sparkles", ar: "مراجعة الترجمة بالـ AI", en: "AI translation check", note_ar: "لما تكون مفعّلة", note_en: "When enabled", groups: [{ fields: ["ai_check_enabled", "claude_api_key", "claude_model"] }] },
      { key: "workflow", icon: "list-checks", ar: "قواعد الشغل", en: "Workflow rules", groups: [{ fields: ["response_window_seconds", "rate_keywords"] }] },
      { key: "newui", icon: "layers", ar: "الواجهة الجديدة", en: "The new interface", groups: [] },
      { key: "whatsapp", icon: "phone", ar: "واتساب", en: "WhatsApp", groups: [{ fields: ["whatsapp_phone_number_id", "whatsapp_access_token"] }] },
      {
        key: "email", icon: "mail", ar: "الإيميل", en: "Email",
        groups: [
          { ar: "استقبال (IMAP)", en: "Receiving (IMAP)", fields: ["imap_host", "imap_password"] },
          { fields: ["mail_aliases"] },
          { ar: "مزامنة العناوين مع Google", en: "Sync aliases with Google", fields: ["google_client_id", "google_client_secret"] },
        ],
      },
    ],
    newui: [
      { key: "operation", ar: "شاشة الأوبريشن", en: "The operation's screen", roles: "newui_operation_roles", users: "newui_operation_users" },
      { key: "admin", ar: "لوحة الأدمن", en: "The admin panel", roles: "newui_admin_roles", users: "newui_admin_users" },
    ],
    status: {
      whatsapp_saved: true, email_saved: false, google_configured: true, google_connected: false, google_sync_at: null, google_sync_error: "",
      webhook_signed: true, webhook_secret_set: true,
    },
    urls: { webhook: "https://eagle.example.com/webhooks/whatsapp/", google_redirect: "https://eagle.example.com/panel/settings/google/callback/", google_connect: "/panel/settings/google/connect/", is_local: false, is_https: true },
    ...over,
  };
}

function serve(who: Role, data: () => AdminSettings = settings, over: Record<string, Handler> = {}) {
  const sent: { url: string; body: unknown }[] = [];
  const record = (url: URL, init: RequestInit | undefined, answer: unknown, status = 200) => {
    sent.push({ url: url.pathname, body: init?.body ? JSON.parse(String(init.body)) : null });
    return jsonResponse(answer, status);
  };
  const defaults: Record<string, Handler> = {
    "/api/v1/me/": () => jsonResponse(me({ role: who, is_admin: who === "admin" })),
    "/api/v1/admin/settings/save/": (url, init) => record(url, init, { ok: true }),
    "/api/v1/admin/settings/google/sync/": (url, init) => record(url, init, { ok: true, ran: true, error: "", added: ["new@example.com"], removed: [], released: [] }),
    "/api/v1/admin/settings/google/disconnect/": (url, init) => record(url, init, { ok: true }),
    "/api/v1/admin/settings/test/whatsapp/": (url, init) => record(url, init, { ok: true, number: "+20100", name: "Eagle", sent: true }),
    "/api/v1/admin/settings/test/email/": (url, init) => record(url, init, { ok: true, host: "smtp.example.com", user: "mail@example.com" }),
    "/api/v1/admin/settings/": () => jsonResponse(data()),
  };
  const routes = { ...over };
  for (const [prefix, answer] of Object.entries(defaults)) if (!(prefix in routes)) routes[prefix] = answer;
  const mocked = mockFetch(routes);
  vi.stubGlobal("fetch", mocked.fn);
  return { ...mocked, sent };
}

function open(lang: "ar" | "en" = "ar") {
  return renderWithProviders(
    <ToastProvider>
      <Routes>
        <Route path="/admin/settings" element={<AdminSettingsPage />} />
        <Route path="/" element={<div>home page</div>} />
      </Routes>
    </ToastProvider>,
    { route: "/admin/settings", lang },
  );
}

const saves = (served: ReturnType<typeof serve>) => served.sent.filter((post) => post.url === "/api/v1/admin/settings/save/");

describe("AdminSettingsPage: what it draws", () => {
  it("draws the sections in order with the classic page's titles, notes and bilingual labels", async () => {
    serve("admin");
    const { container } = open();
    await screen.findByText("مراجعة الترجمة بالـ AI");
    expect(Array.from(container.querySelectorAll("[data-section]")).map((one) => one.getAttribute("data-section"))).toEqual(["ai", "workflow", "newui", "whatsapp", "email"]);
    expect(screen.getByLabelText("الموديل")).toHaveValue("claude-old");
    expect(screen.getByLabelText("فعّل مراجعة الـ AI")).not.toBeChecked();
    expect(screen.getByText("افصل بينهم بفاصلة.")).toHaveClass("helptext");
    expect(screen.getByText("استقبال (IMAP)")).toHaveClass("label");
  });

  it("speaks English with the English labels", async () => {
    serve("admin");
    open("en");
    expect(await screen.findByLabelText("Model")).toHaveValue("claude-old");
    expect(screen.getByText("Comma separated.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Save settings/ })).toBeInTheDocument();
  });

  it("shows whether the WhatsApp keys and the mail settings are saved", async () => {
    serve("admin");
    const { container } = open();
    await screen.findByText("واتساب");
    expect(within(container.querySelector('[data-section="whatsapp"]') as HTMLElement).getByText("المفاتيح محفوظة")).toBeInTheDocument();
    expect(within(container.querySelector('[data-section="email"]') as HTMLElement).getByText("لسه متحفظش")).toBeInTheDocument();
  });

  it("sends anybody who is not the admin home and asks the server for nothing", async () => {
    const served = serve("sales");
    open();
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(served.calls.some((call) => call.url.startsWith("/api/v1/admin/"))).toBe(false);
  });

  it("says so when the page cannot be read", async () => {
    serve("admin", settings, { "/api/v1/admin/settings/": () => jsonResponse({ ok: false, error: "server" }, 500) });
    open();
    expect(await screen.findByRole("alert")).toHaveTextContent("حصلت مشكلة في التحميل.");
  });
});

describe("AdminSettingsPage: secrets", () => {
  it("draws a saved secret as an empty password box that says it is saved - the value is not on the page", async () => {
    serve("admin");
    open();
    const box = await screen.findByLabelText("مفتاح Claude API");
    expect(box).toHaveAttribute("type", "password");
    expect(box).toHaveValue("");
    expect(box).toHaveAttribute("autocomplete", "new-password");
    expect(box).toHaveAttribute("placeholder", expect.stringContaining("محفوظ"));
    expect(screen.getByLabelText("Password")).not.toHaveAttribute("placeholder", expect.stringContaining("محفوظ"));
  });

  it("sends nothing for a secret that was not touched", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    open();
    await user.type(await screen.findByLabelText("الموديل"), "-x");
    await user.click(screen.getByRole("button", { name: /حفظ الإعدادات/ }));
    await waitFor(() => expect(saves(served).length).toBe(1));
    const values = (saves(served)[0]!.body as { values: Record<string, unknown> }).values;
    expect(values).toEqual({ claude_model: "claude-old-x" });
  });

  it("sends a secret only when it is typed", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    open();
    await user.type(await screen.findByLabelText("Access token"), "EAAG-new-token");
    await user.click(screen.getByRole("button", { name: /حفظ الإعدادات/ }));
    await waitFor(() => expect(saves(served).length).toBe(1));
    expect((saves(served)[0]!.body as { values: unknown }).values).toEqual({ whatsapp_access_token: "EAAG-new-token" });
  });

  it("clears a saved secret only through its own tick, and sends null", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    const { container } = open();
    await screen.findByLabelText("مفتاح Claude API");
    const tick = within(container.querySelector('[data-field="claude_api_key"]') as HTMLElement).getByRole("checkbox", { name: /امسح القيمة المحفوظة/ });
    await user.click(tick);
    expect(screen.getByLabelText("مفتاح Claude API")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /حفظ الإعدادات/ }));
    await waitFor(() => expect(saves(served).length).toBe(1));
    expect((saves(served)[0]!.body as { values: unknown }).values).toEqual({ claude_api_key: null });
  });

  it("offers no clear tick for a secret that is not saved", async () => {
    serve("admin");
    const { container } = open();
    await screen.findByLabelText("Password");
    expect(within(container.querySelector('[data-field="imap_password"]') as HTMLElement).queryByRole("checkbox")).toBeNull();
  });

  it("keeps what was typed in a secret box out of the address and the rest of the page", async () => {
    serve("admin");
    const user = userEvent.setup();
    const { container } = open();
    await user.type(await screen.findByLabelText("Access token"), "EAAG-typed-secret");
    expect(window.location.href).not.toContain("EAAG-typed-secret");
    expect(container.querySelector('input[type="password"]')).not.toBeNull();
    expect(Array.from(container.querySelectorAll('input:not([type="password"])')).some((input) => (input as HTMLInputElement).value.includes("EAAG-typed-secret"))).toBe(false);
  });
});

describe("AdminSettingsPage: saving", () => {
  it("cannot be saved until something changes", async () => {
    serve("admin");
    open();
    expect(await screen.findByRole("button", { name: /حفظ الإعدادات/ })).toBeDisabled();
  });

  it("sends only the changed boxes, a ticked box as a boolean and a list as a list", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    open();
    await user.click(await screen.findByLabelText("فعّل مراجعة الـ AI"));
    await user.clear(screen.getByLabelText("مهلة تأكيد الاستلام (ثانية)"));
    await user.type(screen.getByLabelText("مهلة تأكيد الاستلام (ثانية)"), "90");
    await user.click(screen.getByRole("button", { name: /حفظ الإعدادات/ }));
    await waitFor(() => expect(saves(served).length).toBe(1));
    expect((saves(served)[0]!.body as { values: unknown }).values).toEqual({ ai_check_enabled: true, response_window_seconds: "90" });
  });

  it("starts clean again after a save and reads the settings again", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    open();
    await user.type(await screen.findByLabelText("الموديل"), "x");
    await user.click(screen.getByRole("button", { name: /حفظ الإعدادات/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /حفظ الإعدادات/ })).toBeDisabled());
    await waitFor(() => expect(served.calls.filter((call) => call.url === "/api/v1/admin/settings/").length).toBe(2));
  });

  it("shows the form's refusals beside their boxes, says nothing was saved, and keeps what was typed", async () => {
    serve("admin", settings, {
      "/api/v1/admin/settings/save/": () => jsonResponse({ ok: false, error: "invalid", errors: { mail_aliases: ["مش إيميل صحيح: nope"], __all__: ["Something about the whole form."] } }, 400),
    });
    const user = userEvent.setup();
    open();
    await user.type(await screen.findByLabelText("العناوين الموجودة على ميل الشركة"), "nope");
    await user.click(screen.getByRole("button", { name: /حفظ الإعدادات/ }));
    expect(await screen.findByText("مش إيميل صحيح: nope")).toBeInTheDocument();
    expect(screen.getByText("Something about the whole form.")).toBeInTheDocument();
    expect(screen.getByText("اتحفظش حاجة: راجع الحقول اللي جنبها خطأ.")).toBeInTheDocument();
    expect(screen.getByLabelText("العناوين الموجودة على ميل الشركة")).toHaveValue("a@example.comnope");
    expect(screen.getByRole("button", { name: /حفظ الإعدادات/ })).toBeEnabled();
  });

  it("says so when the save fails for a reason that is not the form's", async () => {
    serve("admin", settings, { "/api/v1/admin/settings/save/": () => jsonResponse({ ok: false, error: "server" }, 500) });
    const user = userEvent.setup();
    open();
    await user.type(await screen.findByLabelText("الموديل"), "x");
    await user.click(screen.getByRole("button", { name: /حفظ الإعدادات/ }));
    expect(await screen.findByText("حصلت مشكلة، ماتحفظش حاجة.")).toBeInTheDocument();
  });
});

describe("AdminSettingsPage: the switches for the new interface", () => {
  it("draws one row per screen with its roles and the people it can be tried on", async () => {
    serve("admin");
    const { container } = open();
    await screen.findByText("شاشة الأوبريشن");
    const row = container.querySelector('[data-screen="operation"]') as HTMLElement;
    expect(within(row).getByRole("checkbox", { name: "أدمن · Admin" })).toBeChecked();
    expect(within(row).getByRole("checkbox", { name: "أوبريشن · Operation" })).not.toBeChecked();
    expect(within(row).getByRole("checkbox", { name: "Nour Operation" })).not.toBeChecked();
    expect(within(row).getByText(/\?classic=1/)).toBeInTheDocument();
    const admin = container.querySelector('[data-screen="admin"]') as HTMLElement;
    expect(within(admin).queryByText(/ناس بالاسم/)).toBeNull();
  });

  it("sends the whole list of roles when one is ticked", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    const { container } = open();
    await screen.findByText("شاشة الأوبريشن");
    const row = container.querySelector('[data-screen="operation"]') as HTMLElement;
    await user.click(within(row).getByRole("checkbox", { name: "أوبريشن · Operation" }));
    await user.click(within(row).getByRole("checkbox", { name: "Nour Operation" }));
    await user.click(screen.getByRole("button", { name: /حفظ الإعدادات/ }));
    await waitFor(() => expect(saves(served).length).toBe(1));
    expect((saves(served)[0]!.body as { values: unknown }).values).toEqual({ newui_operation_roles: ["admin", "operation"], newui_operation_users: ["7"] });
  });

  it("sends nothing about the switches when only something else changed", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    open();
    await user.type(await screen.findByLabelText("الموديل"), "x");
    await user.click(screen.getByRole("button", { name: /حفظ الإعدادات/ }));
    await waitFor(() => expect(saves(served).length).toBe(1));
    const sent = Object.keys((saves(served)[0]!.body as { values: Record<string, unknown> }).values);
    expect(sent.filter((name) => name.startsWith("newui_"))).toEqual([]);
  });

  it("shows a refusal of a switch beside its row", async () => {
    serve("admin", settings, {
      "/api/v1/admin/settings/save/": () => jsonResponse({ ok: false, error: "invalid", errors: { newui_operation_roles: ["Select a valid choice."] } }, 400),
    });
    const user = userEvent.setup();
    const { container } = open();
    await screen.findByText("شاشة الأوبريشن");
    const row = container.querySelector('[data-screen="operation"]') as HTMLElement;
    await user.click(within(row).getByRole("checkbox", { name: "أوبريشن · Operation" }));
    await user.click(screen.getByRole("button", { name: /حفظ الإعدادات/ }));
    expect(await within(row).findByText("Select a valid choice.")).toBeInTheDocument();
  });
});

describe("AdminSettingsPage: WhatsApp", () => {
  it("shows the address to register, and copies it", async () => {
    serve("admin");
    const user = userEvent.setup();
    const write = vi.spyOn(navigator.clipboard, "writeText");
    const { container } = open();
    await screen.findByText("واتساب");
    expect(container.querySelector("#whUrl")).toHaveTextContent("https://eagle.example.com/webhooks/whatsapp/");
    await user.click(screen.getByRole("button", { name: "نسخ" }));
    expect(write).toHaveBeenCalledWith("https://eagle.example.com/webhooks/whatsapp/");
  });

  it("says nothing about the webhook when it can check a signature and has its secret", async () => {
    serve("admin");
    const { container } = open();
    await screen.findByText("واتساب");
    expect(container.querySelector("[data-warning]")).toBeNull();
  });

  it("warns that anybody can send a Meta-looking message when the App secret is not saved", async () => {
    serve("admin", () => settings({ status: { ...settings().status, webhook_signed: false } }));
    const { container } = open();
    const warning = await waitFor(() => {
      const found = container.querySelector('[data-warning="unsigned"]');
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    expect(warning).toHaveClass("note--warn");
    expect(warning).toHaveTextContent("الـApp secret مش محفوظ");
    expect(container.querySelector('[data-warning="open"]')).toBeNull();
  });

  it("warns that the simple webhook takes any request when its secret is not set", async () => {
    serve("admin", () => settings({ status: { ...settings().status, webhook_secret_set: false } }));
    const { container } = open();
    await waitFor(() => expect(container.querySelector('[data-warning="open"]')).not.toBeNull());
    expect(container.querySelector('[data-warning="unsigned"]')).toBeNull();
  });

  it("warns about a local address, and about an address that is not https", async () => {
    serve("admin", () => settings({ urls: { ...settings().urls, is_local: true, is_https: false } }));
    const view = open();
    expect(await screen.findByText(/الرابط ده محلي/)).toBeInTheDocument();
    expect(screen.queryByText("Meta بتقبل HTTPS بس.")).toBeNull();
    view.unmount();
    serve("admin", () => settings({ urls: { ...settings().urls, is_local: false, is_https: false } }));
    open();
    expect(await screen.findByText("Meta بتقبل HTTPS بس.")).toBeInTheDocument();
  });

  it("tests the connection as saved and shows what it found", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    open();
    await user.type(await screen.findByLabelText("رقم للتجربة (اختياري) 2010…"), "20100123");
    await user.click(within(document.querySelector('[data-section="whatsapp"]') as HTMLElement).getByRole("button", { name: /احفظ واختبر الاتصال/ }));
    const result = await screen.findByText("الاتصال بواتساب شغال");
    expect(result.closest(".note")).toHaveClass("note--ok");
    expect(result.parentElement).toHaveTextContent("+20100 · Eagle · واتبعت رسالة اختبار");
    expect(served.sent.find((post) => post.url === "/api/v1/admin/settings/test/whatsapp/")!.body).toEqual({ to: "20100123" });
    expect(saves(served)).toEqual([]);
  });

  it("saves what was changed first, then tests", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    open();
    await user.type(await screen.findByLabelText("Phone number ID"), "9");
    await user.click(within(document.querySelector('[data-section="whatsapp"]') as HTMLElement).getByRole("button", { name: /احفظ واختبر الاتصال/ }));
    await screen.findByText("الاتصال بواتساب شغال");
    expect(served.sent.map((post) => post.url)).toEqual(["/api/v1/admin/settings/save/", "/api/v1/admin/settings/test/whatsapp/"]);
    expect((saves(served)[0]!.body as { values: unknown }).values).toEqual({ whatsapp_phone_number_id: "123459" });
  });

  it("does not test when the save is refused, and says which box is wrong", async () => {
    const served = serve("admin", settings, {
      "/api/v1/admin/settings/save/": () => jsonResponse({ ok: false, error: "invalid", errors: { whatsapp_phone_number_id: ["Enter a number."] } }, 400),
    });
    const user = userEvent.setup();
    open();
    await user.type(await screen.findByLabelText("Phone number ID"), "x");
    await user.click(within(document.querySelector('[data-section="whatsapp"]') as HTMLElement).getByRole("button", { name: /احفظ واختبر الاتصال/ }));
    expect(await screen.findByText(/الحفظ فشل — فيه حقل غلط: whatsapp_phone_number_id/)).toBeInTheDocument();
    expect(served.sent.some((post) => post.url.includes("/test/"))).toBe(false);
  });

  it("shows the reason in the page's language when the connection is bad", async () => {
    serve("admin", settings, {
      "/api/v1/admin/settings/test/whatsapp/": () => jsonResponse({ ok: false, error_ar: "التوكن غلط", error_en: "Bad token" }),
    });
    const user = userEvent.setup();
    open();
    await user.click(within((await screen.findByText("واتساب")).closest(".card") as HTMLElement).getByRole("button", { name: /احفظ واختبر الاتصال/ }));
    const note = (await screen.findByText("التوكن غلط")).closest(".note");
    expect(note).toHaveClass("note--high");
  });
});

describe("AdminSettingsPage: the mail and Google", () => {
  it("tests the mail connection", async () => {
    const served = serve("admin");
    const user = userEvent.setup();
    open();
    await screen.findByText("الإيميل");
    await user.type(screen.getByLabelText("إيميل للتجربة (اختياري)"), "me@example.com");
    await user.click(within(document.querySelector('[data-section="email"]') as HTMLElement).getByRole("button", { name: /احفظ واختبر الاتصال/ }));
    expect(await screen.findByText("الاتصال بالإيميل شغال")).toBeInTheDocument();
    expect(served.sent.find((post) => post.url === "/api/v1/admin/settings/test/email/")!.body).toEqual({ to: "me@example.com" });
  });

  it("says Google is not linked, offers to connect when the client is set, and shows the address to register", async () => {
    serve("admin");
    open();
    const connect = await screen.findByRole("link", { name: "اربط Google" });
    expect(connect).toHaveAttribute("href", "/panel/settings/google/connect/");
    expect(screen.getByText("مش مربوط")).toBeInTheDocument();
    expect(screen.getByLabelText("Redirect URI")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("Redirect URI")).toHaveValue("https://eagle.example.com/panel/settings/google/callback/");
    expect(screen.queryByRole("button", { name: /حدّث دلوقتي/ })).toBeNull();
  });

  it("asks for the client first when it is not set", async () => {
    serve("admin", () => settings({ status: { ...settings().status, google_configured: false } }));
    open();
    expect(await screen.findByText("اكتب Client ID وClient Secret واحفظ، وبعدين اربط.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "اربط Google" })).toBeNull();
  });

  it("when linked: says so, shows the last sync and its error, and the alias list is Google's", async () => {
    serve("admin", () => settings({ status: { ...settings().status, google_connected: true, google_sync_at: { ar: "10/03 5:00 م", en: "10/03 5:00 PM" }, google_sync_error: "Google said no" } }));
    open();
    expect(await screen.findByText("مربوط")).toBeInTheDocument();
    expect(screen.getByText("10/03 5:00 م")).toHaveClass("mono");
    expect(screen.getByText("Google said no")).toHaveClass("errorlist");
    expect(screen.getByRole("link", { name: "اربط تاني" })).toBeInTheDocument();
    expect(screen.getByText(/مربوطة بـ Google: القايمة بتتحدّث لوحدها/)).toBeInTheDocument();
  });

  it("syncs now and says what changed", async () => {
    const served = serve("admin", () => settings({ status: { ...settings().status, google_connected: true } }));
    const user = userEvent.setup();
    open();
    await user.click(await screen.findByRole("button", { name: /حدّث دلوقتي/ }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/admin/settings/google/sync/")).toBe(true));
    expect(await screen.findByText("اتضاف: new@example.com")).toBeInTheDocument();
  });

  it("shows Google's error when the sync could not run", async () => {
    serve("admin", () => settings({ status: { ...settings().status, google_connected: true } }), {
      "/api/v1/admin/settings/google/sync/": () => jsonResponse({ ok: true, ran: false, error: "Google refused", added: [], removed: [], released: [] }),
    });
    const user = userEvent.setup();
    open();
    await user.click(await screen.findByRole("button", { name: /حدّث دلوقتي/ }));
    expect(await screen.findByText("Google refused")).toBeInTheDocument();
  });

  it("disconnects and reads the page again", async () => {
    const served = serve("admin", () => settings({ status: { ...settings().status, google_connected: true } }));
    const user = userEvent.setup();
    open();
    await user.click(await screen.findByRole("button", { name: "افصل" }));
    await waitFor(() => expect(served.sent.some((post) => post.url === "/api/v1/admin/settings/google/disconnect/")).toBe(true));
    await waitFor(() => expect(served.calls.filter((call) => call.url === "/api/v1/admin/settings/").length).toBe(2));
  });
});
