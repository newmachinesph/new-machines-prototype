/**
 * Automatic layout for step graphs (the run canvas, and the workflow editor's "Auto-arrange").
 *
 * Wraps ELK's layered algorithm (elkjs, EPL-2.0, see THIRD_PARTY_NOTICES.md). ELK is loaded on first use with a
 * dynamic import, so it lands in its own chunk and never in the main bundle. Pure: no React, no DOM, and the same
 * input always gives the same output.
 */
import type { ELK, ElkExtendedEdge, ElkNode, ElkPoint, LayoutOptions } from "elkjs/lib/elk-api";
import { repairWrappedRoutes, type Box } from "./route-repair";

export type LayoutNode = { id: string; width: number; height: number };
export type LayoutEdge = {
  id: string;
  source: string;
  target: string;
  label?: string;
  /** On the happy path (see `mainPath`): kept on one straight row, and other edges bend around it. */
  primary?: boolean;
};
export type LayoutDirection = "RIGHT" | "DOWN";
export type Point = { x: number; y: number };
/** `points` run from the source's out side to the target's in side; `label` is the centre of the edge's label. */
export type EdgeRoute = { points: Point[]; label?: Point };
/** `positions` are each node's top-left corner. */
export type GraphLayout = { positions: Record<string, Point>; routes: Record<string, EdgeRoute> };

const LABEL_CHAR_PX = 6.2;
const LABEL_PAD_X = 10;
const LABEL_HEIGHT = 18;

const BASE_OPTIONS: LayoutOptions = {
  "elk.algorithm": "layered",
  "elk.edgeRouting": "ORTHOGONAL",
  // Network simplex, weighted by the primary edges' priorities below, keeps the whole happy path on one row;
  // Brandes-Koepf bent it wherever a branch rejoined (measured on the refund and reconciliation workflows).
  "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
  "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
  // A route back to an earlier step (a revision loop) is the edge that runs backwards, never a forward one.
  "elk.layered.cycleBreaking.strategy": "MODEL_ORDER",
  "elk.spacing.nodeNode": "40",
  "elk.layered.spacing.nodeNodeBetweenLayers": "70",
  "elk.spacing.edgeNode": "20",
  "elk.layered.spacing.edgeNodeBetweenLayers": "20",
  "elk.spacing.edgeLabel": "4",
  "elk.layered.edgeLabels.centerLabelPlacementStrategy": "TAIL_LAYER",
  "elk.padding": "[top=12,left=12,bottom=12,right=12]",
  "elk.randomSeed": "1",
};

const PRIMARY_EDGE_OPTIONS: LayoutOptions = {
  "elk.layered.priority.straightness": "100",
  "elk.layered.priority.direction": "100",
};

// Labels sit on their own edge (inline), in the first layer after the edge leaves its source (TAIL_LAYER above),
// so "denied" reads right beside the step that denied, and two routes leaving one step keep their labels apart.
const LABEL_OPTIONS: LayoutOptions = { "elk.edgeLabels.placement": "CENTER", "elk.edgeLabels.inline": "true" };
// A side exit (a non-primary edge into a dead end that nothing else reaches, such as a failure stub) labels its tail
// instead: a centre label takes a layer of its own, which would push the dead end a column away from its step.
const SIDE_EXIT_LABEL_OPTIONS: LayoutOptions = { "elk.edgeLabels.placement": "TAIL" };

function isSideExit(edge: LayoutEdge, edges: LayoutEdge[]) {
  return (
    !edge.primary &&
    !edges.some((e) => e.source === edge.target) &&
    !edges.some((e) => e.target === edge.target && e !== edge)
  );
}

let elkPromise: Promise<ELK> | undefined;

function loadElk(): Promise<ELK> {
  if (!elkPromise) {
    const loading = import("elkjs/lib/elk.bundled.js").then(({ default: ElkConstructor }) => new ElkConstructor());
    elkPromise = loading;
    // A failed load (a chunk that did not arrive) is retried next time, not cached forever.
    loading.catch(() => {
      if (elkPromise === loading) elkPromise = undefined;
    });
  }
  return elkPromise;
}

