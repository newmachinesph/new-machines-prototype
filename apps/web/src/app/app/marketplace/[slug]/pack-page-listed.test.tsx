import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import { renderWithIntl } from "@/test/intl";
import { PackPage } from "./pack-page";

vi.mock("next/navigation", () => ({ notFound: vi.fn() }));
vi.mock("./sandbox-trial", () => ({ SandboxTrial: () => null, TRIAL_ID: "sandbox-trial" }));

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
const usd = (amountMinor: number) => ({ amountMinor, currency: "USD" });
const basePack = {
  slug: "tax-pack",
  name: "Tax filing",
  version: "3.0.0",
  publisher: "Harbor Cafe",
  category: "Finance operations",
  outcome: "Taxes filed.",
  description: "Files taxes.",
  agents: [],
  connectors: [],
  humanReview: "A reviewer checks.",
  estimate: { aiMin: usd(60), aiMax: usd(240), humanMax: usd(0) },
  installed: true,
  certified: false,
  riskClass: "medium",
  regions: ["asia-south1"],
};
const listing = (over: Record<string, unknown> = {}) => ({
  listingId: "lst_1",
  publisher: "Harbor Cafe",
  fee: usd(250),
  feeUnit: "run",
  version: 3,
  installedVersion: 2,
  updateAvailable: true,
  ...over,
});

const state = vi.hoisted(() => ({
  listing: undefined as Record<string, unknown> | undefined,
  upgrade: vi.fn(),
  toast: vi.fn(),
}));
vi.mock("@/lib/queries/me", () => ({ useIsLive: () => true, useMe: () => ({ data: { role: "owner" } }) }));
vi.mock("@/components/base", async (orig) => ({
  ...(await orig<typeof import("@/components/base")>()),
  useToast: () => state.toast,
}));
vi.mock("@/lib/queries/catalog", () => ({
  usePack: () => ok({ ...basePack, listing: state.listing }),
  useAgents: () => ok([]),
  useAgentById: () => () => undefined,
  useUpgradePack: () => ({ upgrade: state.upgrade, isPending: false, ready: true }),
}));

afterEach(() => {
  state.listing = undefined;
  state.upgrade.mockReset();
  state.toast.mockReset();
});

describe("PackPage listed pack", () => {
  it("shows the fee in the costs, the publisher once in the header, and no callout without an update", () => {
    state.listing = listing({ updateAvailable: false, installedVersion: 3 });
    renderWithIntl(<PackPage slug="tax-pack" />);
    const costs = screen.getByRole("heading", { name: "What it costs" }).closest("section")!;
    expect(within(costs).getByText("$2.50 per run")).toBeInTheDocument();
    expect(within(costs).queryByText("Harbor Cafe")).toBeNull();
    expect(screen.getAllByText(/Harbor Cafe/)).toHaveLength(1);
    expect(screen.queryByText("Update available")).toBeNull();
  });

  it("shows the update callout only when an update is available", () => {
    state.listing = listing();
    renderWithIntl(<PackPage slug="tax-pack" />);
    expect(screen.getByText("Update available")).toBeInTheDocument();
    expect(screen.getByText("Version 3 is available. Runs keep using version 2 until you update.")).toBeInTheDocument();
  });

  it("asks before updating, then calls the mutation and toasts", async () => {
    state.listing = listing();
    state.upgrade.mockImplementation((o: { onSuccess: () => void }) => o.onSuccess());
    renderWithIntl(<PackPage slug="tax-pack" />);
    await userEvent.click(screen.getByRole("button", { name: "Update" }));
    expect(state.upgrade).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Update" }));
    await waitFor(() => expect(state.upgrade).toHaveBeenCalledTimes(1));
    expect(state.toast).toHaveBeenCalledWith("Updated to version 3.");
  });

  it("shows the detail of a 409", async () => {
    state.listing = listing();
    const detail = "Wait for its runs to finish, then update.";
    state.upgrade.mockImplementation((o: { onError: (e: unknown) => void }) =>
      o.onError(new ApiError(409, "RUNS_IN_PROGRESS", detail)),
    );
    renderWithIntl(<PackPage slug="tax-pack" />);
    await userEvent.click(screen.getByRole("button", { name: "Update" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Update" }));
    await waitFor(() => expect(state.toast).toHaveBeenCalledWith(detail, undefined, "blocked"));
  });
});
