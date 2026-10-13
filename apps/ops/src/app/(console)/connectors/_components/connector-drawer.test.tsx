import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UiProviders } from "@/components/base";
import type { ConnectorEntry } from "@/lib/api/gen/types.gen";
import { ConnectorDrawer } from "./connector-drawer";

const canWrite = vi.hoisted(() => ({ value: true }));
const workspace = vi.hoisted(() => ({ value: "demo" as "demo" | "live" }));
vi.mock("@/lib/queries/ops", () => ({ useCanWrite: () => canWrite.value, useOpsWorkspace: () => workspace.value }));
const idle = vi.hoisted(() => ({ mutateAsync: vi.fn(), isPending: false }));
vi.mock("@/lib/queries/connectors", () => ({
  useHealthCheckConnector: () => idle,
  useEnableConnector: () => idle,
  useDisableConnector: () => idle,
  useSetConnectorDefaults: () => idle,
}));

const connector: ConnectorEntry = {
  id: "gmail",
  app: "Gmail",
  category: "Email",
  provider: "Composio",
  authType: "oauth_managed",
  status: "enabled",
  tenantsConnected: 7,
  callsToday: 2210,
  errorRate: 0.006,
  lastHealthCheck: { at: "2026-10-12T16:00:00Z", ok: true, latencyMs: 260 },
  defaults: { read: "permit", write: "require_approval", delete: "deny", money: "deny" },
  scopes: ["gmail.readonly"],
};

const renderDrawer = (c: ConnectorEntry = connector) =>
  render(
    <UiProviders>
      <ConnectorDrawer connector={c} onClose={vi.fn()} />
    </UiProviders>,
  );

describe("ConnectorDrawer", () => {
  beforeEach(() => {
    canWrite.value = true;
    workspace.value = "demo";
  });

  it("shows the simulated health section and its last check in the demo", async () => {
    renderDrawer();
    expect(await screen.findByRole("heading", { name: /Health/ })).toHaveAttribute("id", "drawer-health");
    expect(screen.getByText("Last check")).toBeInTheDocument();
    expect(screen.getByText("simulated")).toBeInTheDocument();
  });

  it("hides the health section and the health check in the live workspace, keeping real usage", async () => {
    workspace.value = "live";
    renderDrawer({ ...connector, lastHealthCheck: undefined });
    expect(await screen.findByRole("heading", { name: "Usage" })).toHaveAttribute("id", "drawer-usage");
    expect(screen.queryByRole("heading", { name: /Health/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Run health check" })).toBeNull();
    expect(screen.queryByText("Last check")).toBeNull();
    expect(screen.queryByText("Not checked")).toBeNull();
    expect(screen.queryByText("simulated")).toBeNull();
    expect(screen.getByText("Calls today")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Disable connector" })).toBeEnabled();
  });

  it("lets an operator run a health check and edit the defaults", async () => {
    renderDrawer();
    expect(await screen.findByRole("button", { name: "Run health check" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Disable connector" })).toBeEnabled();
    expect(screen.getByRole("group", { name: "Read decision" })).toBeInTheDocument();
  });

  it("gives support disabled actions and read-only defaults", async () => {
    canWrite.value = false;
    renderDrawer();
    expect(await screen.findByRole("button", { name: "Run health check" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Disable connector" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save defaults" })).toBeDisabled();
    expect(screen.queryByRole("group", { name: "Read decision" })).toBeNull();
    expect(screen.getByText("Read decision:")).toBeInTheDocument();
  });
});
