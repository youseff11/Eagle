import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AHEAD_AGED_EVENT } from "../api/client";
import { jsonResponse, me, mockFetch } from "../test/helpers";
import { useAskAhead } from "./useAskAhead";

afterEach(() => vi.unstubAllGlobals());

function Frame({ who }: { who: ReturnType<typeof me> | undefined }) {
  useAskAhead(who);
  return (
    <div>
      <a href="/app/hr/leave">leave</a>
      <a href="/app/clients/CL-0001">a client</a>
      <a href="https://example.com/app/hr/leave">elsewhere</a>
    </div>
  );
}

function draw(who: ReturnType<typeof me> | undefined, client = new QueryClient()) {
  const mocked = mockFetch({ "/api/v1/": () => jsonResponse({ ok: true }) });
  vi.stubGlobal("fetch", mocked.fn);
  const view = render(
    <QueryClientProvider client={client}>
      <Frame who={who} />
    </QueryClientProvider>,
  );
  return { ...view, calls: mocked.calls, client };
}

describe("useAskAhead", () => {
  it("asks for the page of a link the pointer comes to, the focus reaches or a finger touches", async () => {
    const { getByText, calls } = draw(me({ role: "hr" }));
    fireEvent.pointerOver(getByText("leave"));
    await waitFor(() => expect(calls.map((call) => call.url)).toEqual(["/api/v1/hr/leave/"]));
    fireEvent.focusIn(getByText("leave"));
    fireEvent.touchStart(getByText("leave"));
    // Asked once: the second and third find it on its way.
    expect(calls).toHaveLength(1);
  });

  it("asks nothing for a client's link, a link to another site, or before it knows who the person is", async () => {
    const known = draw(me({ role: "hr" }));
    fireEvent.pointerOver(known.getByText("a client"));
    fireEvent.pointerOver(known.getByText("elsewhere"));
    fireEvent.pointerOver(known.container);
    expect(known.calls).toEqual([]);
    known.unmount();

    const unknown = draw(undefined);
    fireEvent.pointerOver(unknown.getByText("leave"));
    expect(unknown.calls).toEqual([]);
  });

  it("stops listening when the page is gone", () => {
    const { getByText, calls, unmount } = draw(me({ role: "hr" }));
    const link = getByText("leave");
    unmount();
    fireEvent.pointerOver(link);
    expect(calls).toEqual([]);
  });

  it("asks again, behind the page, when it was opened on an answer that had time to go stale", () => {
    vi.useFakeTimers();
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue(undefined);
    draw(me({ role: "hr" }), client);
    window.dispatchEvent(new Event(AHEAD_AGED_EVENT));
    window.dispatchEvent(new Event(AHEAD_AGED_EVENT));
    vi.advanceTimersByTime(500);
    // Two bells close together are one ask.
    expect(invalidate).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });
});
