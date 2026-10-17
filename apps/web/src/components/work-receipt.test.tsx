import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { WorkReceipt } from "./work-receipt";

const state = vi.hoisted(() => ({ query: {} as Record<string, unknown> }));
vi.mock("@/lib/queries/runs", () => ({ useReceipt: () => state.query }));

const receipt = {
  runId: "run_9",
  verified: true,
  entries: 14,
  headHash: "0123456789abcdef0123456789abcdef",
  pinned: [
    { kind: "workflow", key: "order-payment-reconciliation", version: 3, digest: "sha256:aa" },
    { kind: "agent", key: "reconciler", version: 2, digest: "sha256:bb" },
  ],
  items: [],
};

describe("WorkReceipt", () => {
  it("shows the verified badge, entry count, short head hash and pinned versions", () => {
    state.query = { data: receipt };
    renderWithIntl(<WorkReceipt runId="run_9" status="COMPLETED" />);
    expect(screen.getByRole("heading", { name: "Work receipt" })).toBeInTheDocument();
    expect(screen.getByText("Verified")).toBeInTheDocument();
    expect(screen.getByText("14")).toBeInTheDocument();
    expect(screen.getByText("0123456789ab")).toBeInTheDocument();
    expect(screen.queryByText(/0123456789abc/)).not.toBeInTheDocument();
    expect(screen.getByText("order-payment-reconciliation")).toBeInTheDocument();
    expect(screen.getByText("v2")).toBeInTheDocument();
  });

  it("keeps the hash and pinned versions under technical details, and folds the panel on a phone", () => {
    state.query = { data: receipt };
    renderWithIntl(<WorkReceipt runId="run_9" status="COMPLETED" />);
    expect(screen.getByText("0123456789ab").closest("details")).not.toBeNull();
    expect(screen.getByText("order-payment-reconciliation").closest("details")).not.toBeNull();
    const toggle = screen.getByRole("button", { name: "Show Work receipt" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Hide Work receipt" })).toHaveAttribute("aria-expanded", "true");
  });

  it("flags a chain that fails verification", () => {
    state.query = { data: { ...receipt, verified: false } };
    renderWithIntl(<WorkReceipt runId="run_9" status="COMPLETED" />);
    expect(screen.getByText("Not verified")).toBeInTheDocument();
  });

  it("renders nothing while loading or when the run has no receipt", () => {
    for (const q of [
      { isSuccess: false, isPending: true },
      { isSuccess: false, isError: true },
    ]) {
      state.query = q;
      const { container, unmount } = renderWithIntl(<WorkReceipt runId="run_1042" status="COMPLETED" />);
      expect(container).toBeEmptyDOMElement();
      unmount();
    }
  });

  it("keeps showing the receipt when a background refetch fails", () => {
    state.query = { isError: true, data: receipt };
    renderWithIntl(<WorkReceipt runId="run_9" status="RUNNING" />);
    expect(screen.getByText("Verified so far")).toBeInTheDocument();
  });

  // QA3 #6: the chip read "Verified" while the run was still writing to the chain.
  it("says the chain is verified so far while the run is going, and verified once it is finished", () => {
    state.query = { data: receipt };
    for (const status of ["RUNNING", "WAITING_FOR_HUMAN", "WAITING_FOR_EVENT", "VERIFYING"] as const) {
      const { unmount } = renderWithIntl(<WorkReceipt runId="run_9" status={status} />);
      expect(screen.getByText("Verified so far")).toBeInTheDocument();
      unmount();
    }
    for (const status of ["COMPLETED", "FAILED", "CANCELLED"] as const) {
      const { unmount } = renderWithIntl(<WorkReceipt runId="run_9" status={status} />);
      expect(screen.getByText("Verified")).toBeInTheDocument();
      unmount();
    }
    const { unmount } = renderWithIntl(<WorkReceipt runId="run_9" status="RUNNING" />, { locale: "ja" });
    expect(screen.getByText("ここまで検証済み")).toBeInTheDocument();
    unmount();
    state.query = { data: { ...receipt, verified: false } };
    renderWithIntl(<WorkReceipt runId="run_9" status="RUNNING" />);
    expect(screen.getByText("Not verified")).toBeInTheDocument();
  });

  it("names each pinned kind in words, and shows an unknown kind as sent", () => {
    const pinned = [...receipt.pinned, { kind: "future_kind", key: "x", version: 1, digest: "sha256:cc" }];
    state.query = { data: { ...receipt, pinned } };
    renderWithIntl(<WorkReceipt runId="run_9" status="COMPLETED" />);
    expect(screen.getByText("Workflow")).toBeInTheDocument();
    expect(screen.getByText("Agent")).toBeInTheDocument();
    expect(screen.queryByText("workflow")).not.toBeInTheDocument();
    expect(screen.getByText("future_kind")).toBeInTheDocument();
  });

  it("speaks Japanese", () => {
    state.query = { data: receipt };
    renderWithIntl(<WorkReceipt runId="run_9" status="COMPLETED" />, { locale: "ja" });
    expect(screen.getByRole("heading", { name: "作業レシート" })).toBeInTheDocument();
    expect(screen.getByText("ワークフロー")).toBeInTheDocument();
  });
});
