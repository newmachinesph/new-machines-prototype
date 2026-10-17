import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { PackPage } from "./pack-page";

vi.mock("next/navigation", () => ({ notFound: vi.fn() }));
vi.mock("./sandbox-trial", () => ({ SandboxTrial: () => null, TRIAL_ID: "sandbox-trial" }));

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
    capabilities: ["finance.reconcile"],
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
const state = vi.hoisted(() => ({
  installed: false,
  live: false,
  role: "owner",
  extra: {} as Record<string, unknown>,
}));
vi.mock("@/lib/queries/me", () => ({
  useIsLive: () => state.live,
  useMe: () => ({ data: { role: state.role } }),
}));
vi.mock("@/lib/queries/catalog", () => ({
  usePack: () => ok({ ...pack, installed: state.installed, ...state.extra }),
  useAgents: () => ok(agents),
  useAgentById: () => (id: string) => agents.find((a) => a.id === id),
}));

afterEach(() => {
  state.installed = false;
  state.live = false;
  state.role = "owner";
  state.extra = {};
});

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

describe("PackPage actions", () => {
  it("offers one primary action, Add, with the sample-data trial as the secondary", () => {
    renderWithIntl(<PackPage slug="order-payment-reconciliation" />);
    const header = screen.getByRole("heading", { level: 1 }).closest("header")!;
    expect(within(header).getByRole("link", { name: "Add to workspace" })).toHaveAttribute(
      "href",
      "/app/marketplace/order-payment-reconciliation/install",
    );
    expect(within(header).getByRole("link", { name: "See the sample-data trial" })).toHaveAttribute(
      "href",
      "#sandbox-trial",
    );
    expect(within(header).getAllByRole("link")).toHaveLength(2);
    expect(document.body.textContent).not.toMatch(/hire/i);
  });

  it("shows capabilities as plain labels and explains the risk class", () => {
    renderWithIntl(<PackPage slug="order-payment-reconciliation" />);
    expect(screen.getByText("Payment reconciliation")).toBeInTheDocument();
    expect(screen.queryByText("finance.reconcile")).toBeNull();
    expect(screen.getByText("Medium")).toBeInTheDocument();
    expect(screen.getByText(/Can write or send, but only with your approval/)).toBeInTheDocument();
  });

  it("hides the empty Trust Passport of a certified pack with no report", () => {
    renderWithIntl(<PackPage slug="order-payment-reconciliation" />);
    expect(screen.queryByRole("heading", { name: "Trust Passport" })).toBeNull();
    expect(screen.queryByText(/No evaluation report/)).toBeNull();
  });
});

describe("PackPage versions and Japanese", () => {
  it("shows a Studio-built pack by its definition version", () => {
    state.extra = { version: "1.0.1", builtByTeam: true, certified: false, publisher: "Acme Labs" };
    renderWithIntl(<PackPage slug="order-payment-reconciliation" />);
    expect(screen.getByText("Acme Labs, version 1")).toBeInTheDocument();
    expect(screen.queryByText(/1\.0\.1/)).toBeNull();
  });

  it("names each agent with its version and publisher", () => {
    renderWithIntl(<PackPage slug="order-payment-reconciliation" />);
    const who = screen.getByRole("heading", { name: "Who does the work" }).closest("section")!;
    expect(within(who).getAllByText("New Machines Labs, version 1.0.0")).toHaveLength(2);
  });

  it("translates the Trust Passport heading into Japanese", () => {
    state.extra = { certified: false };
    renderWithIntl(<PackPage slug="order-payment-reconciliation" />, { locale: "ja" });
    expect(screen.getByRole("heading", { name: "トラストパスポート" })).toBeInTheDocument();
    expect(screen.queryByText("Trust Passport")).toBeNull();
  });
});

describe("PackPage pack settings", () => {
  it("links an added pack to its settings in a live workspace only", () => {
    state.installed = true;
    state.live = true;
    const { unmount } = renderWithIntl(<PackPage slug="order-payment-reconciliation" />);
    expect(screen.getByRole("link", { name: "Pack settings" })).toHaveAttribute(
      "href",
      "/app/marketplace/order-payment-reconciliation/install",
    );
    unmount();
    state.live = false;
    renderWithIntl(<PackPage slug="order-payment-reconciliation" />);
    expect(screen.queryByRole("link", { name: "Pack settings" })).toBeNull();
  });
});

