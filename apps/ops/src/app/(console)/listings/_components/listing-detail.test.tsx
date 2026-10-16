import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UiProviders } from "@/components/base";
import { ListingDetail } from "./listing-detail";

const state = vi.hoisted(() => ({
  data: undefined as unknown,
  workspace: "live" as "demo" | "live",
  mePending: false,
}));
vi.mock("@/lib/queries/ops", () => ({
  useMe: () => ({ isPending: state.mePending, isError: false, data: state.mePending ? undefined : {} }),
  useOpsWorkspace: () => state.workspace,
  useCanWrite: () => true,
}));
vi.mock("@/lib/queries/listings", () => ({
  useListing: () => ({ isPending: false, isError: false, data: state.data }),
  useListingAction: () => ({ run: vi.fn() }),
}));

const version = {
  id: "v1",
  definitionVersion: 2,
  status: "in_review",
  price: { amountMinor: 500, currency: "USD" },
  checks: [
    { name: "definition", state: "passed", detail: "Definition is valid" },
    { name: "sandbox", state: "failed", detail: "Run failed on step 2", runId: "run-9" },
  ],
  submittedAt: "2026-10-12T10:00:00Z",
  submittedBy: "dev@acme.test",
};

const detail = (over: Record<string, unknown> = {}) => ({
  id: "l1",
  kind: "pack",
  key: "invoice-chaser",
  name: "Invoice chaser",
  publisher: "Acme Labs",
  publisherOrgId: "o1",
  status: "pending",
  price: { amountMinor: 500, currency: "USD" },
  updatedAt: "2026-10-12T10:00:00Z",
  pending: version,
  versions: [version],
  diff: [],
  history: [{ at: "2026-10-12T11:00:00Z", by: "ops@nm.test", action: "request_changes", note: "Fix the prompt" }],
  ...over,
});

const renderDetail = () =>
  render(
    <UiProviders>
      <ListingDetail listingId="l1" />
    </UiProviders>,
  );

describe("ListingDetail", () => {
  beforeEach(() => {
    state.workspace = "live";
    state.mePending = false;
    state.data = detail();
  });

  it("shows a skeleton, not the demo message, while the profile loads", () => {
    state.workspace = "demo";
    state.mePending = true;
    renderDetail();
    expect(screen.queryByText("Listings are part of the live workspace.")).toBeNull();
  });

  it("shows the waiting version's price for a pending listing with no listed price", () => {
    state.data = detail({ price: { amountMinor: 0, currency: "USD" } });
    renderDetail();
    expect(screen.getAllByText(/\$5\.00 per run/).length).toBeGreaterThan(0);
    expect(screen.queryByText("No fee")).toBeNull();
  });

  it("says per call for an agent", () => {
    state.data = detail({ kind: "agent" });
    renderDetail();
    expect(screen.getAllByText(/\$5\.00 per call/).length).toBeGreaterThan(0);
  });

  it("labels both prices when a listed listing has a pending version at another price", () => {
    state.data = detail({ status: "listed", price: { amountMinor: 300, currency: "USD" } });
    renderDetail();
    expect(screen.getByText("Listed price")).toBeInTheDocument();
    expect(screen.getByText("Price in review")).toBeInTheDocument();
    expect(screen.getAllByText("$3.00 per run").length).toBeGreaterThan(0);
  });

  it("keeps one Price when the pending version has the same price", () => {
    state.data = detail({ status: "listed" });
    renderDetail();
    expect(screen.queryByText("Price in review")).toBeNull();
    expect(screen.queryByText("Listed price")).toBeNull();
    expect(screen.getAllByText("$5.00 per run").length).toBeGreaterThan(0);
  });

  it("falls back to the latest version's price when nothing is waiting", () => {
    state.data = detail({ pending: undefined, price: { amountMinor: 0, currency: "USD" } });
    renderDetail();
    expect(screen.getAllByText(/\$5\.00 per run/).length).toBeGreaterThan(0);
  });

  it("says a version is reviewable once checks pass", () => {
    state.data = detail({ pending: { ...version, status: "checking" } });
    renderDetail();
    expect(screen.getByText("Reviewable once checks pass")).toBeInTheDocument();
  });

  it("shows the header and the checks with a sandbox run link", () => {
    renderDetail();
    expect(screen.getByRole("heading", { level: 1, name: /Invoice chaser/ })).toBeInTheDocument();
    expect(screen.getByText("Definition is valid")).toBeInTheDocument();
    expect(screen.getByText("Run failed on step 2")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /sandbox run/i })).toHaveAttribute("href", "/runs/run-9");
  });

  it("shows each diff as a block with its unified text", () => {
    state.data = detail({
      diff: [{ kind: "agent", key: "writer", path: "prompt", change: "changed", unified: "-old line\n+new line" }],
    });
    renderDetail();
    expect(screen.getByText(/\+new line/)).toBeInTheDocument();
  });

  it("says there is nothing to compare for a first version", () => {
    renderDetail();
    expect(screen.getByText("First version: nothing to compare.")).toBeInTheDocument();
  });

  it("lists the history in words", () => {
    renderDetail();
    expect(screen.getByText("Requested changes")).toBeInTheDocument();
    expect(screen.getByText("Fix the prompt")).toBeInTheDocument();
    expect(screen.getByText("ops@nm.test")).toBeInTheDocument();
  });

  it("explains listings are live-only in the demo", () => {
    state.workspace = "demo";
    renderDetail();
    expect(screen.getByRole("heading", { level: 1, name: "Listing" })).toBeInTheDocument();
    expect(screen.getByText("Listings are part of the live workspace.")).toBeInTheDocument();
  });
});
