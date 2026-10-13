import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { HumanTask } from "@/lib/api/gen/types.gen";
import { renderWithIntl } from "@/test/intl";
import { TaskWorkspace } from "./task-workspace";

const done = <T,>(_vars: unknown, opts?: { onSuccess?: (t: T) => void }) => opts?.onSuccess?.({} as T);
vi.mock("@/lib/queries/tasks", () => ({
  useClaimTask: () => ({ mutate: done, isPending: false }),
  useSubmitReview: () => ({ mutate: done, isPending: false }),
}));
vi.mock("@/components/base", async (orig) => ({ ...(await orig<object>()), useToast: () => vi.fn() }));
const workspace = vi.hoisted(() => ({ demo: true }));
vi.mock("@/lib/queries/me", () => ({ useIsDemo: () => workspace.demo }));

const task = {
  id: "ht_011",
  version: 1,
  runId: "run_1042",
  packName: "Order & Payment Reconciliation",
  title: "Correct exceptions",
  mode: "CORRECTION",
  skill: "Invoice review",
  state: "OFFERED",
  pay: { amountMinor: 750, currency: "USD" },
  payTerms: "human_terms@3",
  estMinutes: 20,
  deadline: "2026-10-13T20:07:00Z",
  postedAt: "2026-10-12T10:00:00Z",
  dataClass: "CONFIDENTIAL",
  regions: ["PH"],
  obligations: [],
  instructions: "Decide.",
  question: "Real mismatches?",
  leaseMinutes: 45,
  buyer: "A retailer",
  records: [
    {
      id: "HP-1",
      flag: "Reference mismatch",
      agentNote: "Digits swapped.",
      order: { ref: "HP-1", date: "Oct 11", customer: "M", amount: "$1.00", paymentRef: "R1" },
      payment: { ref: "R2", date: "Oct 12", payer: "S", amount: "$1.00", batch: "B" },
    },
  ],
} as unknown as HumanTask;

afterEach(() => {
  vi.useRealTimers();
  workspace.demo = true;
});

// The check after a submit is simulated with a timer, so tests drive it with fake timers.
async function submitReview(
  locale: "en" | "ja",
  labels: { claim: string; call: string; feedback: string; submit: string },
) {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  renderWithIntl(<TaskWorkspace task={task} buyer={task.buyer} />, { locale });
  await user.click(screen.getByRole("button", { name: labels.claim }));
  await user.click(screen.getByRole("radio", { name: labels.call }));
  await user.type(screen.getByRole("textbox", { name: labels.feedback }), "They are the same payment.");
  await user.click(screen.getByRole("button", { name: labels.submit }));
}

