import type { PackDraft } from "@/lib/api/gen/types.gen";

/** The starter's words, translated by the caller. */
export type StarterText = {
  name: string;
  outcome: string;
  description: string;
  humanReview: string;
  inputLabel: string;
  reviewTitle: string;
  reviewInstructions: string;
};

const DAY_S = 86_400;

/**
 * A new pack's first draft: the smallest pack the API accepts with no problems. It starts, a person reviews the
 * request, and it ends completed (with the review as the deliverable) or failed. Function, industries and budgets
 * are the API's defaults, except a small budget for the reviewer.
 */
export function starterPack(text: StarterText): PackDraft {
  return {
    name: text.name,
    outcome: text.outcome,
    description: text.description,
    humanReview: text.humanReview,
    function: "finance-ops",
    industries: ["retail-commerce"],
    inputFields: [{ name: "request", label: text.inputLabel, type: "text", required: true }],
    budgetMinor: 1500,
    humanBudgetMinor: 500,
    entryStep: "start",
    steps: [
      { id: "start", type: "trigger", config: {}, routes: { next: "review" } },
      {
        id: "review",
        type: "human_workforce",
        config: { title: text.reviewTitle, instructions: text.reviewInstructions, show: "=input", timeout_s: DAY_S },
        routes: { resolved: "done", rejected: "failed", timeout: "failed" },
      },
      { id: "done", type: "end", config: { status: "COMPLETED", deliverable: "=nodes.review.output" }, routes: {} },
      { id: "failed", type: "end", config: { status: "FAILED" }, routes: {} },
    ],
  };
}
