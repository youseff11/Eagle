import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { file } from "../../test/chat";
import { mockFetch, renderWithProviders } from "../../test/helpers";
import { DocumentPreview } from "./DocumentPreview";

afterEach(() => vi.unstubAllGlobals());

function card(over = {}, viewer?: boolean) {
  const fetched = mockFetch({});
  vi.stubGlobal("fetch", fetched.fn);
  const given = file(over);
  const view = renderWithProviders(<DocumentPreview file={given} url={given.url} viewer={viewer} />);
  return { ...view, calls: fetched.calls };
}

describe("a file as a card in the chat", () => {
  it("shows a PDF as a red PDF badge with its name, type and size - nothing of what is inside", () => {
    const { container, calls } = card({ name: "Graduation_Project.pdf", url: "/files/in/p.pdf", mime: "application/pdf", size: 2 * 1024 * 1024 });
    const link = screen.getByRole("link", { name: "Graduation_Project.pdf" });
    expect(link).toHaveAttribute("href", "/files/in/p.pdf");
    expect(container.querySelector(".document-card__badge--pdf")).toHaveTextContent("PDF");
    expect(screen.getByText("Graduation_Project.pdf")).toHaveClass("document-card__name");
    expect(screen.getByText(/PDF · 2/)).toBeInTheDocument();
    // No picture of the page, no text of the file, and nothing is fetched to draw the card.
    expect(container.querySelector("canvas, img, .document-card__paper")).toBeNull();
    expect(calls).toHaveLength(0);
  });

  it("shows a Word file as a blue Word badge, by the extension and whatever type the server says", () => {
    const { container, calls } = card({ name: "contract.docx", url: "/files/in/c.docx", mime: "application/octet-stream", size: 2048 });
    expect(container.querySelector(".document-card__badge--word")).toHaveTextContent("DOC");
    expect(screen.getByText(/DOCX · 2/)).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("shows any other file with a grey badge that says its extension", () => {
    const { container } = card({ name: "archive.zip", url: "/files/in/a.zip", mime: "application/zip", size: 10 });
    expect(container.querySelector(".document-card__badge--other")).toHaveTextContent("ZIP");
  });

  it("shows a file with no extension and no size as a plain file", () => {
    const { container } = card({ name: "noextension", url: "/files/in/n", mime: "", size: 0 });
    expect(container.querySelector(".document-card__badge--other")).toBeInTheDocument();
    expect(screen.getByText("ملف")).toBeInTheDocument();
  });

  it("draws a file name as text, never as markup", () => {
    const { container } = card({ name: '<img src=x onerror="alert(1)">.pdf', url: "/files/in/x.pdf", mime: "application/pdf" });
    expect(screen.getByText('<img src=x onerror="alert(1)">.pdf')).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("opens the file over the chat on a press, and keeps the real address for a new tab", () => {
    card({ name: "a.zip", url: "/files/in/a.zip", mime: "application/zip" });
    const link = screen.getByRole("link", { name: "a.zip" });
    expect(link).toHaveAttribute("target", "_blank");
    fireEvent.click(link, { ctrlKey: true });
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(link);
    expect(screen.getByRole("dialog", { name: "a.zip" })).toBeInTheDocument();
  });

  it("opens nothing while files are being picked", () => {
    card({ name: "a.zip", url: "/files/in/a.zip", mime: "application/zip" }, false);
    fireEvent.click(screen.getByRole("link", { name: "a.zip" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
