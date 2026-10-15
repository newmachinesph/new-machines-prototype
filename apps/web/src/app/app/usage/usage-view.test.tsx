import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { UsageView } from "./usage-view";

const usd = (amountMinor: number) => ({ amountMinor, currency: "USD" as const });
const data = vi.hoisted(() => ({ demo: false, usage: undefined as unknown }));

vi.mock("@/lib/queries/me", () => ({ useIsDemo: () => data.demo }));
vi.mock("@/lib/queries/workspace", () => ({
  useUsage: () => ({ isPending: false, isError: false, data: data.usage }),
}));

const org = (spent: number, plan: string) => ({
  id: "org_x",
  name: "Org",
  short: "Org",
  plan,
  monthlyCap: usd(25000),
  monthSpent: usd(spent),
  region: "us-central1",
});

describe("UsageView in a new live workspace", () => {
  beforeEach(() => {
    data.demo = false;
    data.usage = { org: org(0, "Trial"), ledger: [] };
  });

  it("shows zero figures and points an empty ledger at starting a run", () => {
    renderWithIntl(<UsageView />);
    expect(screen.getByText("Nothing is held right now.")).toBeInTheDocument();
    expect(screen.getByText("No reviewer payments yet.")).toBeInTheDocument();
    expect(screen.getByText("No charges yet. Each run you start adds its costs here.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start a run" })).toHaveAttribute("href", "/app/runs/new");
    expect(screen.getByText("Trial, no plan fee (simulated)")).toBeInTheDocument();
    expect(screen.getByText("None. Billing is simulated, so no card is charged.")).toBeInTheDocument();
    expect(screen.queryByText(/demo/i)).not.toBeInTheDocument();
  });
});

describe("UsageView in the demo workspace", () => {
  it("derives the held run, reviewer pay and the absorbed share from the ledger", () => {
    data.demo = true;
    data.usage = {
      org: org(6194, "Pro"),
      ledger: [
        {
          id: "txn_5512",
          at: "2026-10-12T16:05:12Z",
          kind: "hold",
          description: "Budget hold for run_1047",
          runId: "run_1047",
          amount: usd(5000),
          status: "HELD",
          lines: [],
        },
        {
          id: "txn_5497",
          at: "2026-10-11T10:00:00Z",
          kind: "human_pay",
          description: "Reviewer pay, task ht_009",
          amount: usd(750),
          status: "ELIGIBLE",
          lines: [{ account: "Buyer charges", debit: 750 }],
        },
        {
          id: "txn_5420",
          at: "2026-10-09T10:00:00Z",
          kind: "human_pay",
          description: "Reviewer pay, task ht_010",
          amount: usd(400),
          status: "POSTED",
          lines: [{ account: "Platform absorbed cost", debit: 400 }],
        },
        {
          id: "txn_5400",
          at: "2026-10-01T00:00:00Z",
          kind: "plan",
          description: "Pro plan, October",
          amount: usd(4900),
          status: "POSTED",
          lines: [{ account: "Buyer charges", debit: 4900 }],
        },
      ],
    };
    renderWithIntl(<UsageView />);
    expect(screen.getByText("Spent in October")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "run_1047" })).toHaveAttribute("href", "/app/runs/run_1047");
    // The run link sits in the opened panel, never inside the summary, and the id line is skipped when the title has it.
    const links = screen.getAllByRole("link", { name: "View run" });
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/app/runs/run_1047");
    expect(links[0]?.closest("summary")).toBeNull();
    expect(screen.queryByRole("link", { name: "Budget hold for run_1047" })).toBeNull();
    expect(document.querySelector("summary code")).toBeNull();
    expect(screen.queryByRole("link", { name: "Reviewer pay, task ht_009" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Plan and payment" })).toBeInTheDocument();
    expect(screen.queryByText(/posted twice|debits equal credits/)).toBeNull();
    expect(screen.getByText("2 payments. $4.00 of it was absorbed by New Machines.")).toBeInTheDocument();
    expect(screen.getByText("Pro, $49.00 a month (simulated)")).toBeInTheDocument();
    expect(screen.getByText("$5.44")).toBeInTheDocument();
  });
});
