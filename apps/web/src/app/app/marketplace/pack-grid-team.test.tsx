import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
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

vi.mock("@/lib/queries/catalog", () => ({
  usePacks: () =>
    ok([
      pack("recon", "Reconciliation"),
      pack("org-a1--nudges", "Invoice nudges", { publisher: "Harbor Cafe", certified: false, builtByTeam: true }),
    ]),
  useAgents: () => ok([]),
  useAgentById: () => () => undefined,
  useTaxonomy: () => ok({ functions: [], industries: [] }),
}));

describe("PackGrid team packs", () => {
  it("labels a team pack and offers a Built by your team view", async () => {
    renderWithIntl(<PackGrid />);
    const card = screen.getByRole("link", { name: /Invoice nudges/ });
    expect(within(card).getByText("Built by your team")).toBeInTheDocument();
    expect(within(card).queryByText("Not yet certified")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Built by your team/ }));
    expect(screen.getByRole("link", { name: /Invoice nudges/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Reconciliation/ })).toBeNull();
  });

  it("labels a team pack in Japanese", () => {
    renderWithIntl(<PackGrid />, { locale: "ja" });
    const card = screen.getByRole("link", { name: /Invoice nudges/ });
    expect(within(card).getByText("チームが作成")).toBeInTheDocument();
  });
});