describe("PackPage edit a copy", () => {
  const editCopy = () => screen.queryByRole("link", { name: "Edit a copy in Studio" });

  it("links a copyable pack to a Studio copy for a builder in a live workspace", () => {
    state.live = true;
    state.extra = { copyable: true };
    renderWithIntl(<PackPage slug="order-payment-reconciliation" />);
    expect(editCopy()).toHaveAttribute("href", "/studio/packs/new?from=order-payment-reconciliation");
  });

  it("offers no copy when copyable is missing, the user cannot build, or the workspace is not live", () => {
    state.live = true;
    const { unmount } = renderWithIntl(<PackPage slug="order-payment-reconciliation" />);
    expect(editCopy()).toBeNull();
    unmount();
    state.extra = { copyable: true };
    state.role = "member";
    const second = renderWithIntl(<PackPage slug="order-payment-reconciliation" />);
    expect(editCopy()).toBeNull();
    second.unmount();
    state.role = "owner";
    state.live = false;
    renderWithIntl(<PackPage slug="order-payment-reconciliation" />);
    expect(editCopy()).toBeNull();
  });
});

describe("PackPage costs", () => {
  const costs = () => screen.getByRole("heading", { name: "What it costs" }).closest("section")!;
  const agentsTools = () => within(costs()).getByText("Agents and tools").parentElement!;

  it("shows the price note as the estimate and the contract budget as a cap, not a range from zero", () => {
    state.live = true;
    state.extra = {
      estimate: { aiMin: usd(0), aiMax: usd(3000), humanMax: usd(0) },
      priceNote: "About $0.80 to $3.00 of AI work per run. No reviewer time: you approve the actions yourself.",
    };
    renderWithIntl(<PackPage slug="order-to-cash-exception-desk" />);
    expect(agentsTools()).toHaveTextContent("About $0.80 to $3.00 of AI work per run.");
    expect(within(agentsTools()).getByText("Up to $30.00 per run (cap)")).toBeInTheDocument();
    expect(costs().textContent).not.toMatch(/\$0\.00/);
  });

  it("shows only the cap when a pack has no price note and its estimate starts at zero", () => {
    state.extra = { estimate: { aiMin: usd(0), aiMax: usd(3000), humanMax: usd(0) } };
    renderWithIntl(<PackPage slug="order-to-cash-exception-desk" />);
    expect(within(agentsTools()).getByText("Up to $30.00 per run (cap)")).toBeInTheDocument();
    expect(costs().textContent).not.toMatch(/\$0\.00/);
  });

  it("keeps a catalog estimate range that does not start at zero, with no cap line", () => {
    renderWithIntl(<PackPage slug="order-payment-reconciliation" />);
    expect(within(agentsTools()).getByText("$0.60–$2.40 per run")).toBeInTheDocument();
    expect(within(costs()).queryByText(/\(cap\)/)).toBeNull();
  });

  it("says usage-based when there is neither an estimate nor a cap", () => {
    state.extra = { estimate: { aiMin: usd(0), aiMax: usd(0), humanMax: usd(0) } };
    renderWithIntl(<PackPage slug="order-payment-reconciliation" />);
    expect(agentsTools()).toHaveTextContent("Usage-based");
  });

  it("writes the cap in Japanese", () => {
    state.extra = { estimate: { aiMin: usd(0), aiMax: usd(3000), humanMax: usd(0) } };
    renderWithIntl(<PackPage slug="order-to-cash-exception-desk" />, { locale: "ja" });
    expect(screen.getByText(/1回の実行あたり最大.*30\.00.*（上限）/)).toBeInTheDocument();
  });

  it("names the contract's reviewer budget as a cap, apart from the price note's typical reviewer time", () => {
    state.extra = {
      estimate: { aiMin: usd(60), aiMax: usd(240), humanMax: usd(2000) },
      priceNote:
        "About $0.60 to $2.40 of AI work per run, plus up to $7.50 of reviewer time when a mismatch needs a person.",
    };
    const { unmount } = renderWithIntl(<PackPage slug="order-payment-reconciliation" />);
    expect(within(costs()).getByText("Reviewer pay cap").parentElement).toHaveTextContent("Up to $20.00 per run");
    expect(within(costs()).queryByText("Reviewer pay")).toBeNull();
    unmount();
    renderWithIntl(<PackPage slug="order-payment-reconciliation" />, { locale: "ja" });
    expect(screen.getByText("レビュアー報酬の上限").parentElement).toHaveTextContent(/1回の実行あたり最大.*20\.00/);
  });

  it("says there is no reviewer pay by default when the contract budgets none, naming no cap", () => {
    state.extra = { estimate: { aiMin: usd(0), aiMax: usd(3000), humanMax: usd(0) } };
    const { unmount } = renderWithIntl(<PackPage slug="order-to-cash-exception-desk" />);
    expect(within(costs()).getByText("Reviewer pay").parentElement).toHaveTextContent("None by default");
    expect(within(costs()).queryByText("Reviewer pay cap")).toBeNull();
    unmount();
    renderWithIntl(<PackPage slug="order-to-cash-exception-desk" />, { locale: "ja" });
    expect(screen.getByText("レビュアー報酬").parentElement).toHaveTextContent("既定ではなし");
    expect(screen.queryByText("レビュアー報酬の上限")).toBeNull();
  });
});
