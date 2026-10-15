import { describe, expect, it } from "vitest";
import { edgeIdOf, stepsToGraph } from "./graph";
import { layoutInput, placed, stepSize, unroute } from "./layout";
import { OVERDUE } from "./test-fixtures";

describe("editor layout input", () => {
  const { nodes, edges } = stepsToGraph(OVERDUE.steps);

  it("sizes steps like the run canvas, taller when they have many outcomes", () => {
    expect(stepSize({ type: "trigger" })).toEqual({ width: 150, height: 84 });
    expect(stepSize({ type: "approval" })).toEqual({ width: 210, height: 96 });
    const routes = ["a", "b", "c", "d", "e"].map((route) => ({
      when: "true",
      route,
      verdict: "APPROVED" as const,
      explanation: "x",
    }));
    const rules = {
      question: "q",
      rules: routes,
      default: { route: "f", verdict: "HUMAN_REVIEW" as const, explanation: "x" },
    };
    expect(stepSize({ type: "decision", rules }).height).toBe(168);
  });

  it("puts the happy path on the primary row and labels edges with their outcome", () => {
    const input = layoutInput(nodes, edges);
    const primary = input.edges.filter((e) => e.primary).map((e) => e.id);
    expect(primary).toContain(edgeIdOf("approve", "granted"));
    expect(primary).not.toContain(edgeIdOf("approve", "denied"));
    expect(input.edges.find((e) => e.id === edgeIdOf("send", "ok"))?.label).toBe("ok");
  });

  it("places steps by their centre and draws routed edges, and unroutes edges of moved steps", () => {
    const layout = {
      positions: { start: { x: 0, y: 10 }, recall: { x: 200, y: 10 } },
      routes: {
        [edgeIdOf("start", "next")]: {
          points: [
            { x: 150, y: 52 },
            { x: 200, y: 52 },
          ],
        },
      },
    };
    const out = placed(nodes, edges, layout);
    expect(out.nodes.find((n) => n.id === "start")?.position).toEqual({ x: 0, y: 52 });
    const routed = out.edges.find((e) => e.id === edgeIdOf("start", "next"));
    expect(routed?.type).toBe("routed");
    expect(out.edges.find((e) => e.id === edgeIdOf("recall", "next"))?.type).toBe("smoothstep");
    const moved = unroute(out.edges, new Set(["recall"]));
    expect(moved.find((e) => e.id === edgeIdOf("start", "next"))?.type).toBe("smoothstep");
  });
});
