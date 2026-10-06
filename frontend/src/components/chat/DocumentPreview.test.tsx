import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { file } from "../../test/chat";
import { jsonResponse, mockFetch, renderWithProviders } from "../../test/helpers";
import { DocumentPreview } from "./DocumentPreview";

afterEach(() => vi.unstubAllGlobals());

function renderWord(answer: unknown = { ok: true, text: "Certificate\nDocument contents", thumb: false }, status = 200) {
  const mocked = mockFetch({ "/files/": () => jsonResponse(answer, status) });
  vi.stubGlobal("fetch", mocked.fn);
  const view = renderWithProviders(<DocumentPreview
    file={file({ name: "contract.pdf (193).docx", url: "/files/in/document.docx", mime: "application/octet-stream" })}
    url="/files/in/document.docx"
  />);
  return { ...view, calls: mocked.calls };
}

describe("document preview cards", () => {
  it("shows the opening text of a Word document as a page and keeps the original download", async () => {
    const { calls } = renderWord();
    expect(await screen.findByText(/Certificate.*Document contents/s)).toHaveClass("document-card__paper");
    expect(screen.getByRole("link", { name: "contract.pdf (193).docx" })).toHaveAttribute("href", "/files/in/document.docx");
    expect(screen.getByText(/DOCX/)).toBeInTheDocument();
    expect(calls.map((call) => call.url)).toEqual(["/files/in/document.docx?preview=1"]);
  });

  it("uses the embedded Word thumbnail and falls back to its text if the image fails", async () => {
    renderWord({ ok: true, text: "Opening paragraph", thumb: true });
    const picture = await screen.findByRole("img", { name: "معاينة: contract.pdf (193).docx" });
    expect(picture).toHaveAttribute("src", "/files/in/document.docx?preview=thumb");
    fireEvent.error(picture);
    expect(screen.getByText("Opening paragraph")).toBeInTheDocument();
  });

  it("leaves a usable file card when preview access fails", async () => {
    renderWord({ ok: false, error: "not_found" }, 404);
    expect(await screen.findByText("المعاينة غير متاحة")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "contract.pdf (193).docx" })).toHaveAttribute("href", "/files/in/document.docx");
  });

  it("renders document contents as text without running markup", async () => {
    const { container } = renderWord({ ok: true, text: '<img src=x onerror="alert(1)">', thumb: false });
    expect(await screen.findByText('<img src=x onerror="alert(1)">')).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("waits until the file card is near the visible messages before fetching its preview", async () => {
    let reveal = () => {};
    const disconnect = vi.fn();
    vi.stubGlobal("IntersectionObserver", class {
      constructor(callback: IntersectionObserverCallback) {
        reveal = () => callback([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver);
      }
      observe() {}
      disconnect = disconnect;
    });
    const { calls } = renderWord();
    expect(calls).toHaveLength(0);
    act(() => reveal());
    await screen.findByText(/Certificate/);
    expect(calls).toHaveLength(1);
    expect(disconnect).toHaveBeenCalled();
  });

  it("shows a fallback card for unsupported documents without fetching them", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    renderWithProviders(<DocumentPreview file={file({ name: "archive.zip" })} url="/files/in/archive.zip" />);
    await waitFor(() => expect(screen.getByText("المعاينة غير متاحة")).toBeInTheDocument());
    expect(fetch).not.toHaveBeenCalled();
  });
});
