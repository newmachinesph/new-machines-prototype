import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { OpsOverview } from "@/lib/api/gen/types.gen";
import { KpiStrip } from "./kpi-strip";

const usd = (amountMinor: number) => ({ amountMinor, currency: "USD" as const });

const overview = (over: Partial<OpsOverview> = {}): OpsOverview => ({
  kpis: {
    activeTenants: 4,
    trialTenants: 1,
    runsToday: 12,
    runSuccessRate7d: 0.9,
    openHumanTasks: 2,
    pendingApprovals: 1,
    aiSpendToday: usd(1500),
    platformDailyCap: usd(60000),
    incidentsOpen: 0,
  },
  attention: [],
  recentAudit: [],
  runsByHour: [
    { hour: 8, completed: 5, failed: 2, waiting: 1 },
    { hour: 9, completed: 3, failed: 1, waiting: 0 },
  ],
  simulatedFields: ["kpis.runsToday", "kpis.runSuccessRate7d", "kpis.aiSpendToday", "runsByHour"],
  ...over,
});

/** The tile whose label is `label`: the label's closest panel. */
const tile = (label: string) => screen.getByText(label).closest(".panel") as HTMLElement;

describe("KpiStrip", () => {
  it("keeps the demo's six tiles and Simulated tags", () => {
    const { container } = render(<KpiStrip overview={overview()} />);
    expect(container.querySelectorAll(".panel")).toHaveLength(6);
    expect(screen.getAllByText("Simulated")).toHaveLength(3);
    expect(screen.queryByText("Sample")).toBeNull();
    expect(screen.queryByText("Failed today")).toBeNull();
    expect(screen.queryByText("Spend this month")).toBeNull();
    expect(within(tile("Open incidents")).getByText("All services normal")).toBeInTheDocument();
    expect(tile("Open reviewer tasks")).toHaveAttribute("href", "/workforce");
  });

  it("tags every listed simulated field Sample in the live workspace, and nothing else", () => {
    render(
      <KpiStrip
        live
        overview={overview({
          simulatedFields: ["kpis.platformDailyCap", "kpis.incidentsOpen"],
          spendMonth: usd(123456),
          topPacks: [],
        })}
      />,
    );
    expect(screen.queryByText("Simulated")).toBeNull();
    expect(screen.getAllByText("Sample")).toHaveLength(2);
    expect(within(tile("Open incidents")).getByText("Sample")).toBeInTheDocument();
    expect(within(tile("Open incidents")).queryByText("All services normal")).toBeNull();
    expect(within(tile("AI spend")).getByText("Sample")).toBeInTheDocument();
    expect(within(tile("Runs today")).queryByText("Sample")).toBeNull();
  });

  it("adds failed runs today and month-to-date spend in the live workspace", () => {
    const { container } = render(
      <KpiStrip live overview={overview({ simulatedFields: [], spendMonth: usd(123456) })} />,
    );
    expect(container.querySelectorAll(".panel")).toHaveLength(8);
    expect(within(tile("Failed today")).getByText("3")).toBeInTheDocument();
    expect(tile("Failed today")).toHaveAttribute("href", "/runs?status=FAILED");
    expect(within(tile("Failed today")).getByText("The link lists all failed runs")).toBeInTheDocument();
    expect(within(tile("Spend this month")).getByText("$1,234.56")).toBeInTheDocument();
  });

  it("links open reviewer tasks to the runs waiting on a reviewer in the live workspace", () => {
    render(<KpiStrip live overview={overview({ simulatedFields: [] })} />);
    expect(tile("Open reviewer tasks")).toHaveAttribute("href", "/runs?status=WAITING_FOR_HUMAN");
  });

  it("tags month-to-date spend like any other listed field", () => {
    render(<KpiStrip live overview={overview({ simulatedFields: ["spendMonth"], spendMonth: usd(100) })} />);
    expect(within(tile("Spend this month")).getByText("Sample")).toBeInTheDocument();
  });
});
