import type { EdgeRoute, Point } from "./graph-layout";

/** A node's box in layout coordinates (top-left corner and size). */
export type Box = { x: number; y: number; width: number; height: number };
/** One straight piece of a route. */
export type Segment = { a: Point; b: Point };
type Band = { top: number; bottom: number };

const EPS = 0.5;
const CLEARANCE = 20;
const LANE_SPACING = 10;
/** How many lanes a route tries, one `LANE_SPACING` apart, before it settles for the first. */
const MAX_LANES = 12;

const span = (p: number, q: number): [number, number] => (p < q ? [p, q] : [q, p]);
const isHorizontal = (s: Segment) => Math.abs(s.a.y - s.b.y) < EPS;
export const segmentsOf = (points: Point[]): Segment[] => points.slice(1).map((b, i) => ({ a: points[i], b }));

/** True when `s` lies on the same line as one of `taken` and shares more than a pixel of it. */
function runsAlong(s: Segment, taken: Segment[]) {
  const horizontal = isHorizontal(s);
  const [s0, s1] = horizontal ? span(s.a.x, s.b.x) : span(s.a.y, s.b.y);
  return taken.some((u) => {
    if (isHorizontal(u) !== horizontal) return false;
    if (Math.abs(horizontal ? s.a.y - u.a.y : s.a.x - u.a.x) >= EPS) return false;
    const [u0, u1] = horizontal ? span(u.a.x, u.b.x) : span(u.a.y, u.b.y);
    return Math.min(s1, u1) - Math.max(s0, u0) > 1;
  });
}

/** True when the route leaves the source's right side, enters the target's left side, and only turns at right angles. */
export function isSoundRoute(points: Point[], s: Box, t: Box) {
  if (points.length < 2) return false;
  const [first, last] = [points[0], points[points.length - 1]];
  const attached =
    Math.abs(first.x - (s.x + s.width)) <= 2 &&
    first.y >= s.y - EPS &&
    first.y <= s.y + s.height + EPS &&
    Math.abs(last.x - t.x) <= 2 &&
    last.y >= t.y - EPS &&
    last.y <= t.y + t.height + EPS;
  const orthogonal = segmentsOf(points).every((s) => isHorizontal(s) || Math.abs(s.a.x - s.b.x) < EPS);
  return attached && orthogonal;
}

/** The rows of a wrapped layout, top to bottom: boxes that overlap vertically, directly or through others, share one. */
function rowsOf(boxes: Box[]): Band[] {
  const rows: Band[] = [];
  for (const b of [...boxes].sort((p, q) => p.y - q.y)) {
    const last = rows[rows.length - 1];
    if (last && b.y < last.bottom) rows[rows.length - 1] = { ...last, bottom: Math.max(last.bottom, b.y + b.height) };
    else rows.push({ top: b.y, bottom: b.y + b.height });
  }
  return rows;
}

type Lane = { start: number; step: number; limit: number; fallback: number };

/**
 * The first of `start`, `start + step`, ... that stays short of `limit` and whose segment does not run along a taken
 * one; `fallback` when even `start` is past the limit (a narrow gap), and `start` when every lane is taken.
 */
function freeLane({ start, step, limit, fallback }: Lane, segmentAt: (v: number) => Segment, taken: Segment[]) {
  const past = (v: number) => (step > 0 ? v > limit : v < limit);
  if (past(start)) return fallback;
  for (let i = 0; i < MAX_LANES && !past(start + i * step); i++) {
    if (!runsAlong(segmentAt(start + i * step), taken)) return start + i * step;
  }
  return start;
}

const between = (p: number, q: number) => (Number.isFinite(p) && Number.isFinite(q) ? (p + q) / 2 : undefined);

/**
 * An orthogonal route from `s`'s right side to `t`'s left side for an edge whose route ELK's wrapping left broken.
 * It leaves `s` into the gap beside its column, and runs along the gaps between rows (bands of steps that overlap
 * vertically), which hold no steps. It takes the first of these that passes through no other step:
 * - to a row further down: along the gap above that whole row;
 * - along the gap below the source's row (the way within one row, forwards or back);
 * - below the source's row, round the left of everything, and above the target's row (always clear).
 * Every lane (each vertical and each run along a gap) takes the first free slot, one `LANE_SPACING` apart, so two
 * rerouted edges never run along each other or along `taken` (the routes already drawn). The label goes on the last
 * run along a gap.
 */
