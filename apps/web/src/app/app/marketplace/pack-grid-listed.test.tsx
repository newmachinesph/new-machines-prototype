import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { PackGrid } from "./pack-grid";

vi.mock("nuqs", () => ({
  parseAsString: { withDefault: (d: string) => ({ d }) },
  useQueryState: (_key: string, parser: { d: string }) => {
    const [v, set] = useState<string | null>(null);
    return [v ?? parser.d, set];
  },
}));

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
const estimate = {
  aiMin: { amountMinor: 1, currency: "USD" },
  aiMax: { amountMinor: 2, currency: "USD" },
  humanMax: { amountMinor: 0, currency: "USD" },
};
const listing = (fee: number, feeUnit: "run" | "call") => ({
  listingId: "lst_1",
  publisher: "Harbor Cafe",
  fee: { amountMinor: fee, currency: "USD" },
  feeUnit,
  version: 2,
});
const pack = (slug: string, name: string, over: Record<string, unknown> = {}) => ({
  slug,
  name,
  outcome: `${name} outcome`,
  publisher: "New Machines",
  category: "Finance",
  version: "1.0.0",
  installed: false,
  certified: true,
  agents: [],
  connectors: [],
  estimate,
  industries: [],
  ...over,
});
const agent = (id: string, name: string, over: Record<string, unknown> = {}) => ({
  id,
  name,
  version: "1.0.0",
  publisher: "New Machines Labs",
  summary: `${name} summary`,
  capabilities: [],
  usedBy: [],
  ...over,
});

const shown = vi.hoisted(() => ({ listedAgents: true }));
vi.mock("@/lib/queries/catalog", () => ({
  usePacks: () =>
    ok([
      pack("recon", "Reconciliation"),
      pack("tax-pack", "Tax filing", { publisher: "Harbor Cafe", certified: false, listing: listing(250, "run") }),
      pack("payroll", "Payroll", {
        publisher: "Harbor Cafe",
        certified: false,
        installed: true,
        listing: listing(0, "run"),
      }),
    ]),
  useAgents: () =>
    ok([
      agent("finance-agent", "Finance Agent"),
      ...(shown.listedAgents
        ? [agent("tax-agent", "Tax Agent", { publisher: "Harbor Cafe", listing: listing(30, "call") })]
        : []),
    ]),
  useAgentById: () => () => undefined,
  useTaxonomy: () => ok({ functions: [], industries: [] }),
}));
vi.mock("@/lib/queries/me", () => ({ useMe: () => ({ data: { role: "owner" } }), useIsLive: () => false }));

describe("PackGrid listed packs and agents", () => {
  beforeEach(() => {
    shown.listedAgents = true;
  });

  it("gives the Packs and Agents switch its own name", () => {
    renderWithIntl(<PackGrid />);
    expect(screen.getByRole("group", { name: "Show packs or agents" })).toBeInTheDocument();
  });

  it("has no Agents view in the demo when no agent is listed", () => {
    shown.listedAgents = false;
    renderWithIntl(<PackGrid />);
    expect(screen.queryByRole("button", { name: "Agents" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Show packs or agents" })).toBeNull();
  });

  it("shows the publisher and fee of a listed pack instead of the certified badge", () => {
    renderWithIntl(<PackGrid />);
    const card = screen.getByRole("link", { name: /Tax filing/ });
    expect(within(card).getByText("By Harbor Cafe")).toBeInTheDocument();
    expect(within(card).getByText("$2.50 per run")).toBeInTheDocument();
    // The estimate says the fee comes on top, so the card does not show two prices for one run.
    expect(within(card).getByText("$0.01–$0.02 per run, plus the fee")).toBeInTheDocument();
    expect(within(card).queryByText("Not yet certified")).toBeNull();
    // Packs that are not listed keep their card as it was.
    expect(within(screen.getByRole("link", { name: /Reconciliation/ })).queryByText(/^By /)).toBeNull();
  });

  it("keeps the fee on a listed pack that is already added", () => {
    renderWithIntl(<PackGrid />);
    const card = screen.getByRole("link", { name: /Payroll/ });
    expect(within(card).getByText("Added")).toBeInTheDocument();
    expect(within(card).getByText("By Harbor Cafe")).toBeInTheDocument();
    expect(within(card).getByText("No fee")).toBeInTheDocument();
  });

  it("lists only listed agents in the Agents view, without the pack filters", async () => {
    renderWithIntl(<PackGrid />);
    expect(screen.getByRole("navigation", { name: "Filter packs" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Agents" }));
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.getByRole("link", { name: "Tax Agent" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Finance Agent" })).toBeNull();
    expect(screen.queryByRole("link", { name: /Tax filing/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Packs" }));
    expect(screen.getByRole("link", { name: /Tax filing/ })).toBeInTheDocument();
  });
});
