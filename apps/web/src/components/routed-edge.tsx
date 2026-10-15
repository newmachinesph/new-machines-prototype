"use client";

import { BaseEdge, EdgeLabelRenderer, type Edge, type EdgeProps } from "@xyflow/react";
import { memo } from "react";
import type { Point } from "@/lib/graph-layout";

export type RoutedEdgeData = { points: Point[]; labelAt?: Point };

const CORNER_RADIUS = 8;

/**
 * Pins a laid-out route to the handles React Flow actually rendered. The layout's end points sit on the node
 * boxes; the handles sit a few pixels outside them. The first and last segments leave and enter horizontally, so
 * the neighbouring bend moves with the end point and the route stays orthogonal.
 */
export function pinRoute(points: Point[], source: Point, target: Point): Point[] {
  if (points.length < 2) return [source, target];
  const out = points.map((p) => ({ ...p }));
  const [first, last] = [points[0], points[points.length - 1]];
  out[0] = source;
  out[out.length - 1] = target;
  if (out.length > 2) {
    if (out[1].y === first.y) out[1].y = source.y;
    if (out[out.length - 2].y === last.y) out[out.length - 2].y = target.y;
  } else if (source.y !== target.y) {
    const midX = (source.x + target.x) / 2;
    out.splice(1, 0, { x: midX, y: source.y }, { x: midX, y: target.y });
  }
  return out;
}

/** An SVG path through the points, with each bend rounded off (never past the middle of a segment). */
export function roundedPath(points: Point[], radius = CORNER_RADIUS): string {
  if (points.length === 0) return "";
  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length - 1; i++) {
    const [prev, at, next] = [points[i - 1], points[i], points[i + 1]];
    const r = Math.min(radius, dist(prev, at) / 2, dist(at, next) / 2);
    const a = toward(at, prev, r);
    const b = toward(at, next, r);
    d += ` L ${a.x} ${a.y} Q ${at.x} ${at.y} ${b.x} ${b.y}`;
  }
  const end = points[points.length - 1];
  return `${d} L ${end.x} ${end.y}`;
}

/** The point halfway along the route, measured along its length. */
export function midpointOf(points: Point[]): Point {
  const total = points.slice(1).reduce((sum, p, i) => sum + dist(points[i], p), 0);
  let left = total / 2;
  for (let i = 1; i < points.length; i++) {
    const step = dist(points[i - 1], points[i]);
    if (step >= left && step > 0) return toward(points[i - 1], points[i], left);
    left -= step;
  }
  return points[0] ?? { x: 0, y: 0 };
}

function dist(a: Point, b: Point) {
  return Math.hypot(b.x - a.x, b.y - a.y);
}

function toward(from: Point, to: Point, by: number): Point {
  const d = dist(from, to);
  if (d === 0) return { ...from };
  return { x: from.x + ((to.x - from.x) * by) / d, y: from.y + ((to.y - from.y) * by) / d };
}

/** Draws a route computed by the layout, with its label where the layout reserved room for it. */
export const RoutedEdge = memo(function RoutedEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  data,
  label,
  markerEnd,
  style,
}: EdgeProps<Edge<RoutedEdgeData, "routed">>) {
  const points = pinRoute(data?.points ?? [], { x: sourceX, y: sourceY }, { x: targetX, y: targetY });
  const at = data?.labelAt ?? midpointOf(points);
  return (
    <>
      <BaseEdge id={id} path={roundedPath(points)} markerEnd={markerEnd} style={style} />
      {label ? (
        <EdgeLabelRenderer>
          <div
            className="nodrag nopan pointer-events-none absolute rounded-sm bg-stage px-1.5 text-[11px] leading-4 font-medium whitespace-nowrap text-grey-700"
            style={{ transform: `translate(-50%, -50%) translate(${at.x}px, ${at.y}px)` }}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
});
