import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { PackPage } from "./pack-page";

vi.mock("next/navigation", () => ({ notFound: vi.fn() }));
vi.mock("./sandbox-trial", () => ({ SandboxTrial: () => null }));

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
const usd = (amountMinor: number) => ({ amountMinor, currency: "USD" });
const pack = {
  slug: "order-payment-reconciliation",
  name: "Order & Payment Reconciliation",
  version: "1.0.0",
  publisher: "New Machines Labs",
  category: "Finance operations",
  outcome: "Every order matched.",
  description: "Matches orders to payments.",
  agents: ["finance-agent", "ops-agent"],
  connectors: [{ app: "Shopify", access: "read", mocked: true }],
  humanReview: "Mismatches go to a reviewer.",
  estimate: { aiMin: usd(60), aiMax: usd(240), humanMax: usd(750) },
  installed: false,
  certified: true,
  riskClass: "medium",
  regions: ["asia-south1"],
};
const agents = [
  {
    id: "finance-agent",
    name: "Finance Agent",
    version: "1.0.0",
    publisher: "New Machines Labs",
    summary: "Matches.",
    capabilities: [],
  },
  {
    id: "ops-agent",
    name: "Operations Agent",
    version: "1.0.0",
    publisher: "New Machines Labs",
    summary: "Reports.",
    capabilities: [],
  },
];
vi.mock("@/lib/queries/catalog", () => ({
  usePack: () => ok(pack),
  useAgents: () => ok(agents),
  useAgentById: () => (id: string) => agents.find((a) => a.id === id),
}));

describe("PackPage agents", () => {
  it("links each agent to its agent page", () => {
    renderWithIntl(<PackPage slug="order-payment-reconciliation" />);
    const who = screen.getByRole("heading", { name: "Who does the work" }).closest("section")!;
    expect(within(who).getByRole("link", { name: "Finance Agent" })).toHaveAttribute(
      "href",
      "/app/agents/finance-agent",
    );
    expect(within(who).getByRole("link", { name: "Operations Agent" })).toHaveAttribute(
      "href",
      "/app/agents/ops-agent",
    );
  });
});
