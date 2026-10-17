import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Approval } from "@/lib/types";
import { renderWithIntl } from "@/test/intl";
import { ApprovalCard } from "./approval-card";

const state = vi.hoisted(() => ({ toast: vi.fn(), demo: true }));
vi.mock("@/lib/queries/me", () => ({ useIsDemo: () => state.demo }));
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
  beforeEach(() => {
    state.toast.mockClear();
    state.demo = true;
  });

  it("shows a real run's step as an action, not an email", () => {
    renderWithIntl(<ApprovalCard approval={real(false)} onDecide={() => {}} />);
    expect(screen.getByRole("heading", { name: "Action" })).toBeInTheDocument();
    // QA3 #2: the action reads "App: Tool name", never the tool's id.
    expect(screen.getByText("Google Sheets: Append rows")).toBeInTheDocument();
    expect(screen.queryByText("googlesheets.append_rows")).not.toBeInTheDocument();
    expect(screen.getByText("write")).toBeInTheDocument();
    expect(screen.getByText("12 orders reconciled.")).toBeInTheDocument();
    expect(screen.queryByText(/email/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Simulated")).not.toBeInTheDocument();
    expect(screen.getByText(/Declining stops the run/)).toBeInTheDocument();
  });

  it("drops the step row when the step is the app's own step", () => {
    // The run page labels an app step "App: <tool id as words>", which need not match the tool's name.
    const approval = real(false);
    approval.action = { ...approval.action!, step: "Google Sheets: append rows", operation: "Add rows" };
    renderWithIntl(<ApprovalCard approval={approval} onDecide={() => {}} />);
    expect(screen.queryByText("Step")).not.toBeInTheDocument();
    expect(screen.queryByText("Google Sheets: append rows")).not.toBeInTheDocument();
    expect(screen.getByText("Google Sheets: Add rows")).toBeInTheDocument();
  });

  it("names the digest in the interface language, with the policy line from a key", () => {
    const approval = real(false);
    approval.digest = [
      { label: "Run", value: "October reconciliation" },
      { label: "Policy", value: "Your workspace's policy requires approval before this step writes to your apps." },
      { label: "Decided by", value: "Ana" },
    ];
    const { unmount } = renderWithIntl(<ApprovalCard approval={approval} onDecide={() => {}} />);
    expect(screen.getByText("Run").nextElementSibling).toHaveTextContent("October reconciliation");
    expect(screen.getByText("Policy").nextElementSibling).toHaveTextContent(/^Your workspace's policy requires/);
    expect(screen.getByText("Decided by").nextElementSibling).toHaveTextContent("Ana");
    unmount();
    renderWithIntl(<ApprovalCard approval={approval} onDecide={() => {}} />, { locale: "ja" });
    expect(screen.getByText("実行").nextElementSibling).toHaveTextContent("October reconciliation");
    expect(screen.getByText("ポリシー").nextElementSibling).toHaveTextContent(
      "ワークスペースのポリシーにより、このステップがアプリに書き込む前に承認が必要です。",
    );
    expect(screen.getByText("決定者").nextElementSibling).toHaveTextContent("Ana");
    expect(screen.queryByText(/policy\/default|APPROVAL_REQUIRED/)).not.toBeInTheDocument();
  });

  it("labels the step simulated only when its call is mocked", () => {
    renderWithIntl(<ApprovalCard approval={real(true)} onDecide={() => {}} />);
    expect(within(screen.getByRole("heading", { name: /Action/ })).getByText("Simulated")).toBeInTheDocument();
    expect(screen.getByText("Runs against sandbox data. Nothing changes in Google Sheets.")).toBeInTheDocument();
  });

  it("lists the extra writes the same approval lets through, with their simulated label", () => {
    const approval = real(false);
    approval.action = {
      ...approval.action!,
      unlocked: [
        {
          app: "Custom business app",
          step: "ledger_notes",
          tool: "x.add_ledger_note",
          operation: "add ledger note",
          mocked: true,
          count: 3,
        },
        {
          app: "Gmail",
          step: "Gmail: create draft",
          tool: "gmail.create_draft",
          operation: "create draft",
          mocked: false,
        },
      ],
    };
    renderWithIntl(<ApprovalCard approval={approval} onDecide={() => {}} />);
    expect(screen.getByRole("heading", { name: "Also covered by this approval" })).toBeInTheDocument();
    const row = screen.getByText("ledger_notes").closest("div")!;
    expect(within(row).getByText("Custom business app: Add ledger note")).toBeInTheDocument();
    expect(within(row).getByText(/× 3/)).toBeInTheDocument();
    expect(screen.queryByText("x.add_ledger_note")).not.toBeInTheDocument();
    expect(screen.getByText("Runs against sandbox data. Nothing changes in Custom business app.")).toBeInTheDocument();
    expect(within(row).getByText("Simulated")).toBeInTheDocument();
    // An app's own step is named once, by its action, with only the count and the Simulated tag as the value.
    expect(screen.queryByText("Gmail: create draft")).not.toBeInTheDocument();
    expect(screen.getAllByText(/Gmail: Create draft/)).toHaveLength(1);
    const draft = screen.getByText("Gmail: Create draft").closest("div")!;
    expect(within(draft).queryByText("Simulated")).not.toBeInTheDocument();
    expect(screen.getByText(/the 2 steps listed under it/)).toBeInTheDocument();
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
    // No raw ids on the card: the approval's id is not shown.
    expect(screen.queryByText(/apr_run_2001/)).not.toBeInTheDocument();
  });

  it("keeps the email preview for demo approvals", () => {
    renderWithIntl(<ApprovalCard approval={fixture} onDecide={() => {}} />);
    expect(screen.getByRole("heading", { name: "The email, exactly as it will be sent" })).toBeInTheDocument();
    expect(screen.getByText("ap@fernway-goods.example")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve and send" })).toBeInTheDocument();
  });

  it("says nothing leaves the demo only in the demo workspace", async () => {
    const user = userEvent.setup();
    const { unmount } = renderWithIntl(<ApprovalCard approval={fixture} onDecide={() => {}} />);
    await user.click(screen.getByRole("button", { name: "Approve and send" }));
    expect(state.toast).toHaveBeenLastCalledWith(
      "Approved and queued to send",
      "One email to ap@fernway-goods.example. Simulated: nothing leaves the demo.",
      "sim",
    );
    unmount();
    // QA F-22: a live workspace is not the demo, so its toast never says so.
    state.demo = false;
    renderWithIntl(<ApprovalCard approval={fixture} onDecide={() => {}} />);
    await user.click(screen.getByRole("button", { name: "Approve and send" }));
    const [title, body] = state.toast.mock.lastCall ?? [];
    expect(title).toBe("Approved and queued to send");
    expect(String(body ?? "")).not.toMatch(/demo/i);
  });

  it("speaks Japanese", () => {
    renderWithIntl(<ApprovalCard approval={real(true)} onDecide={() => {}} />, { locale: "ja" });
    expect(screen.getByRole("heading", { name: /アクション/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "承認" })).toBeInTheDocument();
  });
});