describe("TaskWorkspace submit flow", () => {
  it("moves from submitted to a simulated check to accepted", async () => {
    await submitReview("en", {
      claim: "Claim this task",
      call: "Same payment",
      feedback: "Feedback for the agent",
      submit: "Submit review",
    });
    expect(screen.getByText("Simulated check")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(1400);
    });
    expect(screen.getByText("Accepted. $7.50 is owed to you.")).toBeInTheDocument();
  });

  it("labels the simulated check in Japanese", async () => {
    await submitReview("ja", {
      claim: "このタスクを引き受ける",
      call: "同じ支払い",
      feedback: "エージェントへのフィードバック",
      submit: "レビューを提出",
    });
    expect(screen.getByText("模擬チェック")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(1400);
    });
    expect(screen.getByText("受け入れられました。$7.50があなたに支払われます。")).toBeInTheDocument();
  });

  it("shows the closed view in Japanese", () => {
    renderWithIntl(<TaskWorkspace task={{ ...task, state: "CANCELLED" }} buyer={task.buyer} />, { locale: "ja" });
    expect(screen.getByText("このタスクは受け付けていません")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "受けられるタスクに戻る" })).toHaveAttribute("href", "/work");
  });

  it("does not show accepted for a reloaded SUBMITTED task", () => {
    renderWithIntl(<TaskWorkspace task={{ ...task, state: "SUBMITTED" }} buyer={task.buyer} />);
    expect(screen.getByText(/Submitted\. Waiting for the check/)).toBeInTheDocument();
    expect(screen.queryByText(/Accepted\./)).not.toBeInTheDocument();
  });

  it("shows accepted when the server says ACCEPTED", () => {
    renderWithIntl(<TaskWorkspace task={{ ...task, state: "ACCEPTED" }} buyer={task.buyer} />);
    expect(screen.getByText(/Accepted\. \$7\.50 is owed to you\./)).toBeInTheDocument();
  });

  it("shows the accepted view in Japanese with the pay in dollars", () => {
    renderWithIntl(<TaskWorkspace task={{ ...task, state: "ACCEPTED" }} buyer={task.buyer} />, { locale: "ja" });
    expect(screen.getByText("受け入れられました。$7.50があなたに支払われます。")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "run_1042" })).toHaveAttribute("href", "/app/runs/run_1042");
  });

  it("says a reject or escalate stops a real run", async () => {
    const user = userEvent.setup();
    renderWithIntl(<TaskWorkspace task={{ ...task, realRun: true }} buyer={task.buyer} />);
    await user.click(screen.getByRole("button", { name: "Claim this task" }));
    expect(screen.getByText("The result is wrong. The run stops here and does not retry.")).toBeInTheDocument();
    // Corrections on a real run go to the next step; the agent does not retry.
    expect(screen.getByText(/Your corrections go to the next step of the run\./)).toBeInTheDocument();
    expect(screen.queryByText(/apply your notes and try again/)).not.toBeInTheDocument();
    expect(screen.getByText(/more authority or context\. The run stops here\./)).toBeInTheDocument();
  });

  it("goes straight to the run's outcome after a real-run review, with no simulated check", async () => {
    const user = userEvent.setup();
    renderWithIntl(<TaskWorkspace task={{ ...task, realRun: true }} buyer={task.buyer} />);
    await user.click(screen.getByRole("button", { name: "Claim this task" }));
    await user.click(screen.getByRole("radio", { name: "Same payment" }));
    await user.click(screen.getByRole("radio", { name: /^Reject/ }));
    await user.type(screen.getByRole("textbox", { name: "Feedback for the agent" }), "These do not match at all.");
    await user.click(screen.getByRole("button", { name: "Submit review" }));
    expect(screen.getByText("Review recorded. The run stops here.")).toBeInTheDocument();
    expect(screen.queryByText("Simulated check")).not.toBeInTheDocument();
    expect(screen.queryByText(/is owed to you/)).not.toBeInTheDocument();
  });

  it("explains each real-run verdict in Japanese", async () => {
    const user = userEvent.setup();
    renderWithIntl(<TaskWorkspace task={{ ...task, realRun: true }} buyer={task.buyer} />, { locale: "ja" });
    await user.click(screen.getByRole("button", { name: "このタスクを引き受ける" }));
    expect(screen.getByText(/あなたの修正は実行の次のステップに渡されます/)).toBeInTheDocument();
    expect(screen.queryByText("エージェントがあなたのメモを反映して、やり直します。")).not.toBeInTheDocument();
  });

  it("does not wait on a check for a reloaded real-run task", () => {
    const submitted = { ...task, realRun: true, state: "SUBMITTED" as const };
    const { unmount } = renderWithIntl(
      <TaskWorkspace task={{ ...submitted, runOutcome: "CONTINUES" }} buyer={task.buyer} />,
    );
    expect(screen.getByText("Review recorded. The run goes on with it.")).toBeInTheDocument();
    expect(screen.queryByText(/Waiting for the check/)).not.toBeInTheDocument();
    unmount();
    renderWithIntl(<TaskWorkspace task={submitted} buyer={task.buyer} />, { locale: "ja" });
    expect(screen.getByText("レビューを記録しました")).toBeInTheDocument();
  });

  it("shows a neutral view for an unknown state", () => {
    renderWithIntl(<TaskWorkspace task={{ ...task, state: "CANCELLED" }} buyer={task.buyer} />);
    expect(screen.getByText("This task is no longer available")).toBeInTheDocument();
  });
});

describe("TaskWorkspace pay terms", () => {
  it("shows the demo's pay terms in the demo", () => {
    renderWithIntl(<TaskWorkspace task={task} buyer={task.buyer} />);
    expect(screen.getByText("Simulated pay, human_terms@3")).toBeInTheDocument();
  });

  it("drops the API's demo pay terms in a live workspace", () => {
    workspace.demo = false;
    renderWithIntl(<TaskWorkspace task={{ ...task, payTerms: "Demo run: no reviewer pay" }} buyer={task.buyer} />);
    expect(screen.getByText("Simulated pay")).toBeInTheDocument();
    expect(screen.queryByText(/Demo run/)).not.toBeInTheDocument();
  });
});
