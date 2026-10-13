import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UiProviders } from "@/components/base";
import { RunsView } from "./runs-view";

const run = (id: string, real: boolean) => ({
  id,
  tenantId: "org_hp01",
  tenantName: "Harbor & Pine",
  pack: "order-payment-reconciliation",
  status: "COMPLETED" as const,
  startedAt: "2026-10-13T09:00:00Z",
  cost: { amountMinor: 120, currency: "USD" },
  durationSeconds: 90,
  real,
});

vi.mock("nuqs", () => ({
  parseAsString: {},
  parseAsStringLiteral: () => ({}),
  useQueryState: () => [null, vi.fn()],
}));
const workspace = vi.hoisted(() => ({ value: "demo" as "demo" | "live" }));
vi.mock("@/lib/queries/ops", () => ({ useOpsWorkspace: () => workspace.value }));
vi.mock("@/lib/queries/runs", () => ({
  useRuns: () => ({ isPending: false, isError: false, data: [run("run_7", true), run("run_x001", false)] }),
  useTenantOptions: () => ({ data: [] }),
}));

const renderView = () =>
  render(
    <UiProviders>
      <RunsView />
    </UiProviders>,
  );

describe("RunsView", () => {
  beforeEach(() => {
    workspace.value = "demo";
  });

  it("links real runs to their step record and receipt, and only those", () => {
    render(
      <UiProviders>
        <RunsView />
      </UiProviders>,
    );
    expect(screen.getByRole("link", { name: /run_7/ })).toHaveAttribute("href", "/runs/run_7");
    expect(screen.queryByRole("link", { name: /run_x001/ })).toBeNull();
    expect(screen.getByText("run_x001")).toBeInTheDocument();
  });

  it("renders the same in the live workspace, which only lists runtime runs", () => {
    workspace.value = "live";
    renderView();
    expect(screen.queryByText("Sample")).toBeNull();
    const real = screen.getByText("run_7").closest("tr") as HTMLElement;
    expect(within(real).getByRole("link", { name: "Harbor & Pine" })).toHaveAttribute("href", "/tenants/org_hp01");
  });

  it("shows no Sample tags in the demo", () => {
    renderView();
    expect(screen.queryByText("Sample")).toBeNull();
  });
});
