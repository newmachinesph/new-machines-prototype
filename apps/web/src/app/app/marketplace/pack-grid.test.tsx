import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { PackGrid } from "./pack-grid";

const url = vi.hoisted(() => ({ initial: {} as Record<string, string> }));
vi.mock("nuqs", () => ({
  parseAsString: { withDefault: (d: string) => ({ d }) },
  useQueryState: (key: string, parser: { d: string }) => {
    const [v, set] = useState<string | null>(url.initial[key] ?? null);
    return [v ?? parser.d, set];
  },
}));

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
const estimate = {
  aiMin: { amountMinor: 1, currency: "USD" },
  aiMax: { amountMinor: 2, currency: "USD" },
  humanMax: { amountMinor: 0, currency: "USD" },
};
const pack = (
  slug: string,
  name: string,
  industries: string[],
  category = "Operations",
  over: Record<string, unknown> = {},
) => ({
  slug,
  name,
  outcome: `${name} outcome`,
  publisher: "New Machines",
  category,
  version: "1.0.0",
  installed: false,
  certified: true,
  agents: [],
  connectors: [],
  estimate,
  industries,
  ...over,
});
const mocked = (app: string) => ({ app, access: "read", mocked: true });
const retail = { id: "retail", name: "Retail" };
const health = { id: "healthcare", name: "Healthcare" };

vi.mock("@/lib/queries/catalog", () => ({
  usePacks: () =>
    ok([
      pack("recon", "Reconciliation", ["retail"], "Operations", { connectors: [mocked("Shopify"), mocked("Stripe")] }),
      pack("claims", "Claims intake", ["healthcare"], "Operations", {
        connectors: [mocked("Gmail"), { app: "Google Sheets", access: "read" }],
        estimate: {
          ...estimate,
          aiMin: { amountMinor: 0, currency: "USD" },
          aiMax: { amountMinor: 0, currency: "USD" },
        },
      }),
      pack("misc", "Misc", []),
      pack("audit", "Retail audit", ["retail"], "Finance"),
    ]),
  useAgents: () => ok([]),
  useAgentById: () => () => undefined,
  useTaxonomy: () => ok({ functions: [], industries: [retail, health] }),
}));

const me = vi.hoisted(() => ({ role: "owner", workspace: "demo" }));
vi.mock("@/lib/queries/me", () => ({
  useMe: () => ok(me),
  useIsLive: () => me.workspace === "live",
}));

