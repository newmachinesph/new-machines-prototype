import type { RunEdge, RunNode } from "./types";

/** Route labels that lead away from the happy path (mirrors the API projection's failure routes). */
export const FAILURE_ROUTES: ReadonlySet<string> = new Set([
  "blocked",
  "rejected",
  "timeout",
  "denied",
  "error",
  "fail",
  "failed",
]);

export const isFailureRoute = (label: string | undefined) => label !== undefined && FAILURE_ROUTES.has(label);

/** A step on the canvas: a run node, or a stub copy of an end node (`stubOf` is the original's id, `stubFrom` its source's). */
export type CanvasNode = RunNode & { stubOf?: string; stubFrom?: string };

const STUB_OFFSET = { x: 60, y: 130 };
const LABEL_JOIN = " · ";

/**
 * Gives every step its own small copy of an end it reaches only through failure routes ("failed" after a denied
 * read), instead of one shared end that every failure line has to run across the canvas to. A stub keeps the
 * original's label; it takes the original's status only if its own route was taken (the run ended there), and is
 * otherwise not started. Its id is `${end}@${source}`, stable across renders. Several failure routes from one step
 * to that end share one stub and one edge, labelled with all of them. Everything else is unchanged.
 */
export function withTerminalStubs(nodes: RunNode[], edges: RunEdge[]): { nodes: CanvasNode[]; edges: RunEdge[] } {
  const ends = new Map(nodes.filter((n) => n.type === "end").map((n) => [n.id, n]));
  const failureOnly = new Set(
    [...ends.keys()].filter((id) => {
      const incoming = edges.filter((e) => e.to === id);
      return incoming.length > 0 && incoming.every((e) => isFailureRoute(e.label));
    }),
  );
  if (failureOnly.size === 0) return { nodes, edges };

  const stubIdOf = (e: RunEdge) => (failureOnly.has(e.to) ? `${e.to}@${e.from}` : undefined);
  // Every failure route into a stubbed end, grouped by the stub it becomes (in first-seen order).
  const routes = new Map<string, RunEdge[]>();
  for (const e of edges) {
    const id = stubIdOf(e);
    if (id) routes.set(id, [...(routes.get(id) ?? []), e]);
  }
  const stubEdges = new Map(
    [...routes].map(([id, group]) => [
      id,
      {
        from: group[0].from,
        to: id,
        label: group
          .map((e) => e.label)
          .filter(Boolean)
          .join(LABEL_JOIN),
        taken: group.some((e) => !!e.taken),
      } satisfies RunEdge,
    ]),
  );
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const stubs = [...stubEdges].map(([id, edge]): CanvasNode => {
    const end = ends.get(routes.get(id)![0].to)!;
    const source = byId.get(edge.from);
    return {
      ...end,
      id,
      stubOf: end.id,
      stubFrom: edge.from,
      status: edge.taken ? end.status : "CREATED",
      x: (source?.x ?? end.x) + STUB_OFFSET.x,
      y: (source?.y ?? end.y) + STUB_OFFSET.y,
    };
  });
  // Each stub edge goes where its first failure route was; the others it absorbed are dropped.
  const outEdges = edges.flatMap((e) => {
    const id = stubIdOf(e);
    if (!id) return [e];
    return routes.get(id)![0] === e ? [stubEdges.get(id)!] : [];
  });
  return { nodes: [...nodes.filter((n) => !failureOnly.has(n.id)), ...stubs], edges: outEdges };
}
