import { screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { PackGrid } from "./pack-grid";
import { shortPriceNote } from "./per-run";

vi.mock("nuqs", () => ({
  parseAsString: { withDefault: (d: string) => ({ d }) },
  useQueryState: (_key: string, parser: { d: string }) => {
    const [v, set] = useState<string | null>(null);
    return [v ?? parser.d, set];
  },
}));

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
const usd = (amountMinor: number) => ({ amountMinor, currency: "USD" });
// The live API's estimate for a pack definition: 0 to the contract's budget cap.
const capOnly = { aiMin: usd(0), aiMax: usd(3000), humanMax: usd(0) };
const NOTE = "About $0.80 to $3.00 of AI work per run. No reviewer time: you approve the actions yourself.";
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
  estimate: capOnly,
  industries: [],
  ...over,
});
const listing = {
  listingId: "lst_1",
  publisher: "Acme Labs",
  fee: { amountMinor: 250, currency: "USD" },
  feeUnit: "run",
  version: 2,
};

vi.mock("@/lib/queries/catalog", () => ({
  usePacks: () =>
    ok([
      pack("o2c", "Exception desk", { priceNote: NOTE }),
      pack("bare", "Bare cap"),
      pack("listed", "Listed cap", { listing }),
      // A contract whose reviewer budget uses up its maximum leaves no cap for agents and tools.
      pack("uncapped", "Uncapped note", {
        priceNote: NOTE,
        estimate: { aiMin: usd(0), aiMax: usd(0), humanMax: usd(2000) },
      }),
    ]),
  useAgents: () => ok([]),
  useAgentById: () => () => undefined,
  useTaxonomy: () => ok({ functions: [], industries: [] }),
}));

vi.mock("@/lib/queries/me", () => ({ useMe: () => ({ data: { role: "owner" } }), useIsLive: () => true }));

const cost = (name: RegExp) => within(screen.getByRole("link", { name })).getByTestId("pack-cost");

describe("PackGrid cost per run", () => {
  it("shows the price note's estimate and the cap, never a range from $0.00", () => {
    renderWithIntl(<PackGrid />);
    expect(cost(/Exception desk/)).toHaveTextContent("About $0.80 to $3.00 of AI work per run.");
    expect(cost(/Exception desk/)).not.toHaveTextContent("No reviewer time");
    expect(within(cost(/Exception desk/)).getByText("Up to $30.00 per run (cap)")).toBeInTheDocument();
    expect(cost(/Bare cap/)).toHaveTextContent(/^Up to \$30\.00 per run \(cap\)$/);
    expect(document.body.textContent).not.toMatch(/\$0\.00/);
  });

  it("gives a pack with a note but no cap the cap line too, saying none is set", () => {
    renderWithIntl(<PackGrid />);
    expect(cost(/Uncapped note/)).toHaveTextContent("About $0.80 to $3.00 of AI work per run.");
    expect(within(cost(/Uncapped note/)).getByText("No per-run cap set")).toBeInTheDocument();
    expect(cost(/Uncapped note/)).not.toHaveTextContent("Usage-based");
  });

  it("says a listed pack's fee comes on top of the cap", () => {
    renderWithIntl(<PackGrid />);
    expect(cost(/Listed cap/)).toHaveTextContent("Up to $30.00 per run (cap), plus the fee");
  });

  it("writes the cap in Japanese", () => {
    renderWithIntl(<PackGrid />, { locale: "ja" });
    expect(cost(/Bare cap/)).toHaveTextContent(/1回の実行あたり最大\$30\.00（上限）/);
  });
});

describe("shortPriceNote", () => {
  it("keeps the sentence that names an amount, without splitting on a decimal point", () => {
    expect(shortPriceNote(NOTE)).toBe("About $0.80 to $3.00 of AI work per run.");
    expect(shortPriceNote("Built by your team. Up to $5.00 of AI work per run.")).toBe(
      "Up to $5.00 of AI work per run.",
    );
    expect(shortPriceNote("Not priced yet")).toBe("Not priced yet");
  });
});
