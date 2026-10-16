import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { UsageView } from "./usage-view";

const usd = (amountMinor: number) => ({ amountMinor, currency: "USD" as const });
const data = vi.hoisted(() => ({ usage: undefined as unknown }));

vi.mock("@/lib/queries/me", () => ({ useIsDemo: () => false }));
vi.mock("@/lib/queries/workspace", () => ({
  useUsage: () => ({ isPending: false, isError: false, data: data.usage }),
}));

const fee = (name: string, publisher: string, kind: "pack_run" | "agent_call", quantity: number, unit: number) => ({
  listingId: `lst_${name}`,
  name,
  publisher,
  kind,
  quantity,
  unit: usd(unit),
  amount: usd(unit * quantity),
});

const txn = (id: string, fees?: ReturnType<typeof fee>[]) => ({
  id,
  at: "2026-10-12T16:05:12Z",
  kind: "run",
  description: `Run ${id}`,
  runId: id,
  amount: usd(350),
  status: "POSTED",
  lines: [{ account: "Publisher fees", debit: 350 }],
  ...(fees ? { fees } : {}),
});

const org = {
  id: "org_x",
  name: "Org",
  short: "Org",
  plan: "Trial",
  monthlyCap: usd(25000),
  monthSpent: usd(350),
  region: "us-central1",
};

describe("UsageView publisher fees", () => {
  it("expands a transaction's fee items", () => {
    data.usage = {
      org,
      ledger: [
        txn("run_1", [
          fee("Invoice matcher", "Acme Labs", "pack_run", 1, 200),
          fee("Tax checker", "Ledgerly", "agent_call", 3, 50),
        ]),
      ],
    };
    renderWithIntl(<UsageView />);
    expect(screen.queryByText("Invoice matcher by Acme Labs")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show fee details" }));
    expect(screen.getByText("Invoice matcher by Acme Labs")).toBeInTheDocument();
    expect(screen.getByText("Per run")).toBeInTheDocument();
    expect(screen.getByText("Tax checker by Ledgerly")).toBeInTheDocument();
    expect(screen.getByText("3 calls × $0.50")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hide fee details" }));
    expect(screen.queryByText("Invoice matcher by Acme Labs")).not.toBeInTheDocument();
  });

  it("shows the month's publisher fees on their own line, not in the agents figure", () => {
    data.usage = { org, ledger: [txn("run_1", [fee("Invoice matcher", "Acme Labs", "pack_run", 1, 350)])] };
    renderWithIntl(<UsageView />);
    const tile = screen.getByText("Agents, models and tools").parentElement as HTMLElement;
    expect(tile).toHaveTextContent("$0.00");
    expect(within(tile).getByText("Publisher fees, counted separately: $3.50")).toBeInTheDocument();
    expect(within(tile).getByText("Simulated")).toBeInTheDocument();
  });

  it("shows no fee toggle for a run without fees", () => {
    data.usage = { org, ledger: [txn("run_2"), txn("run_3", [])] };
    renderWithIntl(<UsageView />);
    expect(screen.queryByRole("button", { name: "Show fee details" })).not.toBeInTheDocument();
  });

  it("speaks Japanese", () => {
    data.usage = { org, ledger: [txn("run_1", [fee("Invoice matcher", "Acme Labs", "pack_run", 1, 200)])] };
    renderWithIntl(<UsageView />, { locale: "ja" });
    expect(screen.getByRole("button", { name: "手数料の内訳を表示" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "手数料の内訳を表示" }));
    expect(screen.getByText("提供元の手数料")).toBeInTheDocument();
  });
});
