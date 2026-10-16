import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { WorkReceipt } from "./work-receipt";

const state = vi.hoisted(() => ({ query: {} as Record<string, unknown> }));
vi.mock("@/lib/queries/runs", () => ({ useReceipt: () => state.query }));

const usd = (amountMinor: number) => ({ amountMinor, currency: "USD" as const });
const base = {
  runId: "run_9",
  verified: true,
  entries: 14,
  headHash: "0123456789abcdef0123456789abcdef",
  pinned: [],
  items: [],
};
const fees = [
  {
    listingId: "lst_1",
    name: "Invoice matcher",
    publisher: "Acme Labs",
    kind: "pack_run" as const,
    quantity: 1,
    unit: usd(200),
    amount: usd(200),
  },
  {
    listingId: "lst_2",
    name: "Tax checker",
    publisher: "Ledgerly",
    kind: "agent_call" as const,
    quantity: 3,
    unit: usd(50),
    amount: usd(150),
  },
];

describe("WorkReceipt publisher fees", () => {
  it("lists each fee item and the total with the simulated tag", () => {
    state.query = { data: { ...base, fees } };
    renderWithIntl(<WorkReceipt runId="run_9" status="COMPLETED" />);
    expect(screen.getByText("Publisher fees")).toBeInTheDocument();
    expect(screen.getByText("Invoice matcher by Acme Labs")).toBeInTheDocument();
    expect(screen.getByText("Tax checker by Ledgerly")).toBeInTheDocument();
    expect(screen.getByText("Per run")).toBeInTheDocument();
    expect(screen.getByText("3 calls × $0.50")).toBeInTheDocument();
    expect(screen.getByText("$2.00")).toBeInTheDocument();
    expect(screen.getByText("$1.50")).toBeInTheDocument();
    expect(screen.getByText("Total publisher fees")).toBeInTheDocument();
    expect(screen.getByText("$3.50")).toBeInTheDocument();
    expect(screen.getByText("Simulated: no money moves")).toBeInTheDocument();
  });

  it("shows no fee block without fees", () => {
    for (const data of [base, { ...base, fees: [] }]) {
      state.query = { data };
      const { unmount } = renderWithIntl(<WorkReceipt runId="run_9" status="COMPLETED" />);
      expect(screen.queryByText("Publisher fees")).not.toBeInTheDocument();
      expect(screen.queryByText("Simulated: no money moves")).not.toBeInTheDocument();
      unmount();
    }
  });

  it("speaks Japanese", () => {
    state.query = { data: { ...base, fees } };
    renderWithIntl(<WorkReceipt runId="run_9" status="COMPLETED" />, { locale: "ja" });
    expect(screen.getByText("提供元の手数料")).toBeInTheDocument();
  });
});
