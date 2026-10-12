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

afterEach(() => vi.useRealTimers());

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

  it("shows a neutral view for an unknown state", () => {
    renderWithIntl(<TaskWorkspace task={{ ...task, state: "CANCELLED" }} buyer={task.buyer} />);
    expect(screen.getByText("This task is no longer available")).toBeInTheDocument();
  });
});
