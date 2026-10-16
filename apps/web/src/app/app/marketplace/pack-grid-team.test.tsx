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
      pack("org-a1--nudges", "Invoice nudges", {
        publisher: "Harbor Cafe",
        certified: false,
        builtByTeam: true,
        version: "1.0.1",
        agents: ["org-5c8192d7129c2fa2-qa-inbox-reader-a2"],
      }),
    ]),
  useAgents: () => ok([]),
  useAgentById: () => () => undefined,
  useTaxonomy: () => ok({ functions: [], industries: [] }),
}));

vi.mock("@/lib/queries/me", () => ({ useMe: () => ({ data: { role: "owner" } }), useIsLive: () => true }));

describe("PackGrid team packs", () => {
  it("labels a team pack and offers a Built by your team view", async () => {
    renderWithIntl(<PackGrid />);
    const card = screen.getByRole("link", { name: /Invoice nudges/ });
    expect(within(card).getByText("Built by your team")).toBeInTheDocument();
    expect(within(card).queryByText("Not yet certified")).toBeNull();
    // The badge sits in the card's corner; a card with nothing to badge has no corner (see pack-grid.test).
    expect(within(card).getByTestId("pack-badges")).toContainElement(within(card).getByText("Built by your team"));
    expect(within(screen.getByRole("link", { name: /Reconciliation/ })).queryByTestId("pack-badges")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Built by your team/ }));
    expect(screen.getByRole("link", { name: /Invoice nudges/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Reconciliation/ })).toBeNull();
  });

  // QA F-12 and F-16: a team pack's card showed its agent's raw key (with the org id) and version 1.0.1.
  it("never shows a team pack's agent key, and shows its definition version", () => {
    renderWithIntl(<PackGrid />);
    const card = screen.getByRole("link", { name: /Invoice nudges/ });
    expect(card.textContent).not.toMatch(/5c8192d7129c2fa2|qa-inbox-reader/);
    expect(card.textContent).not.toMatch(/1\.0\.1/);
  });

  it("labels a team pack in Japanese", () => {
    renderWithIntl(<PackGrid />, { locale: "ja" });
    const card = screen.getByRole("link", { name: /Invoice nudges/ });
    expect(within(card).getByText("チームが作成")).toBeInTheDocument();
  });
});
