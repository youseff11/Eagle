/**
 * The photos this browser has just sent, kept so that they are not fetched back.
 *
 * A photo that is on its way is drawn from the file in the person's own hands (an object URL). When the server has it,
 * the bubble is replaced by the real one, whose picture is an address on the server: a moment of nothing while it
 * loads, and a bubble that changes size. So the object URL is remembered against the address the server gave the
 * photo, and the real bubble draws that - the same pixels, already there. Only what is drawn: opening a photo, saving it
 * and every link still use the server's address.
 *
 * It is small on purpose: the newest few photos, the older ones are let go (an object URL holds the whole file).
 */

const KEPT = 40;
const photos = new Map<string, string>();

/** Whether the browser can make an object URL at all (a test environment may not). */
function canPreview(): boolean {
  return typeof URL !== "undefined" && typeof URL.createObjectURL === "function";
}

/** An object URL to draw this file from while it is on its way: a photo or a sound; `""` for anything else. */
export function previewOf(file: Blob & { name?: string }): string {
  if (!canPreview()) return "";
  const type = file.type.toLowerCase();
  const name = (file.name ?? "").toLowerCase();
  if (type === "image/svg+xml" || name.endsWith(".svg")) return "";
  if (!type.startsWith("image/") && !type.startsWith("audio/")) return "";
  try {
    return URL.createObjectURL(file);
  } catch {
    return "";
  }
}

/** Let an object URL go (the file it held is no longer needed). */
export function release(preview: string): void {
  if (preview === "" || !canPreview() || typeof URL.revokeObjectURL !== "function") return;
  try {
    URL.revokeObjectURL(preview);
  } catch {
    // Already gone.
  }
}

/** Does the keeper hold this object URL (so that nobody else lets it go)? */
export function isKept(preview: string): boolean {
  for (const held of photos.values()) if (held === preview) return true;
  return false;
}

/** Remember that the server's `address` is the photo `preview` shows. The oldest are let go past the limit. */
export function keep(address: string, preview: string): void {
  if (address === "" || preview === "") return;
  const had = photos.get(address);
  if (had === preview) return;
  photos.delete(address);
  photos.set(address, preview);
  if (had !== undefined && !isKept(had)) release(had);
  while (photos.size > KEPT) {
    const oldest = photos.keys().next().value as string;
    const gone = photos.get(oldest) ?? "";
    photos.delete(oldest);
    if (!isKept(gone)) release(gone);
  }
}

/** What to draw a photo from: the copy already here when there is one, else the server's address. */
export function localSrc(address: string): string {
  return photos.get(address) ?? address;
}

/** Forget everything (a test starts from nothing). */
export function forgetPhotos(): void {
  for (const preview of new Set(photos.values())) release(preview);
  photos.clear();
}