const inPort = (id: string) => `${id}::in`;
const outPort = (id: string) => `${id}::out`;

/** Rough width of an edge label at the canvas's 11px label size; ELK reserves this much room for it. */
export function labelSize(text: string) {
  return { width: Math.ceil(text.length * LABEL_CHAR_PX + LABEL_PAD_X), height: LABEL_HEIGHT };
}

function toElkGraph(nodes: LayoutNode[], edges: LayoutEdge[], direction: LayoutDirection): ElkNode {
  const [inSide, outSide] = direction === "RIGHT" ? ["WEST", "EAST"] : ["NORTH", "SOUTH"];
  const known = new Set(nodes.map((n) => n.id));
  return {
    id: "root",
    layoutOptions: { ...BASE_OPTIONS, "elk.direction": direction },
    children: nodes.map((n) => ({
      id: n.id,
      width: n.width,
      height: n.height,
      layoutOptions: { "elk.portConstraints": "FIXED_SIDE", "elk.portAlignment.default": "CENTER" },
      ports: [
        { id: inPort(n.id), width: 0, height: 0, layoutOptions: { "elk.port.side": inSide } },
        { id: outPort(n.id), width: 0, height: 0, layoutOptions: { "elk.port.side": outSide } },
      ],
    })),
    // Primary edges first (otherwise in the caller's order): with model order respected, ELK then threads the
    // primary path straight and routes the rest around it, whatever order the workflow declares its routes in.
    edges: [...edges.filter((e) => e.primary), ...edges.filter((e) => !e.primary)]
      .filter((e) => known.has(e.source) && known.has(e.target))
      .map<ElkExtendedEdge>((e) => ({
        id: e.id,
        sources: [outPort(e.source)],
        targets: [inPort(e.target)],
        layoutOptions: e.primary ? PRIMARY_EDGE_OPTIONS : undefined,
        labels: e.label
          ? [
              {
                id: `${e.id}::label`,
                text: e.label,
                ...labelSize(e.label),
                layoutOptions: isSideExit(e, edges) ? SIDE_EXIT_LABEL_OPTIONS : LABEL_OPTIONS,
              },
            ]
          : undefined,
      })),
  };
}

function edgePoints(edge: ElkExtendedEdge): Point[] {
  const points: ElkPoint[] = [];
  for (const s of edge.sections ?? []) {
    points.push(s.startPoint, ...(s.bendPoints ?? []), s.endPoint);
  }
  // Consecutive sections share their joining point; keep it once.
  return points
    .filter((p, i) => i === 0 || p.x !== points[i - 1].x || p.y !== points[i - 1].y)
    .map(({ x, y }) => ({ x, y }));
}

function fromElkGraph(graph: ElkNode, edges: LayoutEdge[], direction: LayoutDirection): GraphLayout {
  const positions: Record<string, Point> = {};
  const boxes = new Map<string, Box>();
  for (const child of graph.children ?? []) {
    const box = { x: child.x ?? 0, y: child.y ?? 0, width: child.width ?? 0, height: child.height ?? 0 };
    positions[child.id] = { x: box.x, y: box.y };
    boxes.set(child.id, box);
  }
  const routes: Record<string, EdgeRoute> = {};
  for (const edge of graph.edges ?? []) {
    const label = edge.labels?.[0];
    routes[edge.id] =
      label && label.x !== undefined && label.y !== undefined
        ? {
            points: edgePoints(edge),
            label: { x: label.x + (label.width ?? 0) / 2, y: label.y + (label.height ?? 0) / 2 },
          }
        : { points: edgePoints(edge) };
  }
  // The repairs assume edges leave on the right and enter on the left.
  if (direction !== "RIGHT") return { positions, routes };
  const ends = Object.fromEntries(
    edges.flatMap((e) => {
      const [source, target] = [boxes.get(e.source), boxes.get(e.target)];
      return source && target ? [[e.id, { source, target, labelled: !!e.label }]] : [];
    }),
  );
  return { positions, routes: repairWrappedRoutes(routes, ends, [...boxes.values()]) };
}

