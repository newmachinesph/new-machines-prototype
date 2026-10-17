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
/** The card whose name links to the agent page. */
const card = (name: string) => screen.getByRole("link", { name }).closest("li")!;

describe("AgentList", () => {
  beforeEach(() => {
    state.result = ok([
      agent({ id: "finance-agent", name: "Finance Agent", capabilities: ["finance.reconcile"], usedBy: [recon] }),
      agent({
        id: "retail-agent",
        name: "Retail Agent",
        capabilities: ["retail.orders", "team.assist", "team.triage"],
      }),
      agent({
        id: "agent_finance",
        name: "Invoice Agent",
        publisher: "Sample Labs",
        source: "sample",
        usedBy: [recon, invoices],
      }),
    ]);
  });

  it("lists each agent with publisher, summary and capabilities, linked to its page", () => {
    renderWithIntl(<AgentList />);
    expect(screen.getByRole("link", { name: "Finance Agent" })).toHaveAttribute("href", "/app/agents/finance-agent");
    const finance = card("Finance Agent");
    expect(within(finance).getByText("New Machines Labs, version 1.0.0")).toBeInTheDocument();
    expect(within(finance).getByText("Finance Agent summary")).toBeInTheDocument();
  });

  it("shows a Studio-built agent's definition version, not the 1.0.<n> the Studio writes", () => {
    state.result = ok([
      agent({ id: "org-5c81-helper", name: "Helper", publisher: "Acme Labs", version: "1.0.1", builtByTeam: true }),
    ]);
    renderWithIntl(<AgentList />);
    expect(within(card("Helper")).getByText("Acme Labs, version 1")).toBeInTheDocument();
    expect(screen.queryByText(/1\.0\.1/)).toBeNull();
  });

  it("shows capabilities as plain labels, never as ids", () => {
    renderWithIntl(<AgentList />);
    expect(within(card("Finance Agent")).getByText("Payment reconciliation")).toBeInTheDocument();
    expect(screen.queryByText("finance.reconcile")).toBeNull();
    // A Studio-built agent's capability reads naturally, not as its id cut into words.
    expect(within(card("Retail Agent")).getByText("Helps your team")).toBeInTheDocument();
    expect(screen.queryByText("Team assist")).toBeNull();
    // An id with no published label still reads as words.
    expect(within(card("Retail Agent")).getByText("Team triage")).toBeInTheDocument();
    expect(screen.queryByText("team.triage")).toBeNull();
  });

  it("names and links the packs that use each agent", () => {
    renderWithIntl(<AgentList />);
    const finance = card("Finance Agent");
    expect(within(finance).getByText(/Used in 1 pack:/)).toBeInTheDocument();
    expect(within(finance).getByRole("link", { name: "Order & Payment Reconciliation" })).toHaveAttribute(
      "href",
      "/app/marketplace/order-payment-reconciliation",
    );
    expect(within(card("Retail Agent")).getByText("Not in a pack yet")).toBeInTheDocument();
    const invoice = card("Invoice Agent");
    expect(within(invoice).getByText(/Used in 2 packs:/)).toBeInTheDocument();
    expect(within(invoice).getByRole("link", { name: "Overdue Invoice Follow-up" })).toHaveAttribute(
      "href",
      "/app/marketplace/overdue-invoice-follow-up",
    );
    // The card's own link is not wrapped around the pack links.
    expect(within(invoice).getAllByRole("link")).toHaveLength(3);
  });

  it("tags sample agents only", () => {
    renderWithIntl(<AgentList />);
    expect(within(card("Invoice Agent")).getByText("Sample")).toBeInTheDocument();
    expect(within(card("Finance Agent")).queryByText("Sample")).not.toBeInTheDocument();
  });

  it("filters by a capability's id or by the label shown for it", async () => {
    const user = userEvent.setup();
    renderWithIntl(<AgentList />);
    await user.type(screen.getByRole("searchbox"), "retail.ord");
    expect(screen.getByText("Retail Agent")).toBeInTheDocument();
    expect(screen.queryByText("Finance Agent")).not.toBeInTheDocument();
    await user.clear(screen.getByRole("searchbox"));
    await user.type(screen.getByRole("searchbox"), "payment rec");
    expect(screen.getByText("Finance Agent")).toBeInTheDocument();
    expect(screen.queryByText("Retail Agent")).not.toBeInTheDocument();
  });

  it("filters by name, publisher or summary, and clears the search", async () => {
    const user = userEvent.setup();
    renderWithIntl(<AgentList />);
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
    state.result = ok([
      ...(state.result.data as Agent[]),
      agent({ id: "org-5c81-helper", name: "Helper", publisher: "Acme Labs", builtByTeam: true, certified: false, usedBy: [recon] }),
    ]);
    renderWithIntl(<AgentList />, { locale: "ja" });
    expect(screen.getByRole("searchbox", { name: "エージェントを検索" })).toBeInTheDocument();
    expect(screen.getAllByText(/1件のパックで使用：/)).toHaveLength(2);
    expect(screen.getByText("入金の照合")).toBeInTheDocument();
    // An id with no label stays the id, not half-English words; the pack list has no stray space after the colon.
    expect(screen.getByText("team.triage")).toBeInTheDocument();
    expect(screen.queryByText("Team triage")).toBeNull();
    expect(screen.getByText("チームの業務を支援")).toBeInTheDocument();
    // Our own agent and the pack of ours that uses it read in Japanese; a sample agent keeps its English.
    expect(card("財務エージェント").textContent).toMatch(/1件のパックで使用：注文と入金の照合/);
    expect(screen.queryByText("Finance Agent")).toBeNull();
    expect(card("Invoice Agent")).toBeInTheDocument();
    // A team agent is not ours: neither it nor the packs it names are overlaid, whatever their slug.
    expect(card("Helper").textContent).toMatch(/1件のパックで使用：Order & Payment Reconciliation/);
  });

  it("joins the packs with the language's own list format, each a link", () => {
    renderWithIntl(<AgentList />);
    const used = card("Invoice Agent");
    expect(used.textContent).toMatch(/Used in 2 packs: Order & Payment Reconciliation and Overdue Invoice Follow-up/);
    expect(within(used).getAllByRole("link", { name: /Order|Overdue/ })).toHaveLength(2);
  });
});

describe("AgentList team agents", () => {
  beforeEach(() => {
    state.result = ok([
      agent({ id: "org-a1--helper", name: "Invoice helper", publisher: "Harbor Cafe", builtByTeam: true }),
      agent({ id: "writer-agent", name: "Writer Agent" }),
    ]);
  });

  it("labels an agent the org built", () => {
    renderWithIntl(<AgentList />);
    expect(within(card("Invoice helper")).getByText("Built by your team")).toBeInTheDocument();
    expect(within(card("Writer Agent")).queryByText("Built by your team")).toBeNull();
  });

  it("names a listed agent's publisher once, with its fee", () => {
    state.result = ok([
      agent({
        id: "tax-agent",
        name: "Tax Agent",
        publisher: "Harbor Cafe",
        version: "2",
        listing: {
          listingId: "lst_1",
          publisher: "Harbor Cafe",
          fee: { amountMinor: 30, currency: "USD" },
          feeUnit: "call",
          version: 2,
        },
      }),
    ]);
    renderWithIntl(<AgentList />);
    const tax = card("Tax Agent");
    expect(within(tax).getByText("Version 2")).toBeInTheDocument();
    expect(within(tax).getByText(/By Harbor Cafe/)).toHaveTextContent("By Harbor Cafe · $0.30 per call");
    expect(within(tax).getAllByText(/Harbor Cafe/)).toHaveLength(1);
  });
});
