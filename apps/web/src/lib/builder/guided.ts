/** The guided step list's order. Pure: no React. */
import type { StepEdge, StepNode } from "./graph";
import { FAILURE_OUTCOMES, outcomesOf } from "./routes";

/** Failure routes sort after every happy-path route, whatever their place among the step's outcomes. */
const FAILURE_RANK = 1000;

/**
 * Steps as a person reads the workflow: from the start, depth first, the happy path before failure routes (each
 * step's outcomes in order), ends after every other step, and steps nothing reaches last, in node order.
 */
export function readingOrder(nodes: StepNode[], edges: StepEdge[]): StepNode[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const outgoing = new Map<string, StepEdge[]>();
  for (const e of edges) outgoing.set(e.source, [...(outgoing.get(e.source) ?? []), e]);
  const rank = (node: StepNode, e: StepEdge) => {
    const outcome = e.sourceHandle ?? "";
    return (FAILURE_OUTCOMES.has(outcome) ? FAILURE_RANK : 0) + outcomesOf(node.data).indexOf(outcome);
  };
  const seen = new Set<string>();
  const order: StepNode[] = [];
  const visit = (id: string) => {
    const node = byId.get(id);
    if (!node || seen.has(id)) return;
    seen.add(id);
    if (node.data.type !== "end") order.push(node);
    const next = [...(outgoing.get(id) ?? [])].sort((a, b) => rank(node, a) - rank(node, b));
    for (const e of next) visit(e.target);
  };
  const start = nodes.find((n) => n.data.type === "trigger");
  if (start) visit(start.id);
  const ends = nodes.filter((n) => n.data.type === "end" && seen.has(n.id));
  return [...order, ...ends, ...nodes.filter((n) => !seen.has(n.id))];
}
