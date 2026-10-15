import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TenantConnectors } from "./tenant-connectors";

const row = (app: string) => screen.getByText(app).closest("li")!;

describe("TenantConnectors", () => {
  it("shows each connection's status and whether it reaches a real account", () => {
    render(
      <TenantConnectors
        connections={[
          { app: "stripe", status: "connected", mode: "composio" },
          { app: "shopify", status: "sandbox", mode: "sandbox" },
          { app: "gmail", status: "pending", mode: "composio" },
          { app: "slack", status: "connected" },
        ]}
      />,
    );
    expect(within(row("stripe")).getByText("Real")).toBeInTheDocument();
    expect(within(row("stripe")).getByText("Connected")).toBeInTheDocument();
    expect(within(row("shopify")).getByText("Simulated")).toBeInTheDocument();
    expect(within(row("gmail")).getByText("Signing in")).toBeInTheDocument();
    expect(within(row("gmail")).getByText("Real")).toBeInTheDocument();
    expect(within(row("slack")).queryByText("Real")).not.toBeInTheDocument();
    expect(within(row("slack")).queryByText("Simulated")).not.toBeInTheDocument();
  });

  it("says when a tenant has no connectors", () => {
    render(<TenantConnectors connections={[]} />);
    expect(screen.getByText("No connectors set up.")).toBeInTheDocument();
  });
});
