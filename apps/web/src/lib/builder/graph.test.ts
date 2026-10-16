import { describe, expect, it } from "vitest";
import { edgeIdOf, entryOf, graphToSteps, stepsToGraph } from "./graph";
import { nextStepId, outcomesOf } from "./routes";
import { OVERDUE } from "./test-fixtures";

describe("the editor's graph", () => {
  it("turns each step into a node and each route into an edge from its outcome", () => {
    const { nodes, edges } = stepsToGraph(OVERDUE.steps);
    expect(nodes.map((n) => n.id)).toEqual(OVERDUE.steps.map((s) => s.id));
    expect(nodes.find((n) => n.id === "check")?.data.rules?.question).toBe("Are there overdue invoices to follow up?");
    const granted = edges.find((e) => e.id === edgeIdOf("approve", "granted"));
    expect(granted).toMatchObject({ source: "approve", sourceHandle: "granted", target: "send", targetHandle: "in" });
    expect(edges).toHaveLength(OVERDUE.steps.reduce((n, s) => n + Object.keys(s.routes ?? {}).length, 0));
  });

  it("marks the start step as one the canvas may not delete", () => {
    const { nodes } = stepsToGraph(OVERDUE.steps);
    expect(nodes.find((n) => n.id === "start")?.deletable).toBe(false);
    expect(nodes.find((n) => n.id === "review")?.deletable).toBeUndefined();
  });

  it("round-trips the overdue invoice pack's steps exactly", () => {
    const { nodes, edges } = stepsToGraph(OVERDUE.steps);
    expect(graphToSteps(nodes, edges)).toEqual(OVERDUE.steps);
    expect(entryOf(nodes)).toBe("start");
  });

  it("writes routes in the step type's outcome order, whatever order the edges are in", () => {
    const { nodes, edges } = stepsToGraph(OVERDUE.steps);
    const steps = graphToSteps(nodes, [...edges].reverse());
    expect(Object.keys(steps.find((s) => s.id === "approve")?.routes ?? {})).toEqual(["granted", "denied", "timeout"]);
  });

  it("drops routes to steps that do not exist", () => {
    const { edges } = stepsToGraph([{ id: "start", type: "trigger", config: {}, routes: { next: "gone" } }]);
    expect(edges).toEqual([]);
  });

  it("names outcomes per type, a decision's from its rules", () => {
    expect(outcomesOf({ type: "approval" })).toEqual(["granted", "denied", "timeout"]);
    expect(outcomesOf({ type: "end" })).toEqual([]);
    const check = OVERDUE.steps.find((s) => s.id === "check");
    expect(outcomesOf({ type: "decision", rules: check?.rules })).toEqual(["nothing", "human_review"]);
    expect(outcomesOf({ type: "decision" })).toEqual([]);
  });

  it("lists a decision's model-step failure route among its outcomes", () => {
    const check = OVERDUE.steps.find((s) => s.id === "check");
    if (!check?.rules) throw new Error("fixture");
    const rules = { ...check.rules, evaluator: { on_error: { route: "unsorted" } } };
    expect(outcomesOf({ type: "decision", rules })).toEqual(["nothing", "human_review", "unsorted"]);
    const same = { ...check.rules, evaluator: { on_error: { route: "nothing" } } };
    expect(outcomesOf({ type: "decision", rules: same })).toEqual(["nothing", "human_review"]);
  });

  it("gives a bare step empty settings and routes on the way back", () => {
    const { nodes, edges } = stepsToGraph([{ id: "done", type: "end" }]);
    expect(graphToSteps(nodes, edges)).toEqual([{ id: "done", type: "end", config: {}, routes: {} }]);
  });

  it("writes a decision's routes in rule order, however they arrived", () => {
    const check = OVERDUE.steps.find((s) => s.id === "check");
    if (!check) throw new Error("fixture");
    const shuffled = { ...check, routes: { human_review: "review", nothing: "nothing" } };
    const { nodes, edges } = stepsToGraph([shuffled, ...OVERDUE.steps.filter((s) => s.id !== "check")]);
    expect(Object.keys(graphToSteps(nodes, edges)[0].routes ?? {})).toEqual(["nothing", "human_review"]);
  });

  it("keeps a route on an outcome the step does not have, after the known ones", () => {
    const { nodes, edges } = stepsToGraph([
      { id: "start", type: "trigger", config: {}, routes: { odd: "done", next: "done" } },
      { id: "done", type: "end", config: {}, routes: {} },
    ]);
    expect(edges.map((e) => e.id)).toEqual([edgeIdOf("start", "odd"), edgeIdOf("start", "next")]);
    expect(Object.keys(graphToSteps(nodes, edges)[0].routes ?? {})).toEqual(["next", "odd"]);
  });

  it("gives a later step with a taken id the next free one, and keeps routes on the first", () => {
    const { nodes, edges } = stepsToGraph([
      { id: "start", type: "trigger", config: {}, routes: { next: "review" } },
      { id: "review", type: "human_workforce", config: { title: "A" }, routes: { resolved: "review" } },
      { id: "review", type: "human_workforce", config: { title: "B" }, routes: { resolved: "done" } },
      { id: "done", type: "end", config: {}, routes: {} },
    ]);
    expect(nodes.map((n) => n.id)).toEqual(["start", "review", "review_2", "done"]);
    expect(nodes.find((n) => n.id === "review_2")?.data.config.title).toBe("B");
    expect(edges.find((e) => e.id === edgeIdOf("start", "next"))?.target).toBe("review");
    expect(edges.find((e) => e.id === edgeIdOf("review_2", "resolved"))?.target).toBe("done");
    expect(new Set(edges.map((e) => e.id)).size).toBe(edges.length);
  });

  it("never gives a duplicate the name of a step further down", () => {
    const { nodes, edges } = stepsToGraph([
      { id: "start", type: "trigger", config: {}, routes: { next: "review" } },
      { id: "review", type: "human_workforce", config: { title: "A" }, routes: { resolved: "review_2" } },
      { id: "review", type: "human_workforce", config: { title: "B" }, routes: { resolved: "done" } },
      { id: "review_2", type: "human_workforce", config: { title: "C" }, routes: { resolved: "done" } },
      { id: "done", type: "end", config: {}, routes: {} },
    ]);
    expect(nodes.map((n) => n.id)).toEqual(["start", "review", "review_3", "review_2", "done"]);
    expect(nodes.find((n) => n.id === "review_2")?.data.config.title).toBe("C");
    expect(edges.find((e) => e.id === edgeIdOf("review", "resolved"))?.target).toBe("review_2");
    expect(edges.find((e) => e.id === edgeIdOf("review_3", "resolved"))?.target).toBe("done");
  });

  it("gives a new step the first free id for its type", () => {
    expect(nextStepId("human_workforce", ["start"])).toBe("review");
    expect(nextStepId("human_workforce", ["review", "review_2"])).toBe("review_3");
  });
});
