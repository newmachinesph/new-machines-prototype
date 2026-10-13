import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { StartRunPage } from "./start-run-page";

const url = vi.hoisted(() => ({ pack: null as string | null }));
vi.mock("nuqs", () => ({ useQueryState: () => [url.pack] }));

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
const usd = (amountMinor: number) => ({ amountMinor, currency: "USD" });
const data = vi.hoisted(() => ({
  packs: [] as unknown[],
  conns: [] as unknown[],
  org: { monthlyCap: { amountMinor: 25000, currency: "USD" }, monthSpent: { amountMinor: 100, currency: "USD" } },
}));
const RECON = {
  slug: "order-payment-reconciliation",
  name: "Order & Payment Reconciliation",
  installed: true,
  connectors: [{ app: "Shopify" }, { app: "Stripe" }],
};
const LOCALIZATION = {
  slug: "catalog-localization-en-ja",
  name: "Catalog Localization",
  installed: false,
  connectors: [],
};
vi.mock("@/lib/queries/catalog", () => ({ usePacks: () => ok(data.packs) }));
vi.mock("@/lib/queries/org", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/queries/org")>()),
  useConnections: () => ok(data.conns),
  useOrg: () => ok(data.org),
}));
// The form itself is covered by start-run-form.test.tsx; here only what it is given matters.
vi.mock("./start-run-form", () => ({
  StartRunForm: ({
    packs,
    defaultPack,
    blocked,
  }: {
    packs: { slug: string; inputs: string[]; perRunCap?: { amountMinor: number } }[];
    defaultPack?: string;
    blocked: Record<string, { text: string; href?: string } | undefined>;
  }) => (
    <div>
      <p>
        form with {packs.map((p) => p.slug).join(" ")}, preselecting {defaultPack ?? "nothing"}
      </p>
      {packs.map((p) => (
        <p key={p.slug}>
          {p.slug} inputs: {p.inputs.join(", ") || "none"}; cap: {p.perRunCap?.amountMinor ?? "none"}
        </p>
      ))}
      {Object.entries(blocked).map(([slug, r]) => (
        <p key={slug}>
          blocked {slug}: {r?.text} ({r?.href})
        </p>
      ))}
    </div>
  ),
}));

const connection = (app: string, status: string) => ({ app, status, provider: "Mock", grants: [], oauthScopes: [] });

describe("StartRunPage", () => {
  beforeEach(() => {
    url.pack = null;
    data.packs = [RECON, LOCALIZATION];
    data.conns = [connection("Shopify", "sandbox"), connection("Stripe", "connected")];
    data.org = { monthlyCap: usd(25000), monthSpent: usd(100) };
  });

  it("starts nothing when no pack is hired, and links to the marketplace", () => {
    data.packs = [LOCALIZATION];
    renderWithIntl(<StartRunPage />);
    expect(screen.getByRole("status")).toHaveTextContent("Hire a pack before starting a run.");
    expect(screen.getByRole("link", { name: "See all packs" })).toHaveAttribute("href", "/app/marketplace");
    expect(screen.queryByText(/form with/)).not.toBeInTheDocument();
  });

  it("does not block a pack whose apps are connected, sandbox included", () => {
    renderWithIntl(<StartRunPage />);
    expect(screen.queryByText(/blocked/)).not.toBeInTheDocument();
  });

  it("blocks a pack whose apps are not connected and links to connections", () => {
    data.conns = [connection("Shopify", "not_connected")];
    renderWithIntl(<StartRunPage />);
    expect(
      screen.getByText(
        "blocked order-payment-reconciliation: Connect Shopify and Stripe before starting a run of Order & Payment Reconciliation. (/app/connections)",
      ),
    ).toBeInTheDocument();
  });

  it("blocks every pack once the month's spend reaches the cap and links to usage", () => {
    data.org = { monthlyCap: usd(25000), monthSpent: usd(25000) };
    renderWithIntl(<StartRunPage />);
    expect(
      screen.getByText(/blocked order-payment-reconciliation: .*reached the \$250\.00 monthly cap/),
    ).toHaveTextContent("(/app/usage)");
  });

  it("preselects a hired pack from the link without a notice", () => {
    url.pack = "order-payment-reconciliation";
    renderWithIntl(<StartRunPage />);
    expect(screen.getByText(/preselecting order-payment-reconciliation/)).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("explains a pack that isn't hired and links to its marketplace page", () => {
    url.pack = "catalog-localization-en-ja";
    renderWithIntl(<StartRunPage />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Catalog Localization isn't hired yet, so it can't start a run.",
    );
    expect(screen.getByRole("link", { name: "Hire this pack" })).toHaveAttribute(
      "href",
      "/app/marketplace/catalog-localization-en-ja",
    );
    expect(screen.getByText(/form with order-payment-reconciliation, preselecting nothing/)).toBeInTheDocument();
  });

  it("explains an unknown pack and links to the marketplace", () => {
    url.pack = "no-such-pack";
    renderWithIntl(<StartRunPage />);
    expect(screen.getByRole("status")).toHaveTextContent("There is no pack called no-such-pack.");
    expect(screen.getByRole("link", { name: "See all packs" })).toHaveAttribute("href", "/app/marketplace");
  });

  it("shows the notice in Japanese", () => {
    url.pack = "catalog-localization-en-ja";
    renderWithIntl(<StartRunPage />, { locale: "ja" });
    expect(screen.getByRole("status")).toHaveTextContent("Catalog Localizationはまだ採用されていないため");
    expect(screen.getByRole("link", { name: "このパックを採用" })).toBeInTheDocument();
  });

  it("offers inputs from sandbox apps too, and passes each pack's per-run cap", () => {
    data.packs = [{ ...RECON, connectors: [{ app: "Google Sheets" }], perRunCap: usd(2000) }];
    data.conns = [connection("Google Sheets", "sandbox")];
    renderWithIntl(<StartRunPage />);
    expect(
      screen.getByText(
        "order-payment-reconciliation inputs: Google Sheets: Orders Oct 11, Google Sheets: Stripe payouts, October; cap: 2000",
      ),
    ).toBeInTheDocument();
  });
});
