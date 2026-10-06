import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { PreferencesProvider } from "../i18n/Preferences";
import { Avatar } from "./Avatar";

const view = (ui: React.ReactElement) => render(<PreferencesProvider initialLang="ar" initialTheme="dark">{ui}</PreferencesProvider>);

describe("Avatar", () => {
  it("is only a face when it is not asked to preview: no button, nothing to press", () => {
    view(<Avatar src="/files/avatars/a.png" initials="SS" />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(document.querySelector("img.avatar__img")).toHaveAttribute("src", "/files/avatars/a.png");
  });

  it("has nothing to enlarge when the person has no picture", () => {
    view(<Avatar src={null} initials="SS" preview="Sami Support" />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("SS")).toHaveClass("avatar");
  });

  it("opens the picture large with the name under it, and closes with Escape, the cross and the dark ground", async () => {
    const user = userEvent.setup();
    view(<Avatar src="/files/avatars/a.png" initials="SS" preview="Sami Support" />);
    const open = () => user.click(screen.getByRole("button", { name: "كبّر صورة Sami Support" }));

    await open();
    const dialog = screen.getByRole("dialog", { name: "صورة البروفايل" });
    expect(dialog.querySelector("img.lightbox__img--avatar")).toHaveAttribute("src", "/files/avatars/a.png");
    expect(dialog).toHaveTextContent("Sami Support");
    // One picture: nothing to step to, and no «1 / 1».
    expect(screen.queryByRole("button", { name: "اللي بعدها" })).toBeNull();
    expect(screen.queryByRole("button", { name: "اللي قبلها" })).toBeNull();
    expect(document.querySelector("[data-lightbox-count]")).toBeNull();
    // A face is not a file somebody saves: the button that saves a photo of the chat is not here.
    expect(within(dialog).queryByRole("link", { name: "تنزيل" })).toBeNull();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();

    await open();
    await user.click(screen.getByRole("button", { name: "إغلاق" }));
    expect(screen.queryByRole("dialog")).toBeNull();

    await open();
    await user.pointer({ keys: "[MouseLeft]", target: document.querySelector(".lightbox")! });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("falls back to the initials, with nothing to enlarge, when the picture has gone", async () => {
    view(<Avatar src="/files/avatars/gone.png" initials="SS" preview="Sami Support" />);
    const picture = document.querySelector("img.avatar__img") as HTMLImageElement;
    picture.dispatchEvent(new Event("error"));
    expect(await screen.findByText("SS")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
