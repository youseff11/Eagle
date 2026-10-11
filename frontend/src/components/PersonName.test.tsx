import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithProviders } from "../test/helpers";
import { PersonName } from "./PersonName";

describe("PersonName", () => {
  it("draws somebody still on the staff as plain text", () => {
    renderWithProviders(<PersonName name="Sam" />);
    expect(screen.getByText("Sam")).not.toHaveClass("person-gone");
  });

  it("draws a deleted person in the deleted colour and says so", () => {
    renderWithProviders(<PersonName name="Sam" gone />);
    const name = screen.getByText("Sam");
    expect(name).toHaveClass("person-gone");
    expect(name).toHaveAttribute("title", "موظف اتمسح");
  });

  it("draws a dash for nobody", () => {
    const { container } = renderWithProviders(<PersonName name={null} gone />);
    expect(container.textContent).toBe("—");
  });
});
