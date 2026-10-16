import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UiProviders } from "@/components/base";
import { ListingsView } from "./listings-view";

const state = vi.hoisted(() => ({
  tab: null as string | null,
  workspace: "live" as "demo" | "live",
  mePending: false,
  rows: [] as unknown[],
  useListings: vi.fn(),
}));

vi.mock("nuqs", () => ({
  parseAsStringLiteral: () => ({}),
  useQueryState: () => [state.tab, vi.fn()],
}));
vi.mock("@/lib/queries/ops", () => ({
  useMe: () => ({ isPending: state.mePending, isError: false, data: state.mePending ? undefined : {} }),
  useOpsWorkspace: () => state.workspace,
}));
vi.mock("@/lib/queries/listings", () => ({
  useListings: (status?: string) => {
    state.useListings(status);
    return { isPending: false, isError: false, data: state.rows };
  },
}));

const row = (over: Record<string, unknown> = {}) => ({
  id: "l1",
  kind: "pack",
  key: "invoice-chaser",
  name: "Invoice chaser",
  publisher: "Acme Labs",
  publisherOrgId: "o1",
  status: "pending",
  price: { amountMinor: 250, currency: "USD" },
  updatedAt: "2026-10-12T10:00:00Z",
  pending: {
    id: "v1",
    definitionVersion: 3,
    status: "in_review",
    price: { amountMinor: 250, currency: "USD" },
    checks: [],
  },
  ...over,
});

const renderView = () =>
  render(
    <UiProviders>
      <ListingsView />
    </UiProviders>,
  );

describe("ListingsView", () => {
  beforeEach(() => {
    state.tab = null;
    state.workspace = "live";
    state.mePending = false;
    state.rows = [];
    state.useListings.mockClear();
  });

  it("shows a skeleton, not the demo message, while the profile loads", () => {
    state.workspace = "demo";
    state.mePending = true;
    renderView();
    expect(screen.queryByText("Listings are part of the live workspace.")).toBeNull();
    expect(state.useListings).not.toHaveBeenCalled();
  });

  it("requests in_review on the default tab", () => {
    renderView();
    expect(state.useListings).toHaveBeenCalledWith("in_review");
  });

  it("requests every status on the All tab", () => {
    state.tab = "all";
    renderView();
    expect(state.useListings).toHaveBeenCalledWith(undefined);
  });

  it("renders publisher, price and the waiting version", () => {
    const free = { amountMinor: 0, currency: "USD" };
    state.rows = [
      row(),
      row({
        id: "l2",
        name: "Free helper",
        price: free,
        pending: { id: "v2", definitionVersion: 3, status: "in_review", price: free, checks: [] },
      }),
    ];
    renderView();
    expect(screen.getAllByText("Acme Labs").length).toBe(2);
    expect(screen.getByText("$2.50 per run")).toBeInTheDocument();
    expect(screen.getByText("No fee")).toBeInTheDocument();
    expect(screen.getAllByText("v3").length).toBe(2);
  });

  it("shows the waiting version's price for a pending listing, per call for an agent", () => {
    state.rows = [
      row({
        kind: "agent",
        price: { amountMinor: 0, currency: "USD" },
        pending: { id: "v1", definitionVersion: 1, status: "in_review", price: { amountMinor: 250, currency: "USD" } },
      }),
    ];
    renderView();
    expect(screen.getByText("$2.50 per call")).toBeInTheDocument();
    expect(screen.queryByText("No fee")).toBeNull();
  });

  it("describes submitters as workspaces", () => {
    renderView();
    expect(screen.getByText(/Listings that workspaces have submitted/)).toBeInTheDocument();
  });

  it("shows the empty state", () => {
    renderView();
    expect(screen.getByText("Nothing waiting for review.")).toBeInTheDocument();
  });

  it("says listings belong to the live workspace in the demo", () => {
    state.workspace = "demo";
    renderView();
    expect(screen.getByText("Listings are part of the live workspace.")).toBeInTheDocument();
  });
});
