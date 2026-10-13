import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Pack } from "@/lib/types";
import { renderWithIntl } from "@/test/intl";
import { InstallReview } from "./install-review";

vi.mock("@/components/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/base")>()),
  useToast: () => vi.fn(),
}));
const install = vi.hoisted(() => vi.fn());
vi.mock("@/lib/queries/me", () => ({ useOrgId: () => "org_new" }));
vi.mock("@/lib/queries/catalog", () => ({
  useAgentById: () => (id: string) =>
    id === "finance-agent" ? { id, name: "Finance Agent", capabilities: ["finance.reconcile"] } : undefined,
  useInstallPack: () => ({ mutate: install, isPending: false }),
}));

const usd = (amountMinor: number) => ({ amountMinor, currency: "USD" as const });
const pack = {
  slug: "order-payment-reconciliation",
  name: "Order & Payment Reconciliation",
  version: "1.0.0",
  publisher: "New Machines Labs",
  category: "Finance operations",
  outcome: "Every order matched.",
  description: "Matches orders to payments.",
  agents: ["finance-agent", "ops-agent"],
  connectors: [{ app: "Google Sheets", access: "write (approval)" }],
  humanReview: "Mismatches go to a reviewer.",
  estimate: { aiMin: usd(60), aiMax: usd(240), humanMax: usd(750) },
  installed: false,
  certified: true,
  riskClass: "medium",
  regions: ["asia-south1"],
} satisfies Pack;

describe("InstallReview agents", () => {
  it("links each agent the pack hires to its agent page", () => {
    renderWithIntl(<InstallReview pack={pack} />);
    expect(screen.getByRole("link", { name: "Finance Agent" })).toHaveAttribute("href", "/app/agents/finance-agent");
    // An agent the catalog does not know still links, by its id.
    expect(screen.getByRole("link", { name: "ops-agent" })).toHaveAttribute("href", "/app/agents/ops-agent");
    expect(screen.getByText("finance.reconcile")).toBeInTheDocument();
  });
});

describe("InstallReview hiring", () => {
  it("hires into the signed-in user's org", async () => {
    renderWithIntl(<InstallReview pack={pack} />);
    await userEvent.click(screen.getByRole("checkbox", { name: /agree/i }));
    await userEvent.click(screen.getByRole("button", { name: /^Hire / }));
    expect(install).toHaveBeenCalledWith(
      { path: { org_id: "org_new" }, body: { packSlug: pack.slug, capMinor: 2000, reviewerPool: true } },
      expect.anything(),
    );
  });
});
