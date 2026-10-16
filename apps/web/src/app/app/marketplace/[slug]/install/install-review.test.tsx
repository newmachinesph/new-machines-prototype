import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Pack } from "@/lib/types";
import { renderWithIntl } from "@/test/intl";
import { InstallReview } from "./install-review";

const toast = vi.hoisted(() => vi.fn());
vi.mock("@/components/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/base")>()),
  useToast: () => toast,
}));
const install = vi.hoisted(() => vi.fn());
const state = vi.hoisted(() => ({ live: false, allowNetwork: true }));
vi.mock("@/lib/queries/me", () => ({ useOrgId: () => "org_new", useIsLive: () => state.live }));
vi.mock("@/lib/queries/reviewers", () => ({
  useOrgReviewers: () => ({ data: { allowNetwork: state.allowNetwork, reviewers: [] } }),
}));
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
const hired = { ...pack, installed: true, perRunCap: usd(5000), reviewerPool: "network" as const };
const body = (over: object = {}) => ({
  path: { org_id: "org_new" },
  body: { packSlug: pack.slug, capMinor: 2000, reviewerPool: "team_then_network", ...over },
});
const summary = () => screen.getByRole("heading", { name: "Summary" }).closest("section")!;

beforeEach(() => {
  install.mockReset();
  toast.mockClear();
  state.live = false;
  state.allowNetwork = true;
});

describe("InstallReview agents", () => {
  it("links each agent the pack uses to its agent page", () => {
    renderWithIntl(<InstallReview pack={pack} />);
    expect(screen.getByRole("link", { name: "Finance Agent" })).toHaveAttribute("href", "/app/agents/finance-agent");
    // An agent the catalog does not know still links, by its id.
    expect(screen.getByRole("link", { name: "ops-agent" })).toHaveAttribute("href", "/app/agents/ops-agent");
  });

  it("lists the capabilities requested as plain labels", () => {
    renderWithIntl(<InstallReview pack={pack} />);
    expect(screen.getByText("Payment reconciliation")).toBeInTheDocument();
    expect(screen.queryByText("finance.reconcile")).toBeNull();
  });
});

describe("InstallReview spending cap", () => {
  it("offers the caps as a radio group with the default checked", () => {
    renderWithIntl(<InstallReview pack={pack} />);
    const group = screen.getByRole("group", { name: "Spending cap per run" });
    expect(within(group).getAllByRole("radio")).toHaveLength(3);
    expect(within(group).getByRole("radio", { name: "$20.00" })).toBeChecked();
    expect(group).toHaveAccessibleDescription(/A run stops and asks you/);
  });

  it("offers no cap above the pack's maximum budget, with the maximum among them", () => {
    const capped = { ...pack, maxBudget: { amountMinor: 1000, currency: "USD" as const } };
    renderWithIntl(<InstallReview pack={capped} />);
    const group = screen.getByRole("group", { name: "Spending cap per run" });
    expect(within(group).getAllByRole("radio")).toHaveLength(2);
    expect(within(group).getByRole("radio", { name: "$5.00" })).toBeInTheDocument();
    expect(within(group).getByRole("radio", { name: "$10.00" })).toBeChecked();
  });

  it("folds the chosen cap into the summary's price line and sends it", async () => {
    renderWithIntl(<InstallReview pack={pack} />);
    expect(
      within(summary()).getByText("$0.60–$2.40 plus reviewer pay. A run stops and asks you above $20.00"),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "$50.00" }));
    expect(screen.getByRole("radio", { name: "$50.00" })).toBeChecked();
    expect(
      within(summary()).getByText("$0.60–$2.40 plus reviewer pay. A run stops and asks you above $50.00"),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: /agree/i }));
    await userEvent.click(screen.getByRole("button", { name: /^Add / }));
    expect(install).toHaveBeenCalledWith(body({ capMinor: 5000 }), expect.anything());
  });

  it("says a pack with no agent price is unset rather than $0.00–$0.00", () => {
    const free = { ...pack, estimate: { aiMin: usd(0), aiMax: usd(0), humanMax: usd(750) } };
    renderWithIntl(<InstallReview pack={free} />);
    expect(
      within(summary()).getByText("Agent price not set, plus reviewer pay. A run stops and asks you above $20.00"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/\$0\.00–\$0\.00/)).toBeNull();
  });

  it("does not repeat the cap and reviewer choices as summary rows", () => {
    renderWithIntl(<InstallReview pack={pack} />);
    expect(within(summary()).queryByText("Cap")).toBeNull();
    expect(within(summary()).queryByText("Human reviewers")).toBeNull();
    expect(within(summary()).getByText("Pinned. Updates need your approval.")).toBeInTheDocument();
  });
});

