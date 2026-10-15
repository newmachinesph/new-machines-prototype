/**
 * What the editor reports about a pack's details (the marketplace text, the start form and the budgets), mirroring
 * the API's field rules (apps/api/app/models/studio.py PackDraft, InputField). The generated SDK checks a request
 * body against the same rules before sending, so a draft that breaks one never reaches the API: these issues say
 * so in the editor instead, and hold the request back. Pure: no React.
 */
import type { PackDetails } from "./store";
import { STEP_ID } from "./routes";
import type { IssueCode, LocalIssue } from "./rules";

/** A start-form field's name is a CEL identifier (`input.<name>`), the same rule as a step id. */
export const FIELD_NAME = STEP_ID;
/** The API's budget bounds, in minor units (cents): $1 to $1,000 per run for agents, $0 to $1,000 for reviewers. */
export const MIN_BUDGET_MINOR = 100;
export const MAX_BUDGET_MINOR = 100_000;
export const MAX_INPUT_FIELDS = 10;

export type TextDetail = "name" | "outcome" | "description" | "humanReview";
export type BudgetDetail = "budgetMinor" | "humanBudgetMinor";
export type DetailsIssueCode = "missingDetail" | "badFieldName" | "missingFieldLabel" | "budgetRange";
export type DetailsIssue =
  | { code: "missingDetail"; field: TextDetail }
  | { code: "budgetRange"; field: BudgetDetail; min: number; max: number }
  | { code: "badFieldName" | "missingFieldLabel"; field: "inputFields"; index: number };

/** Anything the editor finds wrong, in the graph or in the details. */
export type EditorIssue = LocalIssue | DetailsIssue;

const TEXTS: readonly TextDetail[] = ["name", "outcome", "description", "humanReview"];
const BUDGETS: readonly { field: BudgetDetail; min: number }[] = [
  { field: "budgetMinor", min: MIN_BUDGET_MINOR },
  { field: "humanBudgetMinor", min: 0 },
];

const filled = (v: unknown) => typeof v === "string" && v.trim().length > 0;

/** What is wrong with the pack's details, in form order. An omitted budget takes the API's default, so it is fine. */
export function detailsIssues(details: PackDetails): DetailsIssue[] {
  const out: DetailsIssue[] = [];
  for (const field of TEXTS) if (!filled(details[field])) out.push({ code: "missingDetail", field });
  (details.inputFields ?? []).forEach((f, index) => {
    if (!FIELD_NAME.test(f.name)) out.push({ code: "badFieldName", field: "inputFields", index });
    if (!filled(f.label)) out.push({ code: "missingFieldLabel", field: "inputFields", index });
  });
  for (const { field, min } of BUDGETS) {
    const value = details[field];
    if (value === undefined) continue;
    if (!Number.isInteger(value) || value < min || value > MAX_BUDGET_MINOR)
      out.push({ code: "budgetRange", field, min, max: MAX_BUDGET_MINOR });
  }
  return out;
}

/**
 * The issues that hold Validate and Save back: the request check would refuse the body before it is sent (a step
 * id or rule outside its pattern, fewer than two steps or more than sixty, an empty text, a budget out of range),
 * and the API would answer 422 with no located errors. Everything else (an unreachable step, a missing argument,
 * settings written as one expression, a decision with no rules yet) is advisory here, and the API is the judge.
 */
const REQUEST_BLOCKING: ReadonlySet<IssueCode | DetailsIssueCode> = new Set<IssueCode | DetailsIssueCode>([
  "tooFewSteps",
  "tooManySteps",
  "badId",
  "missingRules",
  "missingDetail",
  "badFieldName",
  "missingFieldLabel",
  "budgetRange",
]);

export const blocksRequest = (issues: readonly EditorIssue[]) => issues.some((i) => REQUEST_BLOCKING.has(i.code));
