import { describe, expect, it } from "vitest";
import type { RunEdge, RunNode } from "./types";
import { isFailureRoute, withTerminalStubs } from "./terminal-stubs";

const node = (id: string, type: RunNode["type"], i: number, extra: Partial<RunNode> = {}): RunNode => ({
  id,
  type,
  label: id,
  actor: "system",
  status: "CREATED",
  x: 210 * i,
  y: 0,
  ...extra,
});

const NODES: RunNode[] = [
  node("start", "trigger", 0),
  node("read", "connector", 1),
  node("check", "decision", 2),
  node("nothing", "end", 3),
  node("done", "end", 4),
  node("failed", "end", 5, { label: "Failed", status: "FAILED", y: 140 }),
];
const EDGES: RunEdge[] = [
  { from: "start", to: "read", taken: true },
  { from: "read", to: "check", taken: true },
  { from: "read", to: "failed", label: "denied" },
  { from: "read", to: "failed", label: "error", taken: true },
  { from: "check", to: "nothing", label: "nothing" },
  { from: "check", to: "done", label: "approved" },
  { from: "check", to: "failed", label: "timeout" },
];

describe("isFailureRoute", () => {
  it("knows the failure routes and nothing else", () => {
    for (const r of ["denied", "error", "timeout", "fail", "failed", "rejected", "blocked"]) {
      expect(isFailureRoute(r), r).toBe(true);
    }
    for (const r of [undefined, "", "next", "nothing", "approved", "revision required"]) {
      expect(isFailureRoute(r), String(r)).toBe(false);
    }
  });
});

describe("withTerminalStubs", () => {
  it("replaces an end reached only by failure routes with one stub per source", () => {
    const { nodes, edges } = withTerminalStubs(NODES, EDGES);
    expect(nodes.map((n) => n.id)).toEqual([
      "start",
      "read",
      "check",
      "nothing",
      "done",
      "failed@read",
      "failed@check",
    ]);
    const stub = nodes.find((n) => n.id === "failed@read")!;
    expect(stub).toMatchObject({ stubOf: "failed", label: "Failed", status: "FAILED", type: "end" });
    // Two failure routes from one step share one stub and one short edge, labelled with both routes.
    expect(edges).toContainEqual({ from: "read", to: "failed@read", label: "denied · error", taken: true });
    expect(edges).toContainEqual({ from: "check", to: "failed@check", label: "timeout", taken: false });
    expect(edges.some((e) => e.to === "failed")).toBe(false);
  });

  it("gives a stub the end's status only when its own route was taken, and names the step it follows", () => {
    const { nodes } = withTerminalStubs(NODES, EDGES);
    // read's "error" route was taken (merged with its untaken "denied"); check's "timeout" was not.
    expect(nodes.find((n) => n.id === "failed@read")).toMatchObject({ status: "FAILED", stubFrom: "read" });
    expect(nodes.find((n) => n.id === "failed@check")).toMatchObject({ status: "CREATED", stubFrom: "check" });
  });

  it("keeps the edge order, putting a stub edge where its first failure route was", () => {
    const { edges } = withTerminalStubs(NODES, EDGES);
    expect(edges.map((e) => `${e.from}>${e.to}`)).toEqual([
      "start>read",
      "read>check",
      "read>failed@read",
      "check>nothing",
      "check>done",
      "check>failed@check",
    ]);
  });

  it("places each stub next to its source in server coordinates", () => {
    const { nodes } = withTerminalStubs(NODES, EDGES);
    const read = nodes.find((n) => n.id === "read")!;
    const stub = nodes.find((n) => n.id === "failed@read")!;
    expect(stub.x).toBeGreaterThan(read.x);
    expect(stub.y).toBeGreaterThan(read.y);
  });

  it("leaves ends reached by an onward route, and non-end steps, alone", () => {
    const edges: RunEdge[] = [
      { from: "start", to: "read" },
      { from: "read", to: "failed", label: "error" },
      { from: "read", to: "done" },
      { from: "check", to: "done", label: "fail" },
    ];
    const result = withTerminalStubs(NODES, edges);
    expect(result.nodes.map((n) => n.id)).toEqual(["start", "read", "check", "nothing", "done", "failed@read"]);
    expect(result.edges).toContainEqual({ from: "check", to: "done", label: "fail" });
  });

  it("returns the graph unchanged when there is nothing to stub", () => {
    const edges = EDGES.filter((e) => e.to !== "failed");
    const result = withTerminalStubs(NODES, edges);
    expect(result.nodes.map((n) => n.id)).toEqual(NODES.map((n) => n.id));
    expect(result.edges).toEqual(edges);
  });
});
