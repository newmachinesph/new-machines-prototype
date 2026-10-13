import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import type { OpsRunDetail } from "@/lib/api/gen/types.gen";
import { RunDetail } from "./run-detail";

const usd = (amountMinor: number) => ({ amountMinor, currency: "USD" as const });
const HASH = "a3f9c2e17b4d8e90aa11bb22cc33dd44ee55ff66778899aabbccddeeff001122";

const detail = (verified: boolean): OpsRunDetail => ({
  run: {
    id: "run_7",
    packSlug: "order-payment-reconciliation",
    title: "Order & Payment Reconciliation",
    status: "WAITING_FOR_HUMAN",
    startedAt: "2026-10-13T09:00:00Z",
    startedBy: "owner@harborpine.co",
    input: "Last 7 days",
    workflowRef: "order-payment-reconciliation@3",
    contractRef: "order-payment-reconciliation@1",
    budget: usd(2500),
    spent: { ai: usd(142), human: usd(0), tools: usd(0) },
    stages: { executed: "pending", verified: "pending", accepted: "pending", settlement: "not_required" },
    summary: "Two mismatches wait for a reviewer.",
    nodes: [
      {
        id: "orders",
        type: "connector",
        label: "Read orders",
        actor: "machine",
        status: "COMPLETED",
        x: 0,
        y: 0,
        toolCalls: [
          {
            id: "tc_1",
            app: "Shopify",
            action: "list_orders",
            capability: "orders.read",
            status: "CONFIRMED",
            policy: "PERMIT",
            detail: "12 orders",
            mocked: true,
          },
        ],
      },
      {
        id: "check",
        type: "decision",
        label: "Check mismatches",
        actor: "policy",
        status: "COMPLETED",
        x: 1,
        y: 0,
        decision: {
          question: "Do the orders and payments match?",
          evaluator: { kind: "rules", label: "recon-exceptions", configVersion: "1" },
          chain: [],
          verdict: "HUMAN_REVIEW",
          reasonCodes: ["MISMATCH_WITHIN_TOLERANCE"],
          explanation: "Two mismatches need a person.",
          evidenceRefs: [],
          route: "review",
          evaluatedAt: "2026-10-13T09:01:00Z",
          policy: { id: "p1", ref: "policy/default", verdict: "PERMIT", reasonCodes: [], actor: "system" },
        },
      },
      {
        id: "review",
        type: "human_workforce",
        label: "Review mismatches",
        actor: "human",
        status: "WAITING",
        x: 2,
        y: 0,
      },
    ],
    edges: [],
    timeline: [],
  },
  receipt: {
    runId: "run_7",
    verified,
    entries: 2,
    headHash: HASH,
    pinned: [{ kind: "workflow", key: "order-payment-reconciliation", version: 3, digest: HASH }],
    items: [
      { seq: 1, at: "2026-10-13T09:00:00Z", type: "run.started", summary: "Run started", hash: HASH },
      {
        seq: 2,
        at: "2026-10-13T09:00:05Z",
        type: "node.completed",
        nodeId: "orders",
        summary: "orders done",
        hash: HASH,
      },
    ],
  },
});

const state = vi.hoisted(() => ({ query: {} as Record<string, unknown> }));
vi.mock("@/lib/queries/runs", () => ({ useOpsRun: () => state.query }));
const ok = (data: unknown) => ({ isPending: false, isError: false, data });

describe("RunDetail", () => {
  beforeEach(() => {
    state.query = ok(detail(true));
  });

  it("summarises the run: status, spend against budget and each step", () => {
    render(<RunDetail id="run_7" />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Order & Payment Reconciliation");
    expect(screen.getByText("Waiting for a reviewer")).toBeInTheDocument();
    // AI work and the total.
    expect(screen.getAllByText("$1.42")).toHaveLength(2);
    expect(screen.getByText("$25.00")).toBeInTheDocument();

    const steps = screen.getByRole("table", { name: "Steps" });
    const review = within(steps).getByText("Review mismatches").closest("tr")!;
    expect(within(review).getByText("Waiting")).toBeInTheDocument();
    const check = within(steps).getByText("Check mismatches").closest("tr")!;
    expect(within(check).getByText("Human review")).toBeInTheDocument();
    expect(within(check).getByText("Two mismatches need a person.")).toBeInTheDocument();
  });

  it("tags simulated tool calls", () => {
    render(<RunDetail id="run_7" />);
    const orders = within(screen.getByRole("table", { name: "Steps" }))
      .getByText("Read orders")
      .closest("tr")!;
    expect(within(orders).getByText("Shopify list_orders")).toBeInTheDocument();
    expect(within(orders).getByText("Simulated")).toBeInTheDocument();
  });

  it("shows the receipt chain with hash prefixes and a Verified badge", () => {
    render(<RunDetail id="run_7" />);
    expect(screen.getByText("Verified")).toBeInTheDocument();
    const receipt = screen.getByRole("table", { name: "Receipt entries" });
    expect(within(receipt).getAllByText("a3f9c2e17b4d")).toHaveLength(2);
    expect(within(receipt).getByText("run.started")).toBeInTheDocument();
    expect(within(receipt).queryByText(HASH)).toBeNull();
    expect(screen.getByRole("link", { name: "workflow/order-payment-reconciliation v3" })).toHaveAttribute(
      "href",
      "/definitions/workflow/order-payment-reconciliation?version=3",
    );
  });

  it("says when the chain does not verify", () => {
    state.query = ok(detail(false));
    render(<RunDetail id="run_7" />);
    expect(screen.getByText("Not verified")).toBeInTheDocument();
    expect(screen.queryByText("Verified")).toBeNull();
  });

  it("explains that only real runs have a receipt", () => {
    state.query = {
      isPending: false,
      isError: true,
      error: new ApiError(404, "NOT_FOUND", "No real run run_x001."),
    };
    render(<RunDetail id="run_x001" />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("No real run run_x001");
  });
});
