import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { OpsOverview } from "@/lib/api/gen/types.gen";
import { PublishingStats } from "./publishing-stats";

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
  runsByHour: [],
  simulatedFields: [],
  ...over,
});

const tile = (label: string) => screen.getByText(label).closest(".panel") as HTMLElement;

describe("PublishingStats", () => {
  it("shows both figures", () => {
    render(<PublishingStats overview={overview({ listingsInReview: 3, publisherEarningsMonth: usd(12345) })} />);
    expect(tile("Listings in review")).toHaveTextContent("3");
    expect(tile("Publisher earnings this month")).toHaveTextContent("$123.45");
  });

  it("links the review stat to /listings", () => {
    render(<PublishingStats overview={overview({ listingsInReview: 0, publisherEarningsMonth: usd(0) })} />);
    expect(tile("Listings in review")).toHaveAttribute("href", "/listings");
  });

  it("always marks earnings simulated", () => {
    render(<PublishingStats overview={overview({ listingsInReview: 1, publisherEarningsMonth: usd(100) })} />);
    expect(screen.getAllByText("Simulated")).toHaveLength(1);
    expect(tile("Publisher earnings this month")).toHaveTextContent("Simulated");
  });

  it("renders nothing without the fields", () => {
    const { container } = render(<PublishingStats overview={overview()} />);
    expect(container).toBeEmptyDOMElement();
  });
});
