import { afterEach, describe, expect, it, vi } from "vitest";
import { AVATAR_PICK_BYTES, AVATAR_SIDE, NotAPicture, middleSquare, squareAvatar } from "./avatarImage";

afterEach(() => vi.unstubAllGlobals());

describe("middleSquare", () => {
  it("cuts the middle of a wide picture, and of a tall one", () => {
    expect(middleSquare(400, 200)).toEqual({ x: 100, y: 0, side: 200 });
    expect(middleSquare(200, 400)).toEqual({ x: 0, y: 100, side: 200 });
  });

  it("keeps a square whole", () => {
    expect(middleSquare(300, 300)).toEqual({ x: 0, y: 0, side: 300 });
  });

  it("never asks for a half pixel", () => {
    expect(middleSquare(301, 200)).toEqual({ x: 50, y: 0, side: 200 });
  });
});

describe("squareAvatar", () => {
  it("refuses what is not an image, and what is too big to be a photo, before reading it", async () => {
    const decode = vi.fn();
    vi.stubGlobal("createImageBitmap", decode);
    await expect(squareAvatar(new File(["x"], "cv.pdf", { type: "application/pdf" }))).rejects.toBeInstanceOf(NotAPicture);
    const huge = new File(["x"], "big.png", { type: "image/png" });
    Object.defineProperty(huge, "size", { value: AVATAR_PICK_BYTES + 1 });
    await expect(squareAvatar(huge)).rejects.toBeInstanceOf(NotAPicture);
    expect(decode).not.toHaveBeenCalled();
  });

  it("refuses an image the browser cannot decode", async () => {
    vi.stubGlobal("createImageBitmap", () => Promise.reject(new Error("broken")));
    await expect(squareAvatar(new File(["x"], "x.png", { type: "image/png" }))).rejects.toBeInstanceOf(NotAPicture);
  });

  it("draws the middle square, on white, down to the side the server is sent, as a JPEG", async () => {
    const bitmap = { width: 1000, height: 600, close: vi.fn() };
    vi.stubGlobal("createImageBitmap", async () => bitmap);
    const draws: number[][] = [];
    const fills: unknown[][] = [];
    const context = {
      fillStyle: "",
      fillRect: (...args: unknown[]) => fills.push([context.fillStyle, ...args]),
      drawImage: (_image: unknown, ...args: number[]) => draws.push(args),
    };
    const canvas = {
      width: 0,
      height: 0,
      getContext: () => context,
      toBlob: (done: (blob: Blob | null) => void, type: string, quality: number) => {
        expect([type, quality]).toEqual(["image/jpeg", 0.88]);
        done(new Blob(["jpeg bytes"], { type }));
      },
    };
    const create = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation(((tag: string) => (tag === "canvas" ? canvas : create(tag))) as typeof document.createElement);

    const out = await squareAvatar(new File(["x"], "holiday.png", { type: "image/png" }));

    expect([canvas.width, canvas.height]).toEqual([AVATAR_SIDE, AVATAR_SIDE]);
    expect(fills).toEqual([["#fff", 0, 0, AVATAR_SIDE, AVATAR_SIDE]]);
    // From the middle (x = 200 of 1000), a 600-pixel square, into the whole of the canvas.
    expect(draws).toEqual([[200, 0, 600, 600, 0, 0, AVATAR_SIDE, AVATAR_SIDE]]);
    expect(out.type).toBe("image/jpeg");
    expect(out.name).toBe("avatar.jpg");
    expect(bitmap.close).toHaveBeenCalled();
    vi.restoreAllMocks();
  });

  it("does not blow a small picture up past what it has", async () => {
    vi.stubGlobal("createImageBitmap", async () => ({ width: 100, height: 80, close: vi.fn() }));
    const canvas = {
      width: 0,
      height: 0,
      getContext: () => ({ fillStyle: "", fillRect: () => undefined, drawImage: () => undefined }),
      toBlob: (done: (blob: Blob | null) => void) => done(new Blob(["x"])),
    };
    const create = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation(((tag: string) => (tag === "canvas" ? canvas : create(tag))) as typeof document.createElement);
    await squareAvatar(new File(["x"], "small.png", { type: "image/png" }));
    expect([canvas.width, canvas.height]).toEqual([80, 80]);
    vi.restoreAllMocks();
  });

  it("refuses when the browser gives back no bytes", async () => {
    vi.stubGlobal("createImageBitmap", async () => ({ width: 50, height: 50, close: vi.fn() }));
    const canvas = {
      width: 0,
      height: 0,
      getContext: () => ({ fillStyle: "", fillRect: () => undefined, drawImage: () => undefined }),
      toBlob: (done: (blob: Blob | null) => void) => done(null),
    };
    const create = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation(((tag: string) => (tag === "canvas" ? canvas : create(tag))) as typeof document.createElement);
    await expect(squareAvatar(new File(["x"], "x.png", { type: "image/png" }))).rejects.toBeInstanceOf(NotAPicture);
    vi.restoreAllMocks();
  });
});
