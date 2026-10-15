import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { ApprovalsView } from "./approvals/approvals-view";
import { MemoryBoard } from "./memory/memory-items";
import { RunsList } from "./runs/runs-list";

const empty = { isPending: false, isError: false, data: [] };

vi.mock("@/lib/queries/runs", () => ({ useRuns: () => empty }));
vi.mock("@/lib/queries/workspace", () => ({
  useApprovals: () => empty,
  useMemory: () => empty,
  useRetractMemory: () => ({ mutate: vi.fn() }),
  useReviewMemory: () => ({ mutate: vi.fn() }),
  useDecideApproval: () => ({ mutate: vi.fn() }),
}));

describe("empty lists in a new workspace", () => {
  it("runs: points at starting a run", () => {
    renderWithIntl(<RunsList />);
    expect(
      screen.getByText("No runs yet. Start a run of one of your packs and follow its work here."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start a run" })).toHaveAttribute("href", "/app/runs/new");
  });

  it("approvals: says nothing is waiting, links to runs and drops the empty history", () => {
    renderWithIntl(<ApprovalsView />);
    expect(screen.getByText(/Nothing is waiting for your approval/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See runs" })).toHaveAttribute("href", "/app/runs");
    expect(screen.queryByRole("heading", { name: "Earlier" })).not.toBeInTheDocument();
  });

  it("memory: explains how memories arrive", () => {
    renderWithIntl(<MemoryBoard />);
    expect(screen.getByText(/No memories yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See runs" })).toHaveAttribute("href", "/app/runs");
  });

  it("speaks Japanese", () => {
    renderWithIntl(<RunsList />, { locale: "ja" });
    expect(screen.getByRole("link", { name: "実行を開始" })).toBeInTheDocument();
  });
});
