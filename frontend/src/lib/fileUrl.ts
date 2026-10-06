/** The same protected file address, with one query word changed: what the server does with it (`views.serve_file`). */
function withQuery(url: string, name: string, value: string): string {
  const parsed = new URL(url, window.location.origin);
  parsed.searchParams.set(name, value);
  parsed.hash = "";
  return parsed.pathname + parsed.search;
}

/** The address that saves the file instead of showing it: the button beside every viewer. */
export function downloadUrl(url: string): string {
  return withQuery(url, "dl", "1");
}

/** The address of a helper the server makes of a file: `1` (a Word file's first words), `thumb`, or `full` (all its text). */
export function previewUrl(url: string, mode: string): string {
  return withQuery(url, "preview", mode);
}
