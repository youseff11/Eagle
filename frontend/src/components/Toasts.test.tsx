import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PreferencesProvider } from "../i18n/Preferences";
import { MAX_TOASTS, STICKY_TOAST_MS, TOAST_MS, ToastProvider, useToasts, type ToastInput } from "./Toasts";

afterEach(() => {
  vi.useRealTimers();
});

/** A page that can push toasts, with the provider around it. */
function Pusher({ toasts }: { toasts: ToastInput[] }) {
  const { push } = useToasts();
  return (
    <button type="button" onClick={() => toasts.forEach(push)}>
      push
    </button>
  );
}

function renderToasts(toasts: ToastInput[]) {
  return render(
    <PreferencesProvider initialLang="ar" initialTheme="dark">
      <ToastProvider>
        <Pusher toasts={toasts} />
      </ToastProvider>
    </PreferencesProvider>,
  );
}

async function pushNow() {
  await act(async () => {
    screen.getByRole("button", { name: "push" }).click();
  });
}

describe("Toasts", () => {
  it("goes away by itself after seven seconds, a sticky one after fifteen", async () => {
    vi.useFakeTimers();
    renderToasts([{ title: "عادي" }, { title: "لازم يتقرا", sticky: true }]);
    await pushNow();
    expect(screen.getByText("عادي")).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(TOAST_MS - 100);
    });
    expect(screen.getByText("عادي")).toBeInTheDocument();
    await act(async () => {
      vi.advanceTimersByTime(100 + 300);
    });
    expect(screen.queryByText("عادي")).toBeNull();
    expect(screen.getByText("لازم يتقرا")).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(STICKY_TOAST_MS - TOAST_MS);
    });
    expect(screen.queryByText("لازم يتقرا")).toBeNull();
  });

  it("keeps four at most and drops the oldest", async () => {
    renderToasts(["أ", "ب", "ج", "د", "هـ"].map((title) => ({ title })));
    await pushNow();
    const shown = Array.from(document.querySelectorAll(".toast__title")).map((node) => node.textContent);
    expect(shown).toHaveLength(MAX_TOASTS);
    expect(shown).toEqual(["ب", "ج", "د", "هـ"]);
  });

  it("is a status for a notice and an alert for a danger one, with the level's look", async () => {
    renderToasts([
      { title: "معلومة" },
      { title: "تمام", level: "success" },
      { title: "حاسب", level: "warning" },
      { title: "غلط", level: "danger" },
    ]);
    await pushNow();
    expect(screen.getByText("معلومة").closest(".toast")).toHaveClass("toast--info");
    expect(screen.getByText("تمام").closest(".toast")).toHaveClass("toast--success");
    expect(screen.getByText("حاسب").closest(".toast")).toHaveClass("toast--warning");
    expect(screen.getByRole("alert")).toHaveClass("toast--danger");
    expect(screen.getAllByRole("status")).toHaveLength(3);
  });

  it("draws the words as text, never as markup", async () => {
    renderToasts([{ title: "<img src=x onerror=alert(1)>", body: "<b>bold</b>" }]);
    await pushNow();
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(document.querySelector(".toast img")).toBeNull();
    expect(document.querySelector(".toast b")).toBeNull();
  });

  it("closes by its button", async () => {
    renderToasts([{ title: "هتتقفل" }]);
    await pushNow();
    await userEvent.click(screen.getByRole("button", { name: "اقفل" }));
    await vi.waitFor(() => expect(screen.queryByText("هتتقفل")).toBeNull());
  });

  it("does nothing, without an error, outside a provider", async () => {
    render(
      <PreferencesProvider initialLang="ar" initialTheme="dark">
        <Pusher toasts={[{ title: "في الهوا" }]} />
      </PreferencesProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "push" }));
    expect(screen.queryByText("في الهوا")).toBeNull();
  });
});
