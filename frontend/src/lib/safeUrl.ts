/**
 * A link from the server, made safe to put in an `href`.
 *
 * Notifications carry a `url` the server wrote. It is meant to be a path on this
 * site, and it is rendered as a link, so anything else - another site, a
 * `javascript:` address, a protocol-relative `//host`, a backslash that some
 * browsers read as a slash - is refused. Returns the path (with query and
 * hash), or `null`.
 */
export function safeInternalPath(raw: string, origin: string = window.location.origin): string | null {
  if (!raw || /[\u0000-\u001f\\]/.test(raw)) return null;
  if (!raw.startsWith("/") || raw.startsWith("//")) return null;
  try {
    const url = new URL(raw, origin);
    if (url.origin !== origin) return null;
    const path = url.pathname + url.search + url.hash;
    // Dot-segments collapse while the address is parsed: "/.//evil.example" comes
    // out as "//evil.example", which a browser reads as another site. So the
    // result is checked as well as the input.
    if (path.startsWith("//") || path.startsWith("/\\")) return null;
    return path;
  } catch {
    return null;
  }
}
