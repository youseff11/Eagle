import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { entry, renderChats as render, row, visible, file } from "../test/chat";

beforeEach(() => visible("visible"));
afterEach(() => {
  vi.unstubAllGlobals();
  visible("visible");
});

const photo = (n: number) => file({ id: n, name: `p${n}.jpg`, url: `/files/in/p${n}.jpg`, image: true });

function thread(files: ReturnType<typeof file>[]) {
  return render("/chats/CL-0001", { thread: { client: row("CL-0001"), messages: [entry(1, { files })] } });
}

describe("photos sent together", () => {
  it("are one block, not a row of boxes", async () => {
    thread([photo(1), photo(2), photo(3)]);
    await screen.findByText("message 1");
    const grid = document.querySelector(".imggrid");
    expect(grid).not.toBeNull();
    expect(grid!.querySelectorAll(".imggrid__tile")).toHaveLength(3);
    expect(document.querySelectorAll(".bub__file--img")).toHaveLength(0);
  });

  it("draw four tiles and say how many more behind the last", async () => {
    thread([1, 2, 3, 4, 5, 6].map(photo));
    await screen.findByText("message 1");
    expect(document.querySelectorAll(".imggrid__tile")).toHaveLength(4);
    expect(document.querySelector(".imggrid__more")).toHaveTextContent("+2");
  });

  it("open one by one, in order, from the one that was pressed", async () => {
    const user = userEvent.setup();
    thread([1, 2, 3, 4, 5, 6].map(photo));
    await screen.findByText("message 1");
    await user.click(document.querySelectorAll(".imggrid__tile")[1]!);
    expect(screen.getByRole("dialog", { name: "الصور" })).toBeInTheDocument();
    expect(document.querySelector("[data-lightbox-count]")).toHaveTextContent("2 / 6");
    expect(document.querySelector(".lightbox__img")).toHaveAttribute("src", "/files/in/p2.jpg");

    await user.click(screen.getByRole("button", { name: "اللي بعدها" }));
    expect(document.querySelector("[data-lightbox-count]")).toHaveTextContent("3 / 6");
    expect(document.querySelector(".lightbox__img")).toHaveAttribute("src", "/files/in/p3.jpg");

    // The photos hidden behind «+2» are in it too, and the keyboard steps as well.
    await user.keyboard("{ArrowRight}{ArrowRight}{ArrowRight}");
    expect(document.querySelector(".lightbox__img")).toHaveAttribute("src", "/files/in/p6.jpg");
    expect(screen.getByRole("button", { name: "اللي بعدها" })).toBeDisabled();
    await user.keyboard("{ArrowLeft}");
    expect(document.querySelector(".lightbox__img")).toHaveAttribute("src", "/files/in/p5.jpg");
  });

  it("close with Escape, the cross and the dark ground", async () => {
    const user = userEvent.setup();
    thread([photo(1), photo(2)]);
    await screen.findByText("message 1");
    const tile = () => document.querySelectorAll(".imggrid__tile")[0]!;

    await user.click(tile());
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "الصور" })).toBeNull();

    await user.click(tile());
    await user.click(screen.getByRole("button", { name: "إغلاق" }));
    expect(screen.queryByRole("dialog", { name: "الصور" })).toBeNull();

    await user.click(tile());
    await user.pointer({ keys: "[MouseLeft]", target: document.querySelector(".lightbox")! });
    expect(screen.queryByRole("dialog", { name: "الصور" })).toBeNull();
  });

  it("stop at the first one", async () => {
    const user = userEvent.setup();
    thread([photo(1), photo(2)]);
    await screen.findByText("message 1");
    await user.click(document.querySelectorAll(".imggrid__tile")[0]!);
    expect(screen.getByRole("button", { name: "اللي قبلها" })).toBeDisabled();
  });

  it("are not a block when there is only one: it stays a photo with a link", async () => {
    thread([photo(1)]);
    await screen.findByText("message 1");
    expect(document.querySelector(".imggrid")).toBeNull();
    expect(screen.getByAltText("p1.jpg").closest("a")).toHaveAttribute("href", "/files/in/p1.jpg");
  });

  it("are split by a document: each run is its own block, a lone photo stays alone", async () => {
    thread([photo(1), photo(2), file({ id: 9, name: "doc.pdf", url: "/files/in/doc.pdf" }), photo(3)]);
    await screen.findByText("message 1");
    expect(document.querySelectorAll(".imggrid")).toHaveLength(1);
    expect(document.querySelectorAll(".imggrid__tile")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "doc.pdf" })).toBeInTheDocument();
    expect(screen.getByAltText("p3.jpg").closest("a")).toHaveAttribute("href", "/files/in/p3.jpg");
  });

  it("leave out a photo whose address is not on this site", async () => {
    thread([photo(1), file({ id: 2, name: "evil.jpg", url: "https://evil.example/e.jpg", image: true }), photo(3)]);
    await screen.findByText("message 1");
    expect(document.querySelector(".imggrid")).toBeNull();
    expect(document.querySelector('img[src*="evil"]')).toBeNull();
  });
});
