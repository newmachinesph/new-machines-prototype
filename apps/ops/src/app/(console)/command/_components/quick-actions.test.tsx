import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let canWrite = true;
vi.mock("@/lib/queries/ops", () => ({ useCanWrite: () => canWrite }));

import { QuickActions } from "./quick-actions";

describe("QuickActions", () => {
  beforeEach(() => {
    canWrite = true;
  });

  it("links to the dialogs on their pages for operators who can write", () => {
    render(<QuickActions />);
    expect(screen.getByRole("link", { name: "New tenant" })).toHaveAttribute("href", "/tenants?action=new");
    expect(screen.getByRole("link", { name: "Review packs" })).toHaveAttribute("href", "/marketplace?tab=in_review");
    expect(screen.getByRole("link", { name: "Declare incident" })).toHaveAttribute("href", "/health?action=declare");
  });

  it("disables all three for the read-only support role", () => {
    canWrite = false;
    render(<QuickActions />);
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    for (const name of ["New tenant", "Review packs", "Declare incident"]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
  });
});
