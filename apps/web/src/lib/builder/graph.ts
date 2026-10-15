/**
 * A pack's steps as canvas nodes and edges, and back. One node per step (its id is the step id). One edge per
 * route: from the source's outcome handle (`sourceHandle` = the outcome) to the target's `in` handle, with the
 * id `<source>:<outcome>`, so an outcome has at most one edge. Pure: no React.
 */
import type { Edge, Node } from "@xyflow/react";
import type { RoutedEdgeData } from "@/components/routed-edge";
import type { DecisionRules, StepDraft } from "@/lib/api/gen/types.gen";
import { nextStepId, outcomesOf, type StepType } from "./routes";

export type StepConfig = Record<string, unknown>;
export type StepNodeData = { type: StepType; config: StepConfig; rules?: DecisionRules };
export type StepNode = Node<StepNodeData, "step">;
/** `data` holds an ELK route once the graph is laid out (edge type "routed"); a plain "smoothstep" edge has none. */
export type StepEdge = Edge<Partial<RoutedEdgeData>>;
/** A step about to be added: from the palette, the guided list or a drop. */
export type NewStep = { type: StepType; config: StepConfig; rules?: DecisionRules };

/** The target handle every step has. */
export const IN_HANDLE = "in";
/** The space between steps before the layout places them. */
const GRID_X = 260;

export const edgeIdOf = (source: string, outcome: string) => `${source}:${outcome}`;

export function edgeOf(source: string, outcome: string, target: string): StepEdge {
  return {
    id: edgeIdOf(source, outcome),
    source,
    sourceHandle: outcome,
    target,
    targetHandle: IN_HANDLE,
    type: "smoothstep",
    label: outcome,
  };
}

/**
 * Steps with unique ids: the API checks each id's form, not uniqueness, so an import can carry one twice. Every
 * later step with a taken id gets the next free one for its type, free among every id in the draft as well as
 * those already given, so it cannot take the name of a step further down; routes and expressions naming the id
 * keep pointing at the first step, as they did.
 */
function uniqueIds(steps: StepDraft[]): StepDraft[] {
  const all = new Set(steps.map((s) => s.id));
  const taken = new Set<string>();
  return steps.map((s) => {
    const id = taken.has(s.id) ? nextStepId(s.type, new Set([...all, ...taken])) : s.id;
    taken.add(id);
    return id === s.id ? s : { ...s, id };
  });
}

/** Steps as nodes and edges. Positions are a plain row until the layout places them: the YAML stores none. */
export function stepsToGraph(drafts: StepDraft[]): { nodes: StepNode[]; edges: StepEdge[] } {
  const steps = uniqueIds(drafts);
  const ids = new Set(steps.map((s) => s.id));
  const nodes = steps.map((s, i): StepNode => ({
    id: s.id,
    type: "step",
    position: { x: i * GRID_X, y: 0 },
    data: { type: s.type, config: { ...(s.config ?? {}) }, ...(s.rules ? { rules: s.rules } : {}) },
    // A pack has exactly one start; the store refuses to remove it, and React Flow is told the same.
    ...(s.type === "trigger" ? { deletable: false } : {}),
  }));
  const edges = steps.flatMap((s) =>
    Object.entries(s.routes ?? {})
      .filter(([, target]) => ids.has(target))
      .map(([outcome, target]) => edgeOf(s.id, outcome, target)),
  );
  return { nodes, edges };
}

/** Nodes and edges back as steps, in node order; each step's routes in its outcomes' order. */
export function graphToSteps(nodes: StepNode[], edges: StepEdge[]): StepDraft[] {
  const outgoing = new Map<string, StepEdge[]>();
  for (const e of edges) outgoing.set(e.source, [...(outgoing.get(e.source) ?? []), e]);
  return nodes.map((n) => {
    const known = outcomesOf(n.data);
    const rank = (outcome: string) => {
      const i = known.indexOf(outcome);
      return i < 0 ? known.length : i;
    };
    const mine = [...(outgoing.get(n.id) ?? [])].sort(
      (a, b) => rank(a.sourceHandle ?? "") - rank(b.sourceHandle ?? ""),
    );
    return {
      id: n.id,
      type: n.data.type,
      config: { ...n.data.config },
      routes: Object.fromEntries(mine.map((e) => [e.sourceHandle ?? "", e.target])),
      ...(n.data.rules ? { rules: n.data.rules } : {}),
    };
  });
}

/** The pack's entry: its start step (the API requires exactly one), else the first step. */
export function entryOf(nodes: StepNode[]): string {
  return (nodes.find((n) => n.data.type === "trigger") ?? nodes[0])?.id ?? "";
}
