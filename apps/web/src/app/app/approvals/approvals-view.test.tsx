import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Approval } from "@/lib/types";
import { renderWithIntl } from "@/test/intl";
import { ApprovalsView } from "./approvals-view";

const past = (id: string, runId: string): Approval => ({
  id,
  runId,
  title: "Write the reconciliation report to the Sheet",
  requestedBy: "Order & Payment Reconciliation",
  requestedAt: "2026-10-13T10:00:00Z",
  expiresAt: "2026-10-14T10:00:00Z",
  status: "GRANTED",
  policyRef: "policy/default",
  reasonCodes: ["APPROVAL_REQUIRED"],
  digest: [],
});

vi.mock("@/lib/queries/workspace", () => ({
  useApprovals: () => ({
    isPending: false,
    isError: false,
    data: [past("apr_1", "run_2011"), past("apr_2", "run_2011"), past("apr_3", "run_2010")],
  }),
  useDecideApproval: () => ({ mutate: () => {} }),
}));
vi.mock("@/lib/queries/runs", () => ({
  useRuns: () => ({
    isPending: false,
    isError: false,
    data: [{ id: "run_2011", title: "October reconciliation", startedAt: "2026-10-12T09:00:00Z" }],
  }),
}));

describe("ApprovalsView", () => {
  it("groups earlier approvals under a link to their run", () => {
    renderWithIntl(<ApprovalsView />);
    const earlier = screen.getByRole("heading", { name: "Earlier" }).closest("section") ?? document.body;
    const groups = within(earlier).getAllByRole("list")[0];
    const [known, unknown] = within(groups)
      .getAllByRole("listitem")
      .filter((li) => li.parentElement === groups);

    const link = within(known).getByRole("link", { name: /^October reconciliation, .*Oct.*12/ });
    expect(link).toHaveAttribute("href", "/app/runs/run_2011");
    expect(within(known).getAllByText("Write the reconciliation report to the Sheet")).toHaveLength(2);
    expect(within(known).getAllByText(/Approved by you/)).toHaveLength(2);

    // A run the list does not know still gets a link to it.
    expect(within(unknown).getByRole("link", { name: /^Open the run, .*Oct.*13/ })).toHaveAttribute(
      "href",
      "/app/runs/run_2010",
    );
  });
});
