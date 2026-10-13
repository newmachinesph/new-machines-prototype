import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Approval } from "@/lib/types";
import { renderWithIntl } from "@/test/intl";
import { ApprovalCard } from "./approval-card";

const state = vi.hoisted(() => ({ toast: vi.fn() }));
vi.mock("@/lib/queries/workspace", () => ({
  useDecideApproval: () => ({
    mutate: (_vars: unknown, opts?: { onSuccess?: () => void }) => opts?.onSuccess?.(),
  }),
}));
vi.mock("@/components/base", async (orig) => ({ ...(await orig<object>()), useToast: () => state.toast }));

const base = {
  id: "apr_run_2001_approve_write_1",
  runId: "run_2001",
  title: "Write the reconciliation report to the Sheet",
  requestedBy: "Order & Payment Reconciliation",
  requestedAt: "2026-10-13T10:00:00Z",
  expiresAt: "2026-10-14T10:00:00Z",
  status: "PENDING",
  policyRef: "policy/default",
  reasonCodes: ["APPROVAL_REQUIRED"],
  digest: [{ label: "Run", value: "run_2001", mono: true }],
} satisfies Partial<Approval>;

const real = (mocked: boolean, status: Approval["status"] = "PENDING"): Approval => ({
  ...base,
  status,
  action: {
    app: "Google Sheets",
    step: "write",
    tool: "googlesheets.append_rows",
    operation: "append rows",
    summary: "12 orders reconciled.",
    mocked,
  },
});

const fixture: Approval = {
  ...base,
  id: "apr_311",
  preview: { to: "ap@fernway-goods.example", subject: "Invoice INV-3281 is past due", body: "Hello" },
};

describe("ApprovalCard", () => {
  beforeEach(() => state.toast.mockClear());

  it("shows a real run's step as an action, not an email", () => {
    renderWithIntl(<ApprovalCard approval={real(false)} onDecide={() => {}} />);
    expect(screen.getByRole("heading", { name: "Action" })).toBeInTheDocument();
    expect(screen.getByText("Google Sheets")).toBeInTheDocument();
    expect(screen.getByText("write")).toBeInTheDocument();
    expect(screen.getByText("12 orders reconciled.")).toBeInTheDocument();
    expect(screen.queryByText(/email/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Simulated")).not.toBeInTheDocument();
    expect(screen.getByText(/Declining stops the run/)).toBeInTheDocument();
  });

  it("labels the step simulated only when its call is mocked", () => {
    renderWithIntl(<ApprovalCard approval={real(true)} onDecide={() => {}} />);
    expect(within(screen.getByRole("heading", { name: /Action/ })).getByText("Simulated")).toBeInTheDocument();
    expect(screen.getByText("Runs against sandbox data. Nothing changes in Google Sheets.")).toBeInTheDocument();
  });

  it("toasts the step, not an email, when a live step is approved", async () => {
    const user = userEvent.setup();
    renderWithIntl(<ApprovalCard approval={real(false)} onDecide={() => {}} />);
    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(state.toast).toHaveBeenCalledWith("Approved", "The run goes on with this step in Google Sheets.");
  });

  it("says simulated in the toast when the approved step is mocked", async () => {
    const user = userEvent.setup();
    renderWithIntl(<ApprovalCard approval={real(true)} onDecide={() => {}} />);
    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(state.toast).toHaveBeenCalledWith(
      "Approved",
      "The run goes on with this step. Simulated: nothing changes in Google Sheets.",
      "sim",
    );
  });

  it("says the run stops when a real approval is declined", async () => {
    const user = userEvent.setup();
    renderWithIntl(<ApprovalCard approval={real(false)} onDecide={() => {}} />);
    await user.click(screen.getByRole("button", { name: "Decline" }));
    expect(state.toast).toHaveBeenCalledWith("Declined", "The run stops here. Nothing was changed in Google Sheets.");
  });

  it("shows the outcome of a decided real approval without a made-up content hash", () => {
    const { unmount } = renderWithIntl(<ApprovalCard approval={real(false, "DECLINED")} onDecide={() => {}} />);
    expect(screen.getByText("Declined. The run stops here.")).toBeInTheDocument();
    unmount();
    renderWithIntl(<ApprovalCard approval={real(false, "GRANTED")} onDecide={() => {}} />);
    expect(screen.getByText("Approved. The run goes on with this step.")).toBeInTheDocument();
    expect(screen.queryByText(/sha256/)).not.toBeInTheDocument();
  });

  it("keeps the email preview for demo approvals", () => {
    renderWithIntl(<ApprovalCard approval={fixture} onDecide={() => {}} />);
    expect(screen.getByRole("heading", { name: "The email, exactly as it will be sent" })).toBeInTheDocument();
    expect(screen.getByText("ap@fernway-goods.example")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve and send" })).toBeInTheDocument();
  });

  it("speaks Japanese", () => {
    renderWithIntl(<ApprovalCard approval={real(true)} onDecide={() => {}} />, { locale: "ja" });
    expect(screen.getByRole("heading", { name: /アクション/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "承認" })).toBeInTheDocument();
  });
});
