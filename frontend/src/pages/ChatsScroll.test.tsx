import { act, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { qk } from "../api/keys";
import { entry, renderChats, row } from "../test/chat";
import { jsonResponse } from "../test/helpers";

let height = 1800;
const observers = new Set<{ resize: () => void; targets: Set<Element> }>();

beforeEach(() => {
  height = 1800;
  vi.spyOn(Element.prototype, "scrollHeight", "get").mockImplementation(() => height);
  vi.spyOn(Element.prototype, "clientHeight", "get").mockReturnValue(500);
  vi.stubGlobal("ResizeObserver", class {
    targets = new Set<Element>();
    resize: () => void;
    constructor(callback: ResizeObserverCallback) {
      this.resize = () => callback([], this as unknown as ResizeObserver);
      observers.add(this);
    }
    observe(target: Element) { this.targets.add(target); }
    disconnect() { observers.delete(this); }
  });
});

afterEach(() => {
  observers.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function resize(target: Element) {
  act(() => {
    for (const observer of observers) {
      if (observer.targets.has(target)) observer.resize();
    }
  });
}

describe("opening and scrolling a chat", () => {
  it.each(["CL-0001", "u5", "g1"])("opens %s at the latest message", async (code) => {
    const { container } = renderChats(`/chats/${code}`, {
      thread: { client: row(code), messages: [entry(1), entry(2)] },
    });
    await screen.findByText("message 2");
    expect(container.querySelector(".cchat__stream")!.scrollTop).toBe(height);
  });

  it("stays at the end as media and the viewport resize, but leaves someone reading older messages in place", async () => {
    const { container, client } = renderChats("/chats/CL-0001", {
      thread: { client: row("CL-0001"), messages: [entry(1), entry(2)] },
    });
    await screen.findByText("message 2");
    const stream = container.querySelector(".cchat__stream")!;
    const message = stream.querySelector(".chat-entry")!;
    height = 2400;
    resize(message);
    expect(stream.scrollTop).toBe(2400);
    stream.scrollTop = 2200;
    resize(stream);
    expect(stream.scrollTop).toBe(2400);

    stream.scrollTop = 200;
    fireEvent.scroll(stream);
    height = 3000;
    resize(message);
    expect(stream.scrollTop).toBe(200);
    act(() => client.setQueryData(qk.thread("CL-0001"), {
      ok: true, client: row("CL-0001"), messages: [entry(1), entry(2), entry(3)],
    }));
    expect(await screen.findByText("message 3")).toBeInTheDocument();
    expect(stream.scrollTop).toBe(200);

    stream.scrollTop = height - 500;
    fireEvent.scroll(stream);
    height = 3400;
    resize(message);
    expect(stream.scrollTop).toBe(3400);
  });

  it("opens the next conversation at its end after scrolling up in the first", async () => {
    const { container } = renderChats("/chats/CL-0001", {
      lists: { clients: [row("CL-0001"), row("CL-0002")] },
    }, {
      "/api/v1/clients/": (url) => jsonResponse({
        ok: true,
        client: row(url.pathname.includes("CL-0002") ? "CL-0002" : "CL-0001"),
        messages: [entry(url.pathname.includes("CL-0002") ? 2 : 1)],
      }),
    });
    await screen.findByText("message 1");
    const first = container.querySelector(".cchat__stream")!;
    first.scrollTop = 100;
    fireEvent.scroll(first);
    await userEvent.click(container.querySelector('a[href="/chats/CL-0002?type=clients"]')!);
    await screen.findByText("message 2");
    expect(container.querySelector(".cchat__stream")!.scrollTop).toBe(height);
    expect([...observers].some((observer) => observer.targets.has(first))).toBe(false);
  });
});
