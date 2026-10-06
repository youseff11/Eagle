import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { entry, renderChats, row, visible, file } from "../../test/chat";
import { jsonResponse, mockFetch, renderWithProviders } from "../../test/helpers";
import { Bubble, type FileMark } from "./Bubble";
import { DocumentPreview } from "./DocumentPreview";
import { viewerKind } from "./FileViewer";

const pdf = vi.hoisted(() => ({ getDocument: vi.fn(), getPage: vi.fn(), render: vi.fn(), destroy: vi.fn() }));
vi.mock("pdfjs-dist", () => ({ getDocument: pdf.getDocument, GlobalWorkerOptions: {} }));

beforeEach(() => {
  vi.clearAllMocks();
  visible("visible");
  pdf.destroy.mockResolvedValue(undefined);
  pdf.render.mockReturnValue({ promise: Promise.resolve() });
  pdf.getPage.mockResolvedValue({ getViewport: ({ scale }: { scale: number }) => ({ width: 600 * scale, height: 800 * scale }), render: pdf.render });
  pdf.getDocument.mockReturnValue({ promise: Promise.resolve({ numPages: 3, getPage: pdf.getPage }), destroy: pdf.destroy });
});
afterEach(() => vi.unstubAllGlobals());

const word = file({ name: "contract.docx", url: "/files/in/contract.docx", mime: "application/octet-stream", size: 2048 });

/** A Word file's two helpers: the first words for the card, and the whole text for the viewer. */
function serveWord(full: unknown = { ok: true, text: "First line\nWhole text of the contract", truncated: false }) {
  const mocked = mockFetch({
    "/files/": (url) =>
      url.searchParams.get("preview") === "full" ? jsonResponse(full) : jsonResponse({ ok: true, text: "First line", thumb: false }),
  });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked;
}

function card(over = {}, viewer?: boolean) {
  const given = file({ ...word, ...over });
  return renderWithProviders(<DocumentPreview file={given} url={given.url} viewer={viewer} />);
}

describe("what kind of file is shown inside the page", () => {
  it("tells a PDF, a Word file, a text file and a video from the rest, by the name or the type", () => {
    expect(viewerKind({ name: "a.PDF", mime: "" })).toBe("pdf");
    expect(viewerKind({ name: "scan", mime: "application/pdf; charset=binary" })).toBe("pdf");
    expect(viewerKind({ name: "a.docx", mime: "application/octet-stream" })).toBe("word");
    expect(viewerKind({ name: "a.dotx", mime: "" })).toBe("word");
    expect(viewerKind({ name: "a.txt", mime: "" })).toBe("text");
    expect(viewerKind({ name: "clip", mime: "video/mp4" })).toBe("video");
    expect(viewerKind({ name: "a.zip", mime: "application/zip" })).toBe("other");
    // A Word file whose type says PDF is still read as Word: the extension decides first.
    expect(viewerKind({ name: "a.docx", mime: "application/pdf" })).toBe("word");
  });
});

