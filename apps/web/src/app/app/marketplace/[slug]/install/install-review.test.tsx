import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Pack } from "@/lib/types";
import { renderWithIntl } from "@/test/intl";
import { InstallReview } from "./install-review";

vi.mock("@/components/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/base")>()),
  useToast: () => vi.fn(),
}));
vi.mock("@/lib/queries/catalog", () => ({
  ORG_ID: "org_hp01",
  useAgentById: () => (id: string) =>
    id === "finance-agent" ? { id, name: "Finance Agent", capabilities: ["finance.reconcile"] } : undefined,
  useInstallPack: () => ({ mutate: vi.fn(), isPending: false }),
}));

const usd = (amountMinor: number) => ({ amountMinor, currency: "USD" as const });
const pack = {
  slug: "order-payment-reconciliation",
  name: "Order & Payment Reconciliation",
  version: "1.0.0",
  publisher: "New Machines Labs",
  category: "Finance operations",
  outcome: "Every order matched.",
  description: "Matches orders to payments.",
  agents: ["finance-agent", "ops-agent"],
  connectors: [{ app: "Google Sheets", access: "write (approval)" }],
  humanReview: "Mismatches go to a reviewer.",
  estimate: { aiMin: usd(60), aiMax: usd(240), humanMax: usd(750) },
  installed: false,
  certified: true,
  riskClass: "medium",
  regions: ["asia-south1"],
} satisfies Pack;

describe("InstallReview agents", () => {
  it("links each agent the pack hires to its agent page", () => {
    renderWithIntl(<InstallReview pack={pack} />);
    expect(screen.getByRole("link", { name: "Finance Agent" })).toHaveAttribute("href", "/app/agents/finance-agent");
    // An agent the catalog does not know still links, by its id.
    expect(screen.getByRole("link", { name: "ops-agent" })).toHaveAttribute("href", "/app/agents/ops-agent");
    expect(screen.getByText("finance.reconcile")).toBeInTheDocument();
  });
});
