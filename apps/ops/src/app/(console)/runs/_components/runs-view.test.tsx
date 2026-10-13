import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
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
vi.mock("@/lib/queries/runs", () => ({
  useRuns: () => ({ isPending: false, isError: false, data: [run("run_7", true), run("run_x001", false)] }),
  useTenantOptions: () => ({ data: [] }),
}));

describe("RunsView", () => {
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
});