describe("InstallReview adding a pack", () => {
  it("adds the pack to the signed-in user's org with the team first, then the network", async () => {
    renderWithIntl(<InstallReview pack={pack} />);
    expect(screen.getByRole("radio", { name: /^Your team first, then the network/ })).toBeChecked();
    await userEvent.click(screen.getByRole("checkbox", { name: /agree/i }));
    await userEvent.click(screen.getByRole("button", { name: /^Add / }));
    expect(install).toHaveBeenCalledWith(body(), expect.anything());
  });

  it("can keep reviews inside the team", async () => {
    renderWithIntl(<InstallReview pack={pack} />);
    await userEvent.click(screen.getByRole("radio", { name: /^Your team only/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /agree/i }));
    await userEvent.click(screen.getByRole("button", { name: /^Add / }));
    expect(install).toHaveBeenCalledWith(body({ reviewerPool: "team" }), expect.anything());
  });

  it("offers the three reviewer pools in the demo too", () => {
    renderWithIntl(<InstallReview pack={pack} />);
    expect(screen.getAllByRole("radio")).toHaveLength(3 + 3); // three caps, three pools
    expect(screen.getByRole("radio", { name: /^The New Machines reviewer network/ })).toBeInTheDocument();
  });

  it("says the network is off when the workspace does not allow it", () => {
    state.live = true;
    state.allowNetwork = false;
    renderWithIntl(<InstallReview pack={pack} />);
    expect(screen.getByText(/The reviewer network is off for your workspace/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Reviewers" })).toHaveAttribute("href", "/app/reviewers");
  });

  it("says nothing about the network being off when the team reviews alone", async () => {
    state.live = true;
    state.allowNetwork = false;
    renderWithIntl(<InstallReview pack={pack} />);
    await userEvent.click(screen.getByRole("radio", { name: /^Your team only/ }));
    expect(screen.queryByText(/The reviewer network is off/)).toBeNull();
    expect(screen.getByRole("radio", { name: /^Your team only/ })).toBeChecked();
  });

  it("does not say the network is off in the demo", () => {
    state.allowNetwork = false;
    renderWithIntl(<InstallReview pack={pack} />);
    expect(screen.queryByText(/The reviewer network is off/)).toBeNull();
  });
});

describe("InstallReview pack settings", () => {
  it("starts from the pack's cap and pool and saves without agreeing again", async () => {
    state.live = true;
    renderWithIntl(<InstallReview pack={hired} settings />);
    expect(screen.getByRole("radio", { name: "$50.00" })).toBeChecked();
    expect(screen.getByRole("radio", { name: /^The New Machines reviewer network/ })).toBeChecked();
    expect(screen.queryByRole("checkbox", { name: /agree/i })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Save pack settings" }));
    expect(install).toHaveBeenCalledWith(body({ capMinor: 5000, reviewerPool: "network" }), expect.anything());
  });

  it("keeps a saved cap above what a run can use, says so, and saves it unchanged", async () => {
    state.live = true;
    const over = { ...hired, maxBudget: usd(1000), perRunCap: usd(5000) };
    renderWithIntl(<InstallReview pack={over} settings />);
    expect(screen.getByRole("radio", { name: "$50.00" })).toBeChecked();
    expect(screen.getByText("Runs of this pack can use at most $10.00.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save pack settings" }));
    expect(install).toHaveBeenCalledWith(body({ capMinor: 5000, reviewerPool: "network" }), expect.anything());
  });

  it("says the settings could not be saved, not that the pack could not be added", async () => {
    state.live = true;
    install.mockImplementationOnce((_vars, opts: { onError: (e: Error) => void }) => opts.onError(new Error("x")));
    renderWithIntl(<InstallReview pack={hired} settings />);
    await userEvent.click(screen.getByRole("button", { name: "Save pack settings" }));
    expect(toast).toHaveBeenCalledWith("Could not save the pack settings", expect.anything(), "blocked");
  });

  it("says the network is off in the settings too", () => {
    state.live = true;
    state.allowNetwork = false;
    renderWithIntl(<InstallReview pack={hired} settings />);
    expect(screen.getByText(/The reviewer network is off for your workspace/)).toBeInTheDocument();
  });

  it("asks for the agreement when not in settings mode, even for an added pack", () => {
    renderWithIntl(<InstallReview pack={hired} />);
    expect(screen.getByRole("checkbox", { name: /agree/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save pack settings" })).toBeNull();
  });

  it("never uses the add wording in the settings", () => {
    state.live = true;
    renderWithIntl(<InstallReview pack={hired} settings />, { locale: "ja" });
    expect(screen.getByRole("button", { name: "パックの設定を保存" })).toBeInTheDocument();
    expect(screen.queryByText(/採用|追加/)).toBeNull();
  });

  it("shows a listed pack's publisher fee beside the estimate, added to every run", () => {
    const listed = {
      ...pack,
      listing: { listingId: "lst_1", publisher: "Harbor Cafe", fee: usd(250), feeUnit: "run" as const, version: 2 },
    };
    renderWithIntl(<InstallReview pack={listed} />);
    const fee = within(summary()).getByText("Fee").parentElement as HTMLElement;
    expect(fee).toHaveTextContent("$2.50 per run");
    expect(fee).toHaveTextContent("Added to every run, on top of the estimate");
    expect(fee).toHaveTextContent("Simulated");
  });

  it("shows no fee row for a pack without a fee", () => {
    renderWithIntl(<InstallReview pack={pack} />);
    expect(within(summary()).queryByText("Fee")).toBeNull();
  });
});
