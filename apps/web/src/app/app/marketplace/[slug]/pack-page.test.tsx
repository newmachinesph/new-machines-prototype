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
const state = vi.hoisted(() => ({ installed: false, live: false, extra: {} as Record<string, unknown> }));
vi.mock("@/lib/queries/me", () => ({ useIsLive: () => state.live }));
vi.mock("@/lib/queries/catalog", () => ({
  usePack: () => ok({ ...pack, installed: state.installed, ...state.extra }),
  useAgents: () => ok(agents),
  useAgentById: () => (id: string) => agents.find((a) => a.id === id),
}));

afterEach(() => {
  state.installed = false;
  state.live = false;
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
