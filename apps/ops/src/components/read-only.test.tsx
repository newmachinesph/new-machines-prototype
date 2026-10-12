import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { UiProviders } from "./base";
import { ReadOnly } from "./read-only";
import { Button } from "./ui";

describe("ReadOnly", () => {
  it("keeps the action's name and describes why it is off", () => {
    render(
      <UiProviders>
        <ReadOnly>
          <Button disabled>Suspend tenant</Button>
        </ReadOnly>
      </UiProviders>,
    );
    const button = screen.getByRole("button", { name: "Suspend tenant" });
    expect(button).toBeDisabled();
    const wrapper = button.parentElement!;
    expect(wrapper).toHaveAttribute("tabindex", "0");
    expect(wrapper).toHaveAccessibleDescription("Support access is read-only");
  });
});