export function routeAcrossRows(s: Box, t: Box, boxes: Box[], taken: Segment[]): EdgeRoute {
  const rows = rowsOf(boxes);
  const rowOf = (b: Box) => rows.findIndex((r) => b.y < r.bottom && b.y + b.height > r.top);
  const [si, ti] = [rowOf(s), rowOf(t)];
  const inRow = (i: number) => boxes.filter((b) => rowOf(b) === i);
  const [sy, ty] = [s.y + s.height / 2, t.y + t.height / 2];

  // The gaps next to each row; a gap at the edge of the drawing is open.
  const above = (i: number): Lane => {
    const prev = i > 0 ? rows[i - 1].bottom : -Infinity;
    const start = rows[i].top - CLEARANCE;
    return { start, step: -LANE_SPACING, limit: prev + LANE_SPACING, fallback: between(prev, rows[i].top) ?? start };
  };
  const below = (i: number): Lane => {
    const next = i < rows.length - 1 ? rows[i + 1].top : Infinity;
    const start = rows[i].bottom + CLEARANCE;
    return { start, step: LANE_SPACING, limit: next - LANE_SPACING, fallback: between(rows[i].bottom, next) ?? start };
  };
  // The gaps beside each column: right of `s`'s (the widest step stacked with it) and left of `t`'s.
  const overlapsX = (b: Box, c: Box) => b.x < c.x + c.width && b.x + b.width > c.x;
  const sColumnRight = Math.max(
    ...inRow(si)
      .filter((b) => overlapsX(b, s))
      .map((b) => b.x + b.width),
  );
  const sNextLeft = Math.min(
    ...inRow(si)
      .filter((b) => b.x >= sColumnRight)
      .map((b) => b.x),
  );
  const tColumnLeft = Math.min(
    ...inRow(ti)
      .filter((b) => overlapsX(b, t))
      .map((b) => b.x),
  );
  const tPrevRight = Math.max(
    ...inRow(ti)
      .filter((b) => b.x + b.width <= tColumnLeft)
      .map((b) => b.x + b.width),
  );
  const right: Lane = {
    start: sColumnRight + CLEARANCE,
    step: LANE_SPACING,
    limit: sNextLeft - LANE_SPACING,
    fallback: between(sColumnRight, sNextLeft) ?? sColumnRight + CLEARANCE,
  };
  const left: Lane = {
    start: tColumnLeft - CLEARANCE,
    step: -LANE_SPACING,
    limit: tPrevRight + LANE_SPACING,
    fallback: between(tPrevRight, tColumnLeft) ?? tColumnLeft - CLEARANCE,
  };
  const vertical = (y0: number, y1: number) => (x: number) => ({ a: { x, y: y0 }, b: { x, y: y1 } });
  const horizontal = (x0: number, x1: number) => (y: number) => ({ a: { x: x0, y }, b: { x: x1, y } });

  const start = { x: s.x + s.width, y: sy };
  const end = { x: t.x, y: ty };

  // Down (or up) beside the source's column, along one gap, and down (or up) beside the target's column.
  const through = (gap: Lane): EdgeRoute => {
    const x1 = freeLane(right, vertical(sy, gap.start), taken);
    const x2 = freeLane(left, vertical(gap.start, ty), taken);
    const y = freeLane(gap, horizontal(x1, x2), taken);
    const points = [start, { x: x1, y: sy }, { x: x1, y }, { x: x2, y }, { x: x2, y: ty }, end];
    return { points, label: { x: (x1 + x2) / 2, y } };
  };
  // Below the source's row, round the left of everything, and above the target's row: clear of every step.
  const around = (): EdgeRoute => {
    const [firstGap, lastGap] = [below(si), above(ti)];
    const x1 = freeLane(right, vertical(sy, firstGap.start), taken);
    const x2 = freeLane(left, vertical(lastGap.start, ty), taken);
    const outside = Math.min(...boxes.map((b) => b.x)) - CLEARANCE;
    const y1 = freeLane(firstGap, horizontal(x1, outside), taken);
    const y2 = freeLane(lastGap, horizontal(outside, x2), taken);
    const xo = freeLane(
      { start: outside, step: -LANE_SPACING, limit: -Infinity, fallback: outside },
      vertical(y1, y2),
      taken,
    );
    const points = [
      start,
      { x: x1, y: sy },
      { x: x1, y: y1 },
      { x: xo, y: y1 },
      { x: xo, y: y2 },
      { x: x2, y: y2 },
      { x: x2, y: ty },
      end,
    ];
    return { points, label: { x: (xo + x2) / 2, y: y2 } };
  };

  // The shortest way that passes through no other step: the gap above the target's row, then the one below the
  // source's row; otherwise round the outside.
  const others = boxes.filter((b) => b !== s && b !== t);
  const clear = (route: EdgeRoute) => segmentsOf(route.points).every((seg) => !others.some((b) => crosses(seg, b)));
  const tries = ti > si ? [above(ti), below(si)] : [below(si)];
  return tries.map(through).find(clear) ?? around();
}

