import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Agent } from "@/lib/types";
import { renderWithIntl } from "@/test/intl";
import { AgentList } from "./agent-list";

vi.mock("nuqs", () => ({
  parseAsString: { withDefault: (d: string) => ({ d }) },
  useQueryState: (_key: string, parser: { d: string }) => {
    const [v, set] = useState<string | null>(null);
    return [v ?? parser.d, set];
  },
}));

const agent = (over: Partial<Agent> & Pick<Agent, "id" | "name">): Agent => ({
  version: "1.0.0",
  publisher: "New Machines Labs",
  summary: `${over.name} summary`,
  capabilities: [],
  regions: ["asia-south1"],
  certified: true,
  skills: [],
  tools: [],
  usedBy: [],
  source: "definition",
  ...over,
});

const state = vi.hoisted(() => ({ result: {} as Record<string, unknown> }));
vi.mock("@/lib/queries/catalog", () => ({ useAgents: () => state.result }));
const ok = (data: unknown) => ({ isPending: false, isError: false, data });

const recon = { slug: "order-payment-reconciliation", name: "Order & Payment Reconciliation" };
const invoices = { slug: "overdue-invoice-follow-up", name: "Overdue Invoice Follow-up" };

describe("AgentList", () => {
  beforeEach(() => {
    state.result = ok([
      agent({ id: "finance-agent", name: "Finance Agent", capabilities: ["finance.reconcile"], usedBy: [recon] }),
      agent({ id: "retail-agent", name: "Retail Agent", capabilities: ["retail.orders"] }),
      agent({
        id: "agent_finance",
        name: "Invoice Agent",
        publisher: "Sample Labs",
        source: "sample",
        usedBy: [recon, invoices],
      }),
    ]);
  });

  it("lists each agent with publisher, summary, capabilities and pack count, linked to its page", () => {
    renderWithIntl(<AgentList />);
    const finance = screen.getByRole("link", { name: /Finance Agent/ });
    expect(finance).toHaveAttribute("href", "/app/agents/finance-agent");
    expect(within(finance).getByText("New Machines Labs, version 1.0.0")).toBeInTheDocument();
    expect(within(finance).getByText("Finance Agent summary")).toBeInTheDocument();
    expect(within(finance).getByText("finance.reconcile")).toBeInTheDocument();
    expect(within(finance).getByText("Used in 1 pack")).toBeInTheDocument();
    expect(
      within(screen.getByRole("link", { name: /Retail Agent/ })).getByText("Not in a pack yet"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("link", { name: /Invoice Agent/ })).getByText("Used in 2 packs"),
    ).toBeInTheDocument();
  });

  it("tags sample agents only", () => {
    renderWithIntl(<AgentList />);
    expect(within(screen.getByRole("link", { name: /Invoice Agent/ })).getByText("Sample")).toBeInTheDocument();
    expect(within(screen.getByRole("link", { name: /Finance Agent/ })).queryByText("Sample")).not.toBeInTheDocument();
  });

  it("filters by name, publisher, summary or capability, and clears the search", async () => {
    const user = userEvent.setup();
    renderWithIntl(<AgentList />);
    await user.type(screen.getByRole("searchbox"), "retail.orders");
    expect(screen.getByText("Retail Agent")).toBeInTheDocument();
    expect(screen.queryByText("Finance Agent")).not.toBeInTheDocument();
    await user.clear(screen.getByRole("searchbox"));
    await user.type(screen.getByRole("searchbox"), "sample labs");
    expect(screen.getByText("Invoice Agent")).toBeInTheDocument();
    expect(screen.queryByText("Retail Agent")).not.toBeInTheDocument();
    await user.type(screen.getByRole("searchbox"), "zzz");
    expect(screen.getByText("No agent matches.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show all agents" }));
    expect(screen.getByText("Finance Agent")).toBeInTheDocument();
  });

  it("shows a skeleton while loading and an empty state with no agents", () => {
    state.result = { isPending: true, isError: false, data: undefined };
    const { container, unmount } = renderWithIntl(<AgentList />);
    expect(container.querySelector('[aria-hidden="true"]')).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    unmount();
    state.result = ok([]);
    renderWithIntl(<AgentList />);
    expect(screen.getByText("No agents are available yet.")).toBeInTheDocument();
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
  });

  it("is translated into Japanese", () => {
    renderWithIntl(<AgentList />, { locale: "ja" });
    expect(screen.getByRole("searchbox", { name: "エージェントを検索" })).toBeInTheDocument();
    expect(screen.getByText("1件のパックで使用")).toBeInTheDocument();
  });
});
