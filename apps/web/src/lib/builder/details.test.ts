import { describe, expect, it } from "vitest";
import { blocksRequest, detailsIssues, MAX_BUDGET_MINOR, MIN_BUDGET_MINOR } from "./details";
import { detailsOf } from "./store";
import { OVERDUE } from "./test-fixtures";

const details = detailsOf(OVERDUE);

describe("detailsIssues", () => {
  it("finds nothing wrong with a finished pack's details", () => {
    expect(detailsIssues(details)).toEqual([]);
  });

  it("reports each empty text, including one that is only spaces", () => {
    expect(detailsIssues({ ...details, name: "", outcome: "  ", description: "", humanReview: "" })).toEqual([
      { code: "missingDetail", field: "name" },
      { code: "missingDetail", field: "outcome" },
      { code: "missingDetail", field: "description" },
      { code: "missingDetail", field: "humanReview" },
    ]);
  });

  it("reports a field name outside the CEL identifier rule, and an empty label, by position", () => {
    const issues = detailsIssues({
      ...details,
      inputFields: [
        { name: "as_of", label: "As of", type: "date", required: true },
        { name: "Bad-Name", label: "", type: "text", required: true },
        { name: "", label: "Amount", type: "number", required: false },
      ],
    });
    expect(issues).toEqual([
      { code: "badFieldName", field: "inputFields", index: 1 },
      { code: "missingFieldLabel", field: "inputFields", index: 1 },
      { code: "badFieldName", field: "inputFields", index: 2 },
    ]);
  });

  it("reports a budget outside the API's range, with the range", () => {
    expect(detailsIssues({ ...details, budgetMinor: 0 })).toEqual([
      { code: "budgetRange", field: "budgetMinor", min: MIN_BUDGET_MINOR, max: MAX_BUDGET_MINOR },
    ]);
    expect(detailsIssues({ ...details, budgetMinor: MAX_BUDGET_MINOR + 1 })).toHaveLength(1);
    expect(detailsIssues({ ...details, humanBudgetMinor: -1 })).toEqual([
      { code: "budgetRange", field: "humanBudgetMinor", min: 0, max: MAX_BUDGET_MINOR },
    ]);
    // Omitted budgets take the API's defaults.
    expect(detailsIssues({ ...details, budgetMinor: undefined, humanBudgetMinor: undefined })).toEqual([]);
  });
});

describe("blocksRequest", () => {
  it("is true only for a problem the request check would refuse before sending", () => {
    expect(blocksRequest([{ code: "unreachable", step: "x" }])).toBe(false);
    expect(blocksRequest([{ code: "missingArg", step: "x", arg: "limit" }])).toBe(false);
    expect(blocksRequest([{ code: "argsExpression", step: "x" }])).toBe(false);
    // No rules at all pass the request check; the API names the decision. Unfinished rules do not pass it.
    expect(blocksRequest([{ code: "noRules", step: "x" }])).toBe(false);
    expect(blocksRequest([{ code: "missingRules", step: "x" }])).toBe(true);
    expect(blocksRequest([{ code: "badId", step: "Bad" }])).toBe(true);
    expect(blocksRequest([{ code: "tooFewSteps" }])).toBe(true);
    expect(blocksRequest([{ code: "tooManySteps" }])).toBe(true);
    expect(blocksRequest([{ code: "missingDetail", field: "name" }])).toBe(true);
    expect(blocksRequest([{ code: "badFieldName", field: "inputFields", index: 0 }])).toBe(true);
    expect(blocksRequest([{ code: "missingFieldLabel", field: "inputFields", index: 0 }])).toBe(true);
    expect(blocksRequest([{ code: "budgetRange", field: "budgetMinor", min: 100, max: 100_000 }])).toBe(true);
    expect(blocksRequest([])).toBe(false);
  });
});
