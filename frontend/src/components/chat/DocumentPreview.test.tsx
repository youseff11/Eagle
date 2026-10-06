import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { entry, file, renderChats, row, visible } from "../../test/chat";
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
    expect(link).toHaveAttribute("href", "/files/in/p.pdf?dl=1");
    expect(container.querySelector(".document-card__badge--pdf")).toHaveTextContent("PDF");
    expect(screen.getByText("Graduation_Project.pdf")).toHaveClass("document-card__name");
    expect(screen.getByText(/PDF · 2/)).toBeInTheDocument();
    // No picture of the page, no text of the file, and nothing is fetched to draw the card.
    expect(container.querySelector("canvas, img, .document-card__paper")).toBeNull();
    expect(calls).toHaveLength(0);
  });

  it("writes the task's code on the card when the file belongs to a task, and nothing when it does not", () => {
    const first = renderWithProviders(<DocumentPreview file={file({ name: "a.pdf", url: "/files/in/a.pdf" })} url="/files/in/a.pdf" task="TSK-00004" />);
    expect(first.container.querySelector(".document-card__task")).toHaveTextContent("TSK-00004");
    first.unmount();
    const second = renderWithProviders(<DocumentPreview file={file({ name: "a.pdf", url: "/files/in/a.pdf" })} url="/files/in/a.pdf" />);
    expect(second.container.querySelector(".document-card__task")).toBeNull();
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

  it("saves the file at once on a press, with no preview", () => {
    card({ name: "a.zip", url: "/files/in/a.zip", mime: "application/zip" });
    const link = screen.getByRole("link", { name: "a.zip" });
    expect(link).toHaveAttribute("href", "/files/in/a.zip?dl=1");
    expect(link).toHaveAttribute("download", "a.zip");
    fireEvent.click(link);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("saves nothing while files are being picked", () => {
    card({ name: "a.zip", url: "/files/in/a.zip", mime: "application/zip" }, false);
    const allowed = fireEvent.click(screen.getByRole("link", { name: "a.zip" }));
    expect(allowed).toBe(false);
  });
});

describe("the task's code on a file in the chat", () => {
  it("is the code of the task the message was tagged with", async () => {
    visible("visible");
    renderChats("/chats/CL-0001", {
      thread: {
        client: row("CL-0001"),
        messages: [
          entry(1, { task_code: "TSK-00004", files: [file({ id: 1, name: "translation.pdf", url: "/files/in/t.pdf" })] }),
          entry(2, { task_code: "", files: [file({ id: 2, name: "other.pdf", url: "/files/in/o.pdf" })] }),
        ],
      },
    });
    await screen.findByText("message 1");
    const cards = Array.from(document.querySelectorAll(".document-card"));
    expect(cards[0]!.querySelector(".document-card__task")).toHaveTextContent("TSK-00004");
    expect(cards[1]!.querySelector(".document-card__task")).toBeNull();
  });
});
