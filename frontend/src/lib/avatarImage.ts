/** The side of the square that is sent: a face in a 28-pixel box and a 64-pixel one, with room to be sharp on a dense screen. */
export const AVATAR_SIDE = 256;

/** The biggest file the page takes to read (the server's own ceiling is far lower once it is cut down). */
export const AVATAR_PICK_BYTES = 25 * 1024 * 1024;

/** The file could not be read as a picture (not an image, or one the browser cannot decode). */
export class NotAPicture extends Error {}

/** The middle square of a `width` by `height` picture: where to cut so a face is not squeezed. */
export function middleSquare(width: number, height: number): { x: number; y: number; side: number } {
  const side = Math.min(width, height);
  return { x: Math.floor((width - side) / 2), y: Math.floor((height - side) / 2), side };
}

/**
 * A picked file as the square JPEG that is sent: cut from the middle, brought down to `AVATAR_SIDE`, on white (a PNG with
 * nothing behind it would be black as a JPEG). Drawing it again is also what drops everything else a photo carries (where it
 * was taken, which phone): only the pixels are sent.
 */
export async function squareAvatar(file: File): Promise<File> {
  if (!file.type.startsWith("image/") || file.size > AVATAR_PICK_BYTES) throw new NotAPicture();
  let bitmap: ImageBitmap;
  try {
    // "from-image": a photo taken sideways is turned the way it was meant to be looked at.
    bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    throw new NotAPicture();
  }
  try {
    const { x, y, side } = middleSquare(bitmap.width, bitmap.height);
    const size = Math.min(AVATAR_SIDE, side);
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;
    const context = canvas.getContext("2d");
    if (!context) throw new NotAPicture();
    context.fillStyle = "#fff";
    context.fillRect(0, 0, size, size);
    context.drawImage(bitmap, x, y, side, side, 0, 0, size, size);
    const blob = await new Promise<Blob | null>((done) => canvas.toBlob(done, "image/jpeg", 0.88));
    if (!blob) throw new NotAPicture();
    return new File([blob], "avatar.jpg", { type: "image/jpeg" });
  } finally {
    bitmap.close();
  }
}
