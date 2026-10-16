import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PackIcon } from "./pack-icon";

describe("PackIcon", () => {
  it("gives each sample pack its own icon", () => {
    const icons = {
      "inbox-lead-tracker": "lucide-inbox",
      "support-inbox-triage": "lucide-life-buoy",
      "weekly-expense-check": "lucide-receipt-text",
      "meeting-follow-ups": "lucide-calendar-check",
    };
    for (const [slug, icon] of Object.entries(icons)) {
      const { container, unmount } = render(<PackIcon slug={slug} />);
      expect(container.querySelector(`svg.${icon}`)).not.toBeNull();
      unmount();
    }
  });

  it("falls back to the generic icon", () => {
    const { container } = render(<PackIcon slug="something-new" />);
    expect(container.querySelector("svg.lucide-boxes")).not.toBeNull();
  });
});
