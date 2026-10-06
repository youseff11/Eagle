import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../test/helpers";
import PdfPreview from "./PdfPreview";

const pdf = vi.hoisted(() => ({ getDocument: vi.fn(), getPage: vi.fn(), render: vi.fn(), destroy: vi.fn() }));
vi.mock("pdfjs-dist", () => ({ getDocument: pdf.getDocument, GlobalWorkerOptions: {} }));

beforeEach(() => {
  vi.clearAllMocks();
  pdf.destroy.mockResolvedValue(undefined);
  pdf.render.mockReturnValue({ promise: Promise.resolve() });
  pdf.getPage.mockResolvedValue({ getViewport: ({ scale }: { scale: number }) => ({ width: 600 * scale, height: 800 * scale }), render: pdf.render });
  pdf.getDocument.mockReturnValue({ promise: Promise.resolve({ getPage: pdf.getPage }), destroy: pdf.destroy });
});

describe("PDF first-page preview", () => {
  it("draws the first page from the protected URL, then frees the document", async () => {
    renderWithProviders(<PdfPreview url="/files/in/report.pdf" name="report.pdf" />);
    const canvas = await screen.findByRole("img", { name: "معاينة: report.pdf" });
    expect(canvas).toBeVisible();
    expect(pdf.getDocument).toHaveBeenCalledWith(expect.objectContaining({ url: "/files/in/report.pdf", withCredentials: true }));
    expect(pdf.getPage).toHaveBeenCalledWith(1);
    expect(pdf.render).toHaveBeenCalledWith(expect.objectContaining({ canvas }));
    await waitFor(() => expect(pdf.destroy).toHaveBeenCalled());
  });

  it("shows a fallback for broken or protected PDFs", async () => {
    pdf.getDocument.mockReturnValue({ promise: Promise.reject(new Error("Password required")), destroy: pdf.destroy });
    renderWithProviders(<PdfPreview url="/files/in/report.pdf" name="report.pdf" />);
    expect(await screen.findByText("المعاينة غير متاحة")).toBeInTheDocument();
    expect(pdf.render).not.toHaveBeenCalled();
  });

  it("cancels pending work when the chat is closed", async () => {
    pdf.getDocument.mockReturnValue({ promise: new Promise(() => {}), destroy: pdf.destroy });
    const view = renderWithProviders(<PdfPreview url="/files/in/report.pdf" name="report.pdf" />);
    await waitFor(() => expect(pdf.getDocument).toHaveBeenCalled());
    view.unmount();
    expect(pdf.destroy).toHaveBeenCalled();
  });
});
