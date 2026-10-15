import { describe, expect, it } from "vitest";
import { celOptions, isCel, itemOptions, upstreamOf } from "./cel-fields";
import { stepsToGraph } from "./graph";
import { OVERDUE, PALETTE } from "./test-fixtures";

const { nodes, edges } = stepsToGraph(OVERDUE.steps);

describe("what CEL can read", () => {
  it("knows which steps run before a step, on any path", () => {
    expect([...upstreamOf("draft", edges)].sort()).toEqual(["check", "invoices", "plan", "recall", "review", "start"]);
    expect(upstreamOf("start", edges).size).toBe(0);
  });

  it("offers the run input, memory after a recall, and each earlier step's output and fields", () => {
    const exprs = celOptions("draft", nodes, edges, OVERDUE, PALETTE).map((o) => o.expr);
    expect(exprs).toEqual(
      expect.arrayContaining([
        "input.as_of",
        "memory",
        "nodes.invoices.output",
        "nodes.plan.output",
        "nodes.plan.output.messages",
        "nodes.review.output",
      ]),
    );
    expect(exprs).not.toContain("nodes.approve.output");
    expect(exprs).not.toContain("nodes.start.output");
    const messages = celOptions("draft", nodes, edges, OVERDUE, PALETTE).find(
      (o) => o.expr === "nodes.plan.output.messages",
    );
    expect(messages).toEqual({ group: "steps", expr: "nodes.plan.output.messages", label: "plan · Messages" });
  });

  it("marks the options whose label is a fixed word, so the field can translate them", () => {
    const options = celOptions("verify", nodes, edges, OVERDUE, PALETTE);
    expect(options.find((o) => o.expr === "memory")).toEqual({
      group: "memory",
      expr: "memory",
      label: "memory",
      fixed: "memory",
    });
    expect(options.find((o) => o.expr === "nodes.send.output.results")).toEqual({
      group: "steps",
      expr: "nodes.send.output.results",
      label: "send · results",
      fixed: "results",
    });
    expect(options.find((o) => o.expr === "nodes.send.output")).not.toHaveProperty("fixed");
  });

  it("offers memory only after a recall: a remember step sets none", () => {
    const remembered = stepsToGraph(
      OVERDUE.steps.map((s) =>
        s.id === "recall" ? { ...s, config: { op: "remember", space: "customer-accounts", value: "=input.as_of" } } : s,
      ),
    );
    const exprs = celOptions("draft", remembered.nodes, remembered.edges, OVERDUE, PALETTE).map((o) => o.expr);
    expect(exprs).not.toContain("memory");
    expect(exprs).not.toContain("nodes.recall.output");
    expect(exprs).toContain("nodes.plan.output");
  });

  it("skips input fields that are blank, not identifiers or repeated, and falls back to the name as the label", () => {
    const details = {
      inputFields: [
        { name: "as_of", label: "As of" },
        { name: "", label: "Unnamed" },
        { name: "   ", label: "Blank" },
        { name: "2fast", label: "Starts with a digit" },
        { name: "with space", label: "Has a space" },
        { name: "region", label: "" },
        { name: "as_of", label: "As of, again" },
      ],
    };
    const inputs = celOptions("draft", nodes, edges, details, PALETTE).filter((o) => o.group === "input");
    expect(inputs).toEqual([
      { group: "input", expr: "input.as_of", label: "As of" },
      { group: "input", expr: "input.region", label: "region" },
    ]);
  });

  it("offers the item and its fields inside a for_each", () => {
    const options = itemOptions("=nodes.draft.output.drafts", nodes, PALETTE);
    expect(options.map((o) => o.expr)).toEqual(["item", "item.to", "item.subject", "item.body", "item.ref"]);
    expect(options[0]).toEqual({ group: "item", expr: "item", label: "item", fixed: "item" });
    expect(options[1]).toEqual({ group: "item", expr: "item.to", label: "To" });
    expect(itemOptions("", nodes, PALETTE)).toEqual([]);
  });

  it("reads a value starting with = as CEL and anything else as text", () => {
    expect(isCel("=input.as_of")).toBe(true);
    expect(isCel("firm but friendly")).toBe(false);
    expect(isCel(3)).toBe(false);
  });
});
