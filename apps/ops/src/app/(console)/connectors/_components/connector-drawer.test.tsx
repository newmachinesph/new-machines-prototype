import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UiProviders } from "@/components/base";
import type { ConnectorEntry } from "@/lib/api/gen/types.gen";
import { ConnectorDrawer } from "./connector-drawer";

const canWrite = vi.hoisted(() => ({ value: true }));
vi.mock("@/lib/queries/ops", () => ({ useCanWrite: () => canWrite.value }));
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

const renderDrawer = () =>
  render(
    <UiProviders>
      <ConnectorDrawer connector={connector} onClose={vi.fn()} />
    </UiProviders>,
  );

describe("ConnectorDrawer", () => {
  beforeEach(() => {
    canWrite.value = true;
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
