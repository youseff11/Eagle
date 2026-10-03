/** Saving a file the browser already holds. A seam so a test can watch it (jsdom has nowhere to save to). */
export const download = {
  save(blob: Blob, filename: string): void {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    // The click starts the save; the address can go a moment later.
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
};
