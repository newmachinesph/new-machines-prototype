import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UiProviders } from "@/components/base";
import type { OpsHealth } from "@/lib/api/gen/types.gen";
import { HealthView } from "./health-view";

const state = vi.hoisted(() => ({
  workspace: "demo" as "demo" | "live",
  action: null as string | null,
  setAction: vi.fn(),
}));

vi.mock("nuqs", () => ({
  parseAsStringLiteral: () => ({}),
  useQueryState: () => [state.action, state.setAction],
}));
vi.mock("@/lib/queries/ops", () => ({
  useCanWrite: () => true,
  useMe: () => ({ data: { role: "owner", workspace: state.workspace } }),
  useOpsWorkspace: () => state.workspace,
}));

const health: OpsHealth = {
  services: [{ key: "api", name: "API", status: "degraded", latencyP95Ms: 120, uptime30d: 0.999 }],
  incidents: [
    {
      id: "inc_0042",
      title: "Slow API",
      severity: "sev2",
      status: "monitoring",
      startedAt: "2026-10-12T10:00:00Z",
      services: ["api"],
      updates: [{ at: "2026-10-12T10:00:00Z", by: "fixture.person@newmachines.example", text: "Looking." }],
    },
  ],
} as OpsHealth;

vi.mock("@/lib/queries/health", () => ({
  useHealth: () => ({ isPending: false, isError: false, data: health }),
  useDeclareIncident: () => ({ mutateAsync: vi.fn() }),
  useUpdateIncident: () => ({ mutateAsync: vi.fn() }),
}));

const renderView = () =>
  render(
    <UiProviders>
      <HealthView />
    </UiProviders>,
  );

describe("HealthView", () => {
  beforeEach(() => {
    state.workspace = "demo";
    state.action = null;
    state.setAction.mockClear();
  });

  it("lets an operator declare an incident and post updates in the demo", () => {
    renderView();
    expect(screen.getByRole("button", { name: "Declare incident" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Post update" })).toBeEnabled();
  });

  it("hides Declare incident and Post update in the live workspace and drops the declare link", () => {
    state.workspace = "live";
    state.action = "declare";
    renderView();
    expect(screen.queryByRole("button", { name: "Declare incident" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Post update" })).toBeNull();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(state.setAction).toHaveBeenCalledWith(null);
  });

  it("keeps a demo declare link for an operator who can write", () => {
    state.action = "declare";
    renderView();
    expect(state.setAction).not.toHaveBeenCalled();
  });
});