describe("opening a file over the chat", () => {
  it("opens a Word file's whole text without leaving the page, with a button that saves it", async () => {
    const user = userEvent.setup();
    const mocked = serveWord();
    card();
    await user.click(await screen.findByRole("link", { name: "contract.docx" }));
    const dialog = await screen.findByRole("dialog", { name: "contract.docx" });
    expect(await within(dialog).findByText(/Whole text of the contract/)).toBeInTheDocument();
    expect(mocked.calls.some((call) => call.url === "/files/in/contract.docx?preview=full")).toBe(true);
    const save = within(dialog).getByRole("link", { name: "تنزيل" });
    expect(save).toHaveAttribute("href", "/files/in/contract.docx?dl=1");
    expect(save).toHaveAttribute("download", "contract.docx");
    // Nothing was fetched as a download by opening it.
    expect(mocked.calls.some((call) => call.url.includes("dl=1"))).toBe(false);
  });

  it("closes with Escape, the cross and the dark ground", async () => {
    const user = userEvent.setup();
    serveWord();
    card();
    const open = async () => user.click(await screen.findByRole("link", { name: "contract.docx" }));
    await open();
    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    await open();
    await user.click(screen.getByRole("button", { name: "إغلاق" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await open();
    fireEvent.mouseDown(screen.getByRole("dialog"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("says a long Word file is cut and offers the download for the rest", async () => {
    const user = userEvent.setup();
    serveWord({ ok: true, text: "Start of a long file", truncated: true });
    card();
    await user.click(await screen.findByRole("link", { name: "contract.docx" }));
    expect(await screen.findByText(/نزّله عشان تشوفه كله/)).toBeInTheDocument();
  });

  it("draws the text as text, never as markup", async () => {
    const user = userEvent.setup();
    serveWord({ ok: true, text: '<img src=x onerror="alert(1)">', truncated: false });
    card();
    await user.click(await screen.findByRole("link", { name: "contract.docx" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText('<img src=x onerror="alert(1)">')).toBeInTheDocument();
    expect(dialog.querySelector("img")).toBeNull();
  });

  it("says so, and keeps the download, when the Word file cannot be read", async () => {
    const user = userEvent.setup();
    serveWord({ ok: true, text: "", truncated: false });
    card();
    await user.click(await screen.findByRole("link", { name: "contract.docx" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(/مش قادرين نعرض الملف ده هنا/)).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "تنزيل" })).toHaveAttribute("href", "/files/in/contract.docx?dl=1");
  });

  it("draws every page of a PDF, one under the other, from the protected address", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockFetch({}).fn);
    card({ name: "report.pdf", url: "/files/in/report.pdf", mime: "application/pdf" });
    await user.click(screen.getByRole("link", { name: "report.pdf" }));
    const dialog = await screen.findByRole("dialog", { name: "report.pdf" });
    await waitFor(() => expect(dialog.querySelectorAll("canvas.fileviewer__page")).toHaveLength(3));
    expect(pdf.getDocument).toHaveBeenCalledWith(expect.objectContaining({ url: "/files/in/report.pdf", withCredentials: true }));
    expect(within(dialog).getByRole("link", { name: "تنزيل" })).toHaveAttribute("href", "/files/in/report.pdf?dl=1");
    await user.keyboard("{Escape}");
    expect(pdf.destroy).toHaveBeenCalled();
  });

  it("falls back to the download when a PDF cannot be drawn", async () => {
    const user = userEvent.setup();
    pdf.getDocument.mockReturnValue({ promise: Promise.reject(new Error("Password required")), destroy: pdf.destroy });
    vi.stubGlobal("fetch", mockFetch({}).fn);
    card({ name: "report.pdf", url: "/files/in/report.pdf", mime: "application/pdf" });
    await user.click(screen.getByRole("link", { name: "report.pdf" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(/مش قادرين نعرض الملف ده هنا/)).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "تنزيل" })).toBeInTheDocument();
  });

  it("shows a text file's words and a video's player", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockFetch({ "/files/in/notes.txt": () => new Response("plain notes", { status: 200 }) }).fn);
    const first = card({ name: "notes.txt", url: "/files/in/notes.txt", mime: "text/plain" });
    await user.click(screen.getByRole("link", { name: "notes.txt" }));
    expect(await screen.findByText("plain notes")).toBeInTheDocument();
    first.unmount();

    vi.stubGlobal("fetch", mockFetch({}).fn);
    card({ name: "clip.mp4", url: "/files/in/clip.mp4", mime: "video/mp4" });
    await user.click(screen.getByRole("link", { name: "clip.mp4" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.querySelector("video")).toHaveAttribute("src", "/files/in/clip.mp4");
  });

  it("offers only the download for a type the page cannot show", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockFetch({}).fn);
    card({ name: "archive.zip", url: "/files/in/archive.zip", mime: "application/zip" });
    await user.click(screen.getByRole("link", { name: "archive.zip" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/مش قادرين نعرض الملف ده هنا/)).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "تنزيل" })).toHaveAttribute("href", "/files/in/archive.zip?dl=1");
  });

  it("opens nothing while files are being picked, or on a press that asks for a new tab", async () => {
    vi.stubGlobal("fetch", mockFetch({}).fn);
    const picking = card({ name: "archive.zip", url: "/files/in/archive.zip", mime: "application/zip" }, false);
    fireEvent.click(screen.getByRole("link", { name: "archive.zip" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    picking.unmount();

    card({ name: "archive.zip", url: "/files/in/archive.zip", mime: "application/zip" });
    for (const modifier of [{ ctrlKey: true }, { metaKey: true }, { shiftKey: true }, { button: 1 }]) {
      fireEvent.click(screen.getByRole("link", { name: "archive.zip" }), modifier);
      expect(screen.queryByRole("dialog")).toBeNull();
    }
  });

  it("keeps the real address on the card, for a new tab", () => {
    vi.stubGlobal("fetch", mockFetch({}).fn);
    card({ name: "archive.zip", url: "/files/in/archive.zip", mime: "application/zip" });
    const link = screen.getByRole("link", { name: "archive.zip" });
    expect(link).toHaveAttribute("href", "/files/in/archive.zip");
    expect(link).toHaveAttribute("target", "_blank");
  });
});

describe("a photo in the chat", () => {
  function thread() {
    return renderChats("/chats/CL-0001", {
      thread: { client: row("CL-0001"), messages: [entry(1, { files: [file({ id: 4, name: "photo.jpg", url: "/files/in/photo.jpg", image: true, mime: "image/jpeg" })] })] },
    });
  }

  it("opens over the chat with a button that saves it, instead of leaving for a new tab", async () => {
    const user = userEvent.setup();
    thread();
    await screen.findByText("message 1");
    await user.click(document.querySelector("a.bub__img")!);
    const dialog = screen.getByRole("dialog", { name: "الصور" });
    expect(dialog.querySelector(".lightbox__img")).toHaveAttribute("src", "/files/in/photo.jpg");
    const save = within(dialog).getByRole("link", { name: "تنزيل" });
    expect(save).toHaveAttribute("href", "/files/in/photo.jpg?dl=1");
    expect(save).toHaveAttribute("download", "photo.jpg");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("keeps the address for a press that asks for a new tab", async () => {
    thread();
    await screen.findByText("message 1");
    const link = document.querySelector("a.bub__img")!;
    expect(link).toHaveAttribute("href", "/files/in/photo.jpg");
    fireEvent.click(link, { ctrlKey: true });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("while files are being picked", () => {
  it("a press on a photo or a document ticks it and opens nothing", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockFetch({}).fn);
    const toggle = vi.fn();
    const mark: FileMark = { mode: "pick", active: true, show: () => true, ticked: () => false, toggle };
    const files = [
      file({ id: 4, name: "photo.jpg", url: "/files/in/photo.jpg", image: true, mime: "image/jpeg" }),
      file({ id: 5, name: "archive.zip", url: "/files/in/archive.zip", mime: "application/zip" }),
    ];
    renderWithProviders(<Bubble entry={entry(1, { files })} fileMark={mark} />);
    await user.click(document.querySelector("a.bub__img")!);
    await user.click(screen.getByRole("link", { name: "archive.zip" }));
    expect(toggle).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
