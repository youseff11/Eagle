import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PreferencesProvider } from "../i18n/Preferences";
import { PROGRESS_DELAY_MS, TopProgress } from "./TopProgress";

afterEach(() => vi.useRealTimers());

function Page({ finish }: { finish: Promise<string> }) {
  useQuery({ queryKey: ["page"], queryFn: () => finish });
  return null;
}

function frame(client: QueryClient, finish: Promise<string>) {
  return render(
    <QueryClientProvider client={client}>
      <PreferencesProvider initialLang="ar" initialTheme="dark">
        <TopProgress />
        <Page finish={finish} />
      </PreferencesProvider>
    </QueryClientProvider>,
  );
}

describe("TopProgress", () => {
  it("shows a bar only when a page that has nothing to draw yet waits for longer than a moment, and takes it away when it arrives", async () => {
    vi.useFakeTimers();
    let arrive: (value: string) => void = () => undefined;
    const finish = new Promise<string>((resolve) => (arrive = resolve));
    frame(new QueryClient(), finish);
    expect(screen.queryByRole("progressbar")).toBeNull();
    // The ask starts (the query's own notice runs on a timer), then the bar's delay begins.
    await act(async () => void vi.advanceTimersByTime(10));
    expect(screen.queryByRole("progressbar")).toBeNull();
    await act(async () => void vi.advanceTimersByTime(PROGRESS_DELAY_MS + 20));
    expect(screen.getByRole("progressbar")).toHaveClass("top-progress");
    await act(async () => {
      arrive("here");
      await Promise.resolve();
    });
    await act(async () => void vi.advanceTimersByTime(10));
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("does not show for an ask made again behind a page that is already drawn", async () => {
    vi.useFakeTimers();
    const client = new QueryClient();
    client.setQueryData(["page"], "already here");
    frame(client, new Promise<string>(() => undefined));
    await act(async () => void vi.advanceTimersByTime(PROGRESS_DELAY_MS * 4));
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("does not show for a page that arrives inside the delay", async () => {
    vi.useFakeTimers();
    frame(new QueryClient(), Promise.resolve("fast"));
    await act(async () => void vi.advanceTimersByTime(PROGRESS_DELAY_MS * 4));
    expect(screen.queryByRole("progressbar")).toBeNull();
  });
});