describe("PackGrid industry filter", () => {
  beforeEach(() => {
    url.initial = {};
    me.role = "owner";
    me.workspace = "demo";
  });

  it("shows every pack under All industries by default", () => {
    renderWithIntl(<PackGrid />);
    expect(screen.getByRole("button", { name: /All industries/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Reconciliation")).toBeInTheDocument();
    expect(screen.getByText("Claims intake")).toBeInTheDocument();
    expect(screen.getByText("Misc")).toBeInTheDocument();
  });

  it("narrows to the chosen industry and goes back on All industries", async () => {
    const user = userEvent.setup();
    renderWithIntl(<PackGrid />);
    await user.click(screen.getByRole("button", { name: /Healthcare/ }));
    expect(screen.getByText("Claims intake")).toBeInTheDocument();
    expect(screen.queryByText("Reconciliation")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /All industries/ }));
    expect(screen.getByText("Reconciliation")).toBeInTheDocument();
  });

  it("starts from the industry in the URL", () => {
    url.initial = { industry: "retail" };
    renderWithIntl(<PackGrid />);
    expect(screen.getByRole("button", { name: /Retail/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("Claims intake")).not.toBeInTheDocument();
  });

  it("combines industry with category and search", async () => {
    const user = userEvent.setup();
    renderWithIntl(<PackGrid />);
    await user.click(screen.getByRole("button", { name: /Retail/ }));
    expect(screen.getByText("Reconciliation")).toBeInTheDocument();
    expect(screen.getByText("Retail audit")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Finance/ }));
    expect(screen.queryByText("Reconciliation")).not.toBeInTheDocument();
    expect(screen.getByText("Retail audit")).toBeInTheDocument();
    await user.type(screen.getByRole("searchbox"), "zzz");
    expect(screen.getByText("No pack matches.")).toBeInTheDocument();
  });

  it("clears the industry with Show all packs", async () => {
    const user = userEvent.setup();
    renderWithIntl(<PackGrid />);
    await user.click(screen.getByRole("button", { name: /Healthcare/ }));
    await user.type(screen.getByRole("searchbox"), "zzz");
    await user.click(screen.getByRole("button", { name: "Show all packs" }));
    expect(screen.getByRole("button", { name: /All industries/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Reconciliation")).toBeInTheDocument();
  });

  it("reads a stale Built by your team view as All packs when the org has no team pack", () => {
    url.initial = { category: "Built by your team" };
    renderWithIntl(<PackGrid />);
    expect(screen.queryByRole("button", { name: /Built by your team/ })).toBeNull();
    expect(screen.getByRole("button", { name: /^All packs/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Reconciliation")).toBeInTheDocument();
    expect(screen.getByText("Claims intake")).toBeInTheDocument();
  });

  it("renders no badge column on a card with nothing to badge", () => {
    renderWithIntl(<PackGrid />);
    // Certified, not added, not the team's: the corner that would hold a badge is not there to take space.
    const card = screen.getByRole("link", { name: /Reconciliation/ });
    expect(within(card).queryByTestId("pack-badges")).toBeNull();
  });

  it("keeps the views, functions and industries in one filter bar", () => {
    renderWithIntl(<PackGrid />);
    const nav = screen.getByRole("navigation", { name: "Filter packs" });
    expect(within(nav).getByRole("group", { name: "Show" })).toBeInTheDocument();
    expect(within(nav).getByRole("group", { name: "Function" })).toBeInTheDocument();
    const industry = within(nav).getByRole("group", { name: "Industry" });
    expect(within(industry).getByRole("button", { name: /^Healthcare/ })).toHaveTextContent("1");
    expect(within(industry).getByRole("button", { name: /^All industries/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("says Sandbox mock once for a card whose apps are all mocks, and per app otherwise", () => {
    renderWithIntl(<PackGrid />);
    const recon = screen.getByRole("link", { name: /Reconciliation/ });
    expect(within(recon).getAllByText("Sandbox mock")).toHaveLength(1);
    expect(within(recon).getByText("Shopify")).toBeInTheDocument();
    expect(within(recon).getByText("Stripe")).toBeInTheDocument();
    const claims = screen.getByRole("link", { name: /Claims intake/ });
    expect(within(claims).getByText("Gmail")).toContainElement(within(claims).getByText("Sandbox mock"));
    expect(within(claims).getByText("Google Sheets")).not.toContainElement(within(claims).getByText("Sandbox mock"));
  });

  it("says a pack with a zero estimate has no price set, never $0.00–$0.00", () => {
    renderWithIntl(<PackGrid />);
    expect(within(screen.getByRole("link", { name: /Claims intake/ })).getByText("Price not set")).toBeInTheDocument();
    expect(within(screen.getByRole("link", { name: /Misc/ })).getByText("$0.01–$0.02 per run")).toBeInTheDocument();
    expect(screen.queryByText(/\$0\.00–\$0\.00/)).toBeNull();
  });

  it("labels the chips in Japanese", () => {
    renderWithIntl(<PackGrid />, { locale: "ja" });
    expect(screen.getByRole("button", { name: /すべての業界/ })).toBeInTheDocument();
  });

  it("points owners and admins of a live workspace to the Developer Studio to build a pack", () => {
    const build = () => screen.queryByRole("link", { name: "Build a pack" });
    me.workspace = "live";
    const { unmount } = renderWithIntl(<PackGrid />);
    expect(build()).toHaveAttribute("href", "/studio/packs/new");
    unmount();
    me.role = "member"; // members only read in the Studio
    const second = renderWithIntl(<PackGrid />);
    expect(build()).toBeNull();
    second.unmount();
    me.role = "owner";
    me.workspace = "demo"; // the demo has no Studio
    renderWithIntl(<PackGrid />);
    expect(build()).toBeNull();
  });
});
