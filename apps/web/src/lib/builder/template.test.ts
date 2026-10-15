import { describe, expect, it } from "vitest";
import { stepsToGraph } from "./graph";
import { graphIssues, toolIndex } from "./rules";
import { starterPack } from "./template";
import { PALETTE } from "./test-fixtures";

describe("the starter pack", () => {
  it("is a small pack with no problems: start, a human review, a completed end and a failed end", () => {
    const pack = starterPack({
      name: "New pack",
      outcome: "o",
      description: "d",
      humanReview: "h",
      inputLabel: "Request",
      reviewTitle: "Review the request",
      reviewInstructions: "Read it.",
    });
    expect(pack.steps.map((s) => s.type)).toEqual(["trigger", "human_workforce", "end", "end"]);
    expect(pack.entryStep).toBe("start");
    const { nodes, edges } = stepsToGraph(pack.steps);
    expect(graphIssues(nodes, edges, toolIndex(PALETTE.tools), PALETTE)).toEqual([]);
  });
});
