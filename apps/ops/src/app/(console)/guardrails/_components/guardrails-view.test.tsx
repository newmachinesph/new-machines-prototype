import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UiProviders } from "@/components/base";
import type { Guardrail } from "@/lib/api/gen/types.gen";
import { GuardrailsView } from "./guardrails-view";

const state = vi.hoisted(() => ({ workspace: "demo" as "demo" | "live" }));

vi.mock("@/lib/queries/ops", () => ({
  useCanWrite: () => true,
  useOpsWorkspace: () => state.workspace,
}));

const guardrail = (over: Partial<Guardrail> & Pick<Guardrail, "key" | "kind" | "label">): Guardrail => ({
  description: "Does a thing.",
  enabled: false,
  updatedAt: "2026-10-12T10:00:00Z",
  updatedBy: "fixture.person@newmachines.example",
  ...over,
});

const guardrails: Guardrail[] = [
  guardrail({ key: "pause_all_runs", kind: "kill_switch", label: "Pause all runs", updatedBy: "real@ops.example" }),
  guardrail({ key: "freeze_payouts", kind: "kill_switch", label: "Freeze payouts" }),
  guardrail({ key: "beta_packs", kind: "flag", label: "Beta packs", enabled: true }),
  guardrail({ key: "max_runs", kind: "limit", label: "Max runs", value: 20, unit: "runs" }),
];

vi.mock("@/lib/queries/guardrails", () => ({
  useGuardrails: () => ({ isPending: false, isError: false, data: guardrails }),
  useSetGuardrail: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

const renderView = () =>
  render(
    <UiProviders>
      <GuardrailsView />
    </UiProviders>,
  );

/** The list item that holds the guardrail labelled `label`. */
const row = (label: string) => screen.getByText(label).closest("li") as HTMLElement;

describe("GuardrailsView", () => {
  beforeEach(() => {
    state.workspace = "demo";
  });

  it("lets an operator edit every guardrail in the demo, with no Sample tags", () => {
    renderView();
    expect(screen.queryByText("Sample")).toBeNull();
    expect(screen.getByRole("button", { name: "Turn on Freeze payouts" })).toBeEnabled();
    expect(screen.getByRole("switch", { name: "Beta packs" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Edit limit: Max runs" })).toBeEnabled();
    expect(within(row("Freeze payouts")).getByText(/fixture\.person/)).toBeInTheDocument();
  });

  it("tags every guardrail but the pause switch Sample in the live workspace", () => {
    state.workspace = "live";
    renderView();
    for (const label of ["Freeze payouts", "Beta packs", "Max runs"]) {
      expect(within(row(label)).getByText("Sample")).toBeInTheDocument();
    }
    expect(within(row("Pause all runs")).queryByText("Sample")).toBeNull();
  });

  it("makes the sample guardrails read-only and drops their fixture attribution, keeping the pause switch", () => {
    state.workspace = "live";
    renderView();
    expect(screen.queryByRole("button", { name: "Turn on Freeze payouts" })).toBeNull();
    expect(screen.queryByRole("switch", { name: "Beta packs" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Edit limit: Max runs" })).toBeNull();
    expect(screen.queryByText(/fixture\.person/)).toBeNull();
    expect(screen.getByRole("button", { name: "Turn on Pause all runs" })).toBeEnabled();
    expect(within(row("Pause all runs")).getByText(/real@ops\.example/)).toBeInTheDocument();
  });
});
