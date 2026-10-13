import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BillingHeader } from "./billing-header";

const workspace = vi.hoisted(() => ({ value: "demo" as "demo" | "live" }));
vi.mock("@/lib/queries/ops", () => ({ useOpsWorkspace: () => workspace.value }));

describe("BillingHeader", () => {
  beforeEach(() => {
    workspace.value = "demo";
  });

  it("tags the demo's billing Simulated and says it is for the demo", () => {
    render(<BillingHeader />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Simulated");
    expect(screen.getByText(/simulated for the demo/)).toBeInTheDocument();
    expect(screen.queryByText("Sample")).toBeNull();
  });

  it("tags live billing Sample under the heading only, without demo copy", () => {
    workspace.value = "live";
    render(<BillingHeader />);
    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading).not.toHaveTextContent("Simulated");
    expect(screen.queryByText(/for the demo/)).toBeNull();
    const note = screen.getByText("Billing figures are sample data, not the live workspace's.");
    expect(heading.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("Sample")).toBeInTheDocument();
  });
});
