import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ListingVersion, StudioListing } from "@/lib/api/gen/types.gen";
import { renderWithIntl } from "@/test/intl";
import { PublisherView } from "./publisher-view";

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
const usd = (amountMinor: number) => ({ amountMinor, currency: "USD" as const });
const version = (status: ListingVersion["status"], price = 5): ListingVersion => ({
  id: `v-${status}`,
  definitionVersion: 1,
  status,
  price: usd(price),
  checks: [],
  submittedAt: "2026-10-10T09:00:00Z",
  submittedBy: "ana@acme.test",
});
const listing = (over: Partial<StudioListing>): StudioListing => ({
  id: "l1",
  kind: "pack",
  key: "org-a1--refund-check",
  name: "Refund check",
  status: "listed",
  price: usd(25),
  latest: version("approved", 25),
  approvedVersion: 1,
  installs: 12,
  runs30d: 340,
  earningsMonth: usd(4200),
  simulated: true,
  ...over,
});
const state = vi.hoisted(() => ({ listings: [] as unknown[], earnings: undefined as unknown }));

vi.mock("@/lib/queries/publishing", () => ({
  useStudioListings: () => ok(state.listings),
  useStudioEarnings: () => ok(state.earnings),
}));

describe("PublisherView", () => {
  beforeEach(() => {
    state.listings = [
      listing({}),
      listing({
        id: "l2",
        kind: "agent",
        key: "org-a1--ledger-reader",
        name: "Ledger reader",
        status: "listed",
        price: usd(0),
        latest: { ...version("changes_requested", 0), definitionVersion: 2 },
        installs: 3,
        runs30d: 20,
        earningsMonth: usd(0),
      }),
    ];
    state.earnings = {
      month: usd(4200),
      simulated: true,
      payouts: [
        { month: "2026-08", amount: usd(1000), status: "SIMULATED" },
        { month: "2026-09", amount: usd(3000), status: "SIMULATED" },
      ],
    };
  });

  it("lists the listings with kind, price, installs, runs and earnings, each linking to its page", () => {
    renderWithIntl(<PublisherView />);
    const row = screen.getByRole("link", { name: "Refund check" }).closest("tr") as HTMLElement;
    expect(screen.getByRole("link", { name: "Refund check" })).toHaveAttribute("href", "/studio/publisher/l1");
    expect(within(row).getByText("Pack")).toBeInTheDocument();
    expect(within(row).getByText("Listed")).toBeInTheDocument();
    expect(within(row).getByText("$0.25 per run")).toBeInTheDocument();
    expect(within(row).getByText("12")).toBeInTheDocument();
    expect(within(row).getByText("340")).toBeInTheDocument();
    expect(within(row).getByText("$42.00")).toBeInTheDocument();
    const agent = screen.getByRole("link", { name: "Ledger reader" }).closest("tr") as HTMLElement;
    expect(within(agent).getByText("Agent")).toBeInTheDocument();
    expect(within(agent).getByText("No fee")).toBeInTheDocument();
  });

  it("shows the price in review until a version is first approved, never No fee", () => {
    state.listings = [
      listing({ status: "pending", price: usd(0), approvedVersion: undefined, latest: version("in_review", 250) }),
    ];
    renderWithIntl(<PublisherView />);
    const row = screen.getByRole("link", { name: "Refund check" }).closest("tr") as HTMLElement;
    expect(within(row).getByText("$2.50 per run")).toBeInTheDocument();
    expect(within(row).queryByText("No fee")).toBeNull();
  });

  it("shows the listed price and the different price in review", () => {
    state.listings = [listing({ latest: { ...version("in_review", 40), definitionVersion: 2 } })];
    renderWithIntl(<PublisherView />);
    const row = screen.getByRole("link", { name: "Refund check" }).closest("tr") as HTMLElement;
    expect(within(row).getByText("$0.25 per run")).toBeInTheDocument();
    expect(within(row).getByText("In review: $0.40 per run")).toBeInTheDocument();
  });

  it("shows the version status next to the listing status when the latest version is not approved", () => {
    renderWithIntl(<PublisherView />);
    const agent = screen.getByRole("link", { name: "Ledger reader" }).closest("tr") as HTMLElement;
    expect(within(agent).getByText("Listed")).toBeInTheDocument();
    expect(within(agent).getByText("Changes requested")).toBeInTheDocument();
    const pack = screen.getByRole("link", { name: "Refund check" }).closest("tr") as HTMLElement;
    expect(within(pack).queryByText("Approved")).toBeNull();
  });

  it("labels earnings simulated and lists payout months newest first", () => {
    renderWithIntl(<PublisherView />);
    expect(screen.getAllByText("Earnings this month").length).toBe(2);
    expect(screen.getAllByText("Simulated").length).toBeGreaterThan(0);
    const items = screen.getAllByRole("listitem").map((li) => li.textContent ?? "");
    expect(items[0]).toContain("September 2026");
    expect(items[0]).toContain("$30.00");
    expect(items[1]).toContain("August 2026");
  });

  it("says when there are no payouts", () => {
    state.earnings = { month: usd(0), payouts: [] };
    renderWithIntl(<PublisherView />);
    expect(screen.getByText("No payouts yet.")).toBeInTheDocument();
  });

  it("points to agents and packs when nothing is listed", () => {
    state.listings = [];
    renderWithIntl(<PublisherView />);
    expect(
      screen.getByText("Nothing listed yet. Submit an agent or pack for review from its page."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Agents" })).toHaveAttribute("href", "/studio/agents");
    expect(screen.getByRole("link", { name: "Packs" })).toHaveAttribute("href", "/studio/packs");
  });

  it("speaks Japanese", () => {
    renderWithIntl(<PublisherView />, { locale: "ja" });
    expect(screen.getAllByText("今月の収益").length).toBe(2);
    expect(screen.getByText("支払い履歴")).toBeInTheDocument();
  });
});