type Link = Pick<LayoutEdge, "id" | "source" | "target">;

/**
 * The ids of the edges on the longest chain through `edges`, starting from a node nothing leads into: a workflow's
 * happy path, when given only its onward routes (no failure or revision routes). Ties go to the earlier edge, so
 * the workflow's own order decides. Cycles are cut where they are found. Use it to mark `primary` edges.
 */
export function mainPath(edges: Link[]): Set<string> {
  const outgoing = new Map<string, Link[]>();
  for (const e of edges) outgoing.set(e.source, [...(outgoing.get(e.source) ?? []), e]);
  const best = new Map<string, { length: number; via?: Link }>();
  const visiting = new Set<string>();

  const lengthFrom = (id: string): number => {
    const known = best.get(id);
    if (known) return known.length;
    if (visiting.has(id)) return -1;
    visiting.add(id);
    let entry: { length: number; via?: Link } = { length: 0 };
    for (const e of outgoing.get(id) ?? []) {
      const length = 1 + lengthFrom(e.target);
      if (length > entry.length) entry = { length, via: e };
    }
    visiting.delete(id);
    best.set(id, entry);
    return entry.length;
  };

  const targets = new Set(edges.map((e) => e.target));
  const roots = [...new Set(edges.map((e) => e.source))].filter((id) => !targets.has(id));
  const candidates = roots.length ? roots : edges.slice(0, 1).map((e) => e.source);
  let start: string | undefined;
  let longest = -1;
  for (const id of candidates) {
    const length = lengthFrom(id);
    if (length > longest) [start, longest] = [id, length];
  }

  const path = new Set<string>();
  const seen = new Set<string>();
  for (let at = start; at !== undefined && !seen.has(at); at = best.get(at)?.via?.target) {
    seen.add(at);
    const via = best.get(at)?.via;
    if (via) path.add(via.id);
  }
  return path;
}

export type LayoutOptionsIn = {
  direction?: LayoutDirection;
  /**
   * Width / height of the space the graph will be shown in. When set, a long graph wraps into rows (or columns,
   * top to bottom) so the whole drawing has roughly this shape; each row still reads in order. Unset: no wrapping.
   */
  aspectRatio?: number;
};

function wrapOptions(aspectRatio: number | undefined): LayoutOptions {
  if (!aspectRatio || !Number.isFinite(aspectRatio) || aspectRatio <= 0) return {};
  return {
    "elk.aspectRatio": aspectRatio.toFixed(3),
    // Multi-edge wrapping cuts between any two layers, even where failure routes cross the cut as well as the main
    // path (single-edge wrapping can only cut where exactly one edge crosses, so it rarely reached the shape asked).
    "elk.layered.wrapping.strategy": "MULTI_EDGE",
    "elk.layered.wrapping.additionalEdgeSpacing": "20",
  };
}

/**
 * Lays out a step graph left to right (or top to bottom): the primary path on one straight row (or, with
 * `aspectRatio`, wrapped into rows that read in order), branches and failure routes beside it, edges routed
 * orthogonally from each node's out side to the next node's in side. Edges whose source or target is not among
 * `nodes` are ignored.
 */
export async function layoutGraph(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
  opts: LayoutOptionsIn = {},
): Promise<GraphLayout> {
  if (nodes.length === 0) return { positions: {}, routes: {} };
  const elk = await loadElk();
  const graph = toElkGraph(nodes, edges, opts.direction ?? "RIGHT");
  graph.layoutOptions = { ...graph.layoutOptions, ...wrapOptions(opts.aspectRatio) };
  return fromElkGraph(await elk.layout(graph), edges, opts.direction ?? "RIGHT");
}