/** The segment passes through the inside of `b`, not just along its edge. */
function crosses(seg: Segment, b: Box) {
  const [[x0, x1], [y0, y1]] = [span(seg.a.x, seg.b.x), span(seg.a.y, seg.b.y)];
  return x1 > b.x + 1 && x0 < b.x + b.width - 1 && y1 > b.y + 1 && y0 < b.y + b.height - 1;
}

/** Where `p` sits along the route `before`, carried over to the same place on `after` (a copy with lanes moved). */
function carry(p: Point, before: Point[], after: Point[]): Point {
  let best = { i: 0, t: 0, d: Infinity };
  segmentsOf(before).forEach(({ a, b }, i) => {
    const [dx, dy] = [b.x - a.x, b.y - a.y];
    const length2 = dx * dx + dy * dy;
    const t = length2 === 0 ? 0 : Math.min(1, Math.max(0, ((p.x - a.x) * dx + (p.y - a.y) * dy) / length2));
    const d = Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
    if (d < best.d) best = { i, t, d };
  });
  const [a, b, a2, b2] = [before[best.i], before[best.i + 1], after[best.i], after[best.i + 1]];
  if (!b) return p;
  const on = { x: a.x + best.t * (b.x - a.x), y: a.y + best.t * (b.y - a.y) };
  return { x: a2.x + best.t * (b2.x - a2.x) + (p.x - on.x), y: a2.y + best.t * (b2.y - a2.y) + (p.y - on.y) };
}

/**
 * ELK runs the lanes of wrapped edges well outside the nodes, where fitting the view (which frames the nodes) cuts them
 * off. Re-space the lanes beyond each side: the innermost sits `CLEARANCE` from the nodes and each further one
 * `LANE_SPACING` beyond it. Lanes keep their order, segments stay straight because equal x stays equal, and a label
 * moves with the part of its route it sits on.
 */
export function pullLanesIn(routes: Record<string, EdgeRoute>, boxes: Box[]): Record<string, EdgeRoute> {
  if (boxes.length === 0) return routes;
  const leftEdge = Math.min(...boxes.map((b) => b.x));
  const rightEdge = Math.max(...boxes.map((b) => b.x + b.width));
  const xs = Object.values(routes).flatMap((r) => r.points.map((p) => p.x));
  const lanes = (outside: number[], edge: number, sign: number) =>
    [...new Set(outside)]
      .sort((a, b) => Math.abs(a - edge) - Math.abs(b - edge))
      .map((x, rank): [number, number] => [x, edge + sign * (CLEARANCE + rank * LANE_SPACING)]);
  const moved = new Map([
    ...lanes(
      xs.filter((x) => x < leftEdge),
      leftEdge,
      -1,
    ),
    ...lanes(
      xs.filter((x) => x > rightEdge),
      rightEdge,
      1,
    ),
  ]);
  if (moved.size === 0) return routes;
  return Object.fromEntries(
    Object.entries(routes).map(([id, r]) => {
      const points = r.points.map((p) => (moved.has(p.x) ? { ...p, x: moved.get(p.x)! } : p));
      return [id, r.label ? { points, label: carry(r.label, r.points, points) } : { points }];
    }),
  );
}

/**
 * Repairs what ELK's wrapping leaves behind in a left-to-right layout: lanes pulled in beside the nodes, then every
 * broken route (see isSoundRoute) redrawn along the gaps between rows, clear of the routes already drawn.
 */
export function repairWrappedRoutes(
  routes: Record<string, EdgeRoute>,
  ends: Record<string, { source: Box; target: Box; labelled: boolean }>,
  boxes: Box[],
): Record<string, EdgeRoute> {
  const brokenIds = Object.keys(routes).filter(
    (id) => ends[id] && !isSoundRoute(routes[id].points, ends[id].source, ends[id].target),
  );
  const sound = pullLanesIn(
    Object.fromEntries(Object.entries(routes).filter(([id]) => !brokenIds.includes(id))),
    boxes,
  );
  const repaired = { ...sound };
  const taken = Object.values(sound).flatMap((r) => segmentsOf(r.points));
  for (const id of brokenIds) {
    const { source, target, labelled } = ends[id];
    const route = routeAcrossRows(source, target, boxes, taken);
    taken.push(...segmentsOf(route.points));
    repaired[id] = labelled ? route : { points: route.points };
  }
  // Keep the caller's order of routes.
  return Object.fromEntries(Object.keys(routes).map((id) => [id, repaired[id]]));
}
