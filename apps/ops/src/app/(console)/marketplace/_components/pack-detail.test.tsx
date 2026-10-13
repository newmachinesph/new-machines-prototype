import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { UiProviders } from "@/components/base";
import { PackDetail } from "./pack-detail";

const usd = (amountMinor: number) => ({ amountMinor, currency: "USD" });
const PACK = {
  slug: "order-payment-reconciliation",
  name: "Order & Payment Reconciliation",
  version: "1.0.0",
  publisher: "New Machines Labs",
  category: "Finance",
  status: "published",
  riskClass: "medium",
  certified: false,
  installs: 3,
  runs30d: 0,
  successRate: 0,
  priceNote: "About $1 a run",
  updatedAt: "2026-10-12T10:00:00Z",
  connectors: [],
  function: { id: "finance-ops", name: "Finance operations" },
  industries: [
    { id: "retail-commerce", name: "Retail & Commerce" },
    { id: "manufacturing", name: "Manufacturing" },
  ],
  history: [],
  pack: {
    outcome: "Every order matched.",
    description: "Reads orders and payments.",
    humanReview: "Mismatches go to a reviewer.",
    connectors: [],
    regions: [],
    estimate: { aiMin: usd(60), aiMax: usd(240), humanMax: usd(750) },
  },
};

vi.mock("@/lib/queries/marketplace", () => ({
  usePack: () => ({ isPending: false, isError: false, data: PACK }),
  usePackAction: () => vi.fn(),
}));
vi.mock("@/lib/queries/ops", () => ({ useCanWrite: () => true, useOpsWorkspace: () => "demo" }));

describe("PackDetail", () => {
  it("shows the pack's function and industries", () => {
    render(
      <UiProviders>
        <PackDetail slug="order-payment-reconciliation" />
      </UiProviders>,
    );
    expect(screen.getByText("Finance operations")).toBeInTheDocument();
    expect(screen.getByText("Retail & Commerce, Manufacturing")).toBeInTheDocument();
  });
});
