import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UiProviders } from "@/components/base";
import { ConnectorsView } from "./connectors-view";

const state = vi.hoisted(() => ({
  canWrite: true,
  action: "add" as string | null,
  selected: null as string | null,
  setAction: vi.fn(),
  setSelected: vi.fn(),
}));

vi.mock("nuqs", () => ({
  parseAsString: {},
  parseAsStringLiteral: () => ({}),
  useQueryState: (key: string) =>
    key === "action" ? [state.action, state.setAction] : [state.selected, state.setSelected],
}));
vi.mock("@/lib/queries/ops", () => ({
  useCanWrite: () => state.canWrite,
  useMe: () => ({ isSuccess: true }),
}));
const connector = vi.hoisted(() => ({
  id: "stripe",
  app: "Stripe",
  category: "Payments",
  provider: "Composio",
  authType: "api_key",
  status: "enabled",
  tenantsConnected: 4,
  callsToday: 780,
  errorRate: 0.07,
  lastHealthCheck: { at: "2026-10-12T16:00:00Z", ok: true, latencyMs: 200 },
  defaults: { read: "permit", write: "require_approval", delete: "deny", money: "deny" },
  scopes: [],
}));
vi.mock("@/lib/queries/connectors", () => ({
  useConnectors: () => ({ isPending: false, isError: false, data: [connector] }),
}));
vi.mock("./add-connector", () => ({ AddConnector: () => <div data-testid="add-dialog" /> }));
vi.mock("./connector-drawer", () => ({ ConnectorDrawer: () => null, STATUS_TONE: { enabled: "machine" } }));

const renderView = () =>
  render(
    <UiProviders>
      <ConnectorsView />
    </UiProviders>,
  );

describe("ConnectorsView", () => {
  beforeEach(() => {
    state.canWrite = true;
    state.action = "add";
    state.selected = null;
    state.setAction.mockClear();
    state.setSelected.mockClear();
  });

  it("mounts Add connector for an operator", () => {
    renderView();
    expect(screen.getByTestId("add-dialog")).toBeInTheDocument();
  });

  it("does not mount Add connector for support and clears the action parameter", () => {
    state.canWrite = false;
    renderView();
    expect(screen.queryByTestId("add-dialog")).toBeNull();
    expect(state.setAction).toHaveBeenCalledWith(null);
  });

  it("labels an error rate of 5% or more with a visible High pill", () => {
    renderView();
    expect(screen.getByText("High")).toBeVisible();
    expect(screen.getByText("7%")).toBeInTheDocument();
  });

  it("clears an unknown connector id from the URL", () => {
    state.selected = "nope";
    renderView();
    expect(state.setSelected).toHaveBeenCalledWith(null);
  });
});
