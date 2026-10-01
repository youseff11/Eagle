import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/helpers";
import { ErrorBoundary } from "./ErrorBoundary";

beforeEach(() => {
  // React reports a caught render error to the console; the tests expect them.
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});
afterEach(() => vi.restoreAllMocks());

function Bomb({ explode }: { explode: boolean }) {
  if (explode) throw new Error("boom");
  return <div>the page</div>;
}

describe("ErrorBoundary", () => {
  it("shows the page when nothing is wrong", () => {
    renderWithProviders(
      <ErrorBoundary>
        <Bomb explode={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByText("the page")).toBeInTheDocument();
  });

  it("keeps a failing page inside a message with the way to the classic interface", () => {
    renderWithProviders(
      <ErrorBoundary>
        <Bomb explode />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("حصلت مشكلة في عرض الصفحة دي.");
    expect(screen.getByRole("link", { name: "افتح الواجهة الحالية" })).toHaveAttribute("href", "/?classic=1");
    expect(screen.getByRole("button", { name: "جرّب تاني" })).toBeInTheDocument();
  });

  it("speaks English when asked", () => {
    renderWithProviders(
      <ErrorBoundary>
        <Bomb explode />
      </ErrorBoundary>,
      { lang: "en" },
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong showing this page.");
  });

  it("gives the next page a fresh start when the reset key changes", async () => {
    function Harness() {
      const [path, setPath] = useState("/broken");
      return (
        <>
          <button type="button" onClick={() => setPath("/fine")}>
            go
          </button>
          <ErrorBoundary resetKey={path}>
            <Bomb explode={path === "/broken"} />
          </ErrorBoundary>
        </>
      );
    }
    renderWithProviders(<Harness />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "go" }));
    expect(screen.getByText("the page")).toBeInTheDocument();
  });
});
