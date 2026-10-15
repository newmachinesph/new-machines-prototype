/**
 * The editor's side of the shared ELK layout (src/lib/graph-layout.ts, also used by the run canvas): step sizes,
 * the input for layoutGraph, and applying its result. Pure: no React.
 */
import { mainPath, type GraphLayout, type LayoutEdge, type LayoutNode } from "@/lib/graph-layout";
import type { StepEdge, StepNode, StepNodeData } from "./graph";
import { FAILURE_OUTCOMES, outcomesOf, SMALL_STEPS } from "./routes";

// The run canvas's card sizes (run-canvas.tsx STEP_SIZE and SMALL_SIZE), so both canvases look alike.
const STEP_WIDTH = 210;
const STEP_HEIGHT = 96;
const SMALL_WIDTH = 150;
const SMALL_HEIGHT = 84;
/** Room for each outcome handle on a card's right side, so handles and their edges do not crowd. */
export const HANDLE_GAP = 24;

export function stepSize(data: Pick<StepNodeData, "type" | "rules">): { width: number; height: number } {
  const small = SMALL_STEPS.has(data.type);
  const handles = outcomesOf(data).length;
  return {
    width: small ? SMALL_WIDTH : STEP_WIDTH,
    height: Math.max(small ? SMALL_HEIGHT : STEP_HEIGHT, HANDLE_GAP * (handles + 1)),
  };
}

/** Nodes and edges for layoutGraph. The happy path (the longest chain of non-failure outcomes) is primary. */
export function layoutInput(nodes: StepNode[], edges: StepEdge[]): { nodes: LayoutNode[]; edges: LayoutEdge[] } {
  const onward = edges.filter((e) => !FAILURE_OUTCOMES.has(e.sourceHandle ?? ""));
  const primary = mainPath(onward);
  return {
    nodes: nodes.map((n) => ({ id: n.id, ...stepSize(n.data) })),
    edges: edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      label: e.sourceHandle ?? undefined,
      primary: primary.has(e.id),
    })),
  };
}

const unrouted = (e: StepEdge): StepEdge => ({ ...e, type: "smoothstep", data: {} });

/**
 * Applies a layout: each node placed by its vertical centre (the canvas's nodeOrigin is [0, 0.5], as on the run
 * canvas), each laid-out edge drawn as the shared "routed" edge. Anything the layout left out keeps its place.
 */
export function placed(
  nodes: StepNode[],
  edges: StepEdge[],
  layout: GraphLayout,
): { nodes: StepNode[]; edges: StepEdge[] } {
  return {
    nodes: nodes.map((n) => {
      const at = layout.positions[n.id];
      return at ? { ...n, position: { x: at.x, y: at.y + stepSize(n.data).height / 2 } } : n;
    }),
    edges: edges.map((e) => {
      const route = layout.routes[e.id];
      return route ? { ...e, type: "routed", data: { points: route.points, labelAt: route.label } } : unrouted(e);
    }),
  };
}

/** A route stops fitting when a step it touches moves: draw those edges plainly until the next layout. */
export function unroute(edges: StepEdge[], moved: ReadonlySet<string>): StepEdge[] {
  return edges.map((e) => (e.type === "routed" && (moved.has(e.source) || moved.has(e.target)) ? unrouted(e) : e));
}
