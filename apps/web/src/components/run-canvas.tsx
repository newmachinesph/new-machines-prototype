"use client";

import {
  Background,
  ControlButton,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { Workflow } from "lucide-react";
import { useTranslations } from "next-intl";
import { memo, useCallback, useEffect, useEffectEvent, useMemo, useRef, useState, type RefObject } from "react";
import { cn } from "@/lib/cn";
import { layoutGraph, mainPath, type GraphLayout, type LayoutEdge, type LayoutNode } from "@/lib/graph-layout";
import { isFailureRoute, withTerminalStubs, type CanvasNode } from "@/lib/terminal-stubs";
import type { NodeType, Run, RunEdge, RunNode } from "@/lib/types";
import { RoutedEdge, type RoutedEdgeData } from "./routed-edge";
import { StepCard } from "./step-card";
import { NodeStatusPill } from "./ui";

type StepData = { node: RunNode; selected: boolean };

const isBlocked = (status: RunNode["status"]) => status === "BLOCKED" || status === "FAILED" || status === "TIMED_OUT";

const Step = memo(function Step({ data }: NodeProps<Node<StepData>>) {
  const { node, selected } = data;
  const t = useTranslations("run.canvas");
  const state = selected
    ? "selected"
    : node.status === "WAITING"
      ? "waiting"
      : isBlocked(node.status)
        ? "blocked"
        : "plain";
  return (
    <>
      <Handle type="target" position={Position.Left} />
      <StepCard
        actor={node.actor}
        kind={t(`nodeType.${node.type satisfies NodeType}`)}
        title={node.label}
        subtitle={node.subtitle}
        small={node.type === "trigger" || node.type === "end"}
        state={state}
        dim={node.status === "CREATED"}
        aside={node.attempts && node.attempts > 1 ? t("attempt", { n: node.attempts }) : undefined}
      >
        <div className="mt-2">
          <NodeStatusPill status={node.status} />
        </div>
      </StepCard>
      <Handle type="source" position={Position.Right} />
    </>
  );
});

/** A small copy of an end step, beside the step whose failure routes lead to it (see withTerminalStubs). */
const Stub = memo(function Stub({ data }: NodeProps<Node<StepData>>) {
  const { node, selected } = data;
  const tNode = useTranslations("node");
  const blocked = isBlocked(node.status);
  return (
    <div
      className={cn(
        "flex h-10 w-[120px] flex-col justify-center rounded-lg border bg-paper px-2.5 text-left leading-tight shadow-[0_1px_2px_rgb(17_17_17/0.05)]",
        selected ? "border-ink ring-2 ring-ink/10" : blocked ? "border-blocked/50" : "border-rule",
        node.status === "CREATED" && "opacity-70",
      )}
    >
      <Handle type="target" position={Position.Left} />
      <div className="truncate text-[12px] font-semibold text-ink">{node.label}</div>
      <div className={cn("truncate text-[10.5px]", blocked ? "text-blocked" : "text-muted")}>{tNode(node.status)}</div>
    </div>
  );
});

const nodeTypes = { step: Step, stub: Stub };
const edgeTypes = { routed: RoutedEdge };

// Fixed sizes matching the widths above; heights are estimates. Nodes are placed by their vertical centre
// (NODE_ORIGIN), so a step that renders taller than its estimate still lines up with its neighbours and its edges.
const STEP_SIZE = { width: 210, height: 96 };
const SMALL_SIZE = { width: 150, height: 84 };
const STUB_SIZE = { width: 120, height: 40 };
const NODE_ORIGIN: [number, number] = [0, 0.5];
/** Opening view: the anchor step and the steps near it (this far across, and within its row), at most 1:1 zoom. */
const FOCUS_RADIUS = { x: 620, y: 260 };
const FIT_OPTIONS = { padding: 0.14, maxZoom: 1 };
/** The canvas's usual shape (about 1100 by 420), used until it has been measured, or where it cannot be. */
const DEFAULT_ASPECT = 2.5;
/** Aspect ratios snap to steps of about 19% (quarter powers of two), so small resizes keep the same layout. */
const ASPECT_STEPS_PER_DOUBLING = 4;
const RESIZE_DEBOUNCE_MS = 250;

const sizeOf = (n: CanvasNode) =>
  n.stubOf ? STUB_SIZE : n.type === "trigger" || n.type === "end" ? SMALL_SIZE : STEP_SIZE;
const edgeId = (e: RunEdge) => `${e.from}->${e.to}:${e.label ?? ""}`;

/** width / height snapped to a quarter power of two (see ASPECT_STEPS_PER_DOUBLING); the usual shape when unsized. */
export function snapAspect(width: number, height: number) {
  if (!(width > 0 && height > 0)) return DEFAULT_ASPECT;
  const steps = Math.round(Math.log2(width / height) * ASPECT_STEPS_PER_DOUBLING);
  return 2 ** (steps / ASPECT_STEPS_PER_DOUBLING);
}

/**
 * The container's width / height, snapped (see snapAspect) and debounced, so the layout only changes when the
 * canvas's shape changes meaningfully, not on every pixel of a resize. Null until first measured.
 */
function useAspect(ref: RefObject<HTMLElement | null>) {
  const [aspect, setAspect] = useState<number | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const { width, height } = el.getBoundingClientRect();
      setAspect(snapAspect(width, height));
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const observer = new ResizeObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(measure, RESIZE_DEBOUNCE_MS);
    });
    observer.observe(el);
    return () => {
      clearTimeout(timer);
      observer.disconnect();
    };
  }, [ref]);
  return aspect;
}

type LayoutResult = { graphKey: string; layout: GraphLayout | null; settled: number };

/**
 * Lays the run's graph out with ELK, wrapped to the canvas's shape. Keyed on the graph's shape (ids, types, labels,
 * revision routes), not on statuses, so the layout does not jump while a run streams. A new aspect lays the same
 * graph out again but keeps showing the current layout until the new one lands; only a new graph drops it.
 *
 * `layout` is null until the first layout is ready, or if it fails; the canvas then keeps the server's positions.
 * `settled` counts finished layout runs (laid out or failed): the canvas fits its view on each one.
 */
function useGraphLayout(nodes: CanvasNode[], edges: RunEdge[], aspect: number | null) {
  const graphKey = JSON.stringify([
    nodes.map((n) => [n.id, n.type, n.label]),
    edges.map((e) => [edgeId(e), !!e.revision]),
  ]);
  const [input, setInput] = useState(() => ({ graphKey, ...layoutInput(nodes, edges) }));
  if (input.graphKey !== graphKey) setInput({ graphKey, ...layoutInput(nodes, edges) });
  const [request, setRequest] = useState(0);
  const [result, setResult] = useState<LayoutResult | null>(null);

  useEffect(() => {
    if (aspect === null) return;
    let live = true;
    const settle = (layout: (previous: LayoutResult | null) => GraphLayout | null) => {
      if (live) {
        setResult((previous) => ({
          graphKey: input.graphKey,
          layout: layout(previous),
          settled: (previous?.settled ?? 0) + 1,
        }));
      }
    };
    layoutGraph(input.nodes, input.edges, { aspectRatio: aspect }).then(
      (layout) => settle(() => layout),
      // Fallback: keep the current layout for this graph, else the server's positions. Nothing to report.
      () => settle((previous) => (previous?.graphKey === input.graphKey ? previous.layout : null)),
    );
    return () => {
      live = false;
    };
  }, [input, aspect, request]);

  const relayout = useCallback(() => setRequest((r) => r + 1), []);
  return {
    layout: result?.graphKey === graphKey ? result.layout : null,
    settled: result?.settled ?? 0,
    // Canvas id to run node id (for stubs); changes only with the graph's shape, like the layout.
    originals: input.originals,
    relayout,
  };
}

function layoutInput(
  nodes: CanvasNode[],
  edges: RunEdge[],
): { nodes: LayoutNode[]; edges: LayoutEdge[]; originals: Map<string, string> } {
  const links = edges.map((e) => ({ id: edgeId(e), source: e.from, target: e.to }));
  // The happy path is the longest chain of onward routes. Structural, not `taken`: taken changes while a run
  // streams, and the layout must not. Stub edges carry joined labels ("denied · error"), so test each route.
  const onward = links.filter((_, i) => !edges[i].revision && !isFailureEdge(edges[i]));
  const primary = mainPath(onward);
  return {
    nodes: nodes.map((n) => ({ id: n.id, ...sizeOf(n) })),
    edges: links.map((link, i) => ({ ...link, label: edges[i].label, primary: primary.has(link.id) })),
    originals: new Map(nodes.map((n) => [n.id, n.stubOf ?? n.id])),
  };
}

const isFailureEdge = (e: RunEdge) => !!e.label && e.label.split(" · ").every((route) => isFailureRoute(route));

type Placed = { id: string; original: string; x: number; y: number };

/** The anchor step (or a stub of it, or the first step) and every step near it. */
function focusAround(anchorId: string | undefined, placed: Placed[]) {
  const anchor = placed.find((p) => p.id === anchorId) ?? placed.find((p) => p.original === anchorId) ?? placed[0];
  if (!anchor) return [];
  return placed
    .filter((p) => Math.abs(p.x - anchor.x) <= FOCUS_RADIUS.x && Math.abs(p.y - anchor.y) <= FOCUS_RADIUS.y)
    .map(({ id }) => ({ id }));
}

/**
 * Fits the view around the selected step each time `nonce` changes: once per finished layout run (the first layout,
 * a resize, "Arrange steps"). The selection and positions are read when it fits, so a stream of new node objects or a
 * new selection never pulls the view on its own.
 */
function FitOnSettle({ nonce, anchor, placed }: { nonce: number; anchor?: string; placed: Placed[] }) {
  const { fitView } = useReactFlow();
  const fit = useEffectEvent(() => {
    void fitView({ ...FIT_OPTIONS, nodes: focusAround(anchor, placed) });
  });
  useEffect(() => {
    if (nonce > 0) fit();
  }, [nonce]);
  return null;
}

export function RunCanvas({
  run,
  selectedId,
  onSelect,
}: {
  run: Run;
  selectedId?: string;
  onSelect: (id: string) => void;
}) {
  const t = useTranslations("run.canvas");
  const tNode = useTranslations("node");
  const container = useRef<HTMLDivElement>(null);
  const aspect = useAspect(container);
  const graph = useMemo(() => withTerminalStubs(run.nodes, run.edges), [run.nodes, run.edges]);
  const { layout, settled, originals, relayout } = useGraphLayout(graph.nodes, graph.edges, aspect);
  const select = (id: string) => onSelect(originals.get(id) ?? id);

  // Where each step is now: laid out, or the server's position until (unless) the layout is ready.
  const placed = useMemo<Placed[]>(
    () =>
      graph.nodes.map((n) => ({
        id: n.id,
        original: n.stubOf ?? n.id,
        ...(layout?.positions[n.id] ?? { x: n.x, y: n.y }),
      })),
    [graph.nodes, layout],
  );

  const nodes = useMemo<Node<StepData>[]>(() => {
    const labels = new Map(graph.nodes.map((n) => [n.id, n.label]));
    return graph.nodes.map((n, i) => ({
      id: n.id,
      type: n.stubOf ? "stub" : "step",
      position: { x: placed[i].x, y: placed[i].y + sizeOf(n).height / 2 },
      data: { node: n, selected: (n.stubOf ?? n.id) === selectedId },
      draggable: false,
      connectable: false,
      // Stubs share their end's label; say which step each one follows.
      ariaLabel: n.stubFrom
        ? t("stubAria", { label: n.label, source: labels.get(n.stubFrom) ?? n.stubFrom, status: tNode(n.status) })
        : t("nodeAria", { label: n.label, status: tNode(n.status) }),
    }));
  }, [graph.nodes, placed, selectedId, t, tNode]);

  // Per-edge route data changes only with the layout, so routed edges keep their props while a run streams.
  const routeData = useMemo(
    () =>
      new Map(
        Object.entries(layout?.routes ?? {}).map(([id, route]) => [
          id,
          { points: route.points, labelAt: route.label } satisfies RoutedEdgeData,
        ]),
      ),
    [layout],
  );

  const edges = useMemo<Edge[]>(
    () =>
      graph.edges.map((e) => {
        const data = routeData.get(edgeId(e));
        return {
          id: edgeId(e),
          source: e.from,
          target: e.to,
          label: e.label,
          ...(data ? { type: "routed", data } : { type: e.revision ? "default" : "smoothstep" }),
          className: cn(e.taken && "taken", e.revision && "revision"),
          markerEnd: {
            type: MarkerType.ArrowClosed,
            width: 14,
            height: 14,
            color: e.taken ? (e.revision ? "#b45309" : "#111111") : "#c5c5cb",
          },
          labelBgPadding: [4, 2] as [number, number],
          focusable: false,
        };
      }),
    [graph.edges, routeData],
  );

  // Open zoomed in around the step that matters (the initial selection), not the whole graph;
  // long workflows are unreadable when squeezed to fit. Users pan for the rest.
  // Until the layout is ready the server's positions decide the focus; each finished layout fits again (FitOnSettle).
  const [focus] = useState(() => focusAround(selectedId, placed));

  return (
    <div ref={container} className="size-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        nodeOrigin={NODE_ORIGIN}
        onNodeClick={(_, n) => select(n.id)}
        fitView
        fitViewOptions={{ ...FIT_OPTIONS, nodes: focus }}
        minZoom={0.2}
        maxZoom={1.4}
        nodesDraggable={false}
        nodesConnectable={false}
        deleteKeyCode={null}
        elementsSelectable
        ariaLabelConfig={{
          "node.a11yDescription.default": t("nodeHelp"),
          "edge.a11yDescription.default": t("edgeHelp"),
          "controls.ariaLabel": t("zoomControls"),
          "controls.zoomIn.ariaLabel": t("zoomIn"),
          "controls.zoomOut.ariaLabel": t("zoomOut"),
          "controls.fitView.ariaLabel": t("fitView"),
        }}
        onNodesChange={(changes) => {
          // Keyboard selection (Enter or Space on a focused step) arrives as a select change.
          const picked = changes.find((c) => c.type === "select" && c.selected);
          if (picked && "id" in picked) select(picked.id);
        }}
      >
        <Background gap={20} size={1} color="#dcdde1" />
        <Controls showInteractive={false} position="bottom-right">
          <ControlButton onClick={relayout} title={t("arrange")} aria-label={t("arrange")}>
            <Workflow aria-hidden style={{ fill: "none" }} strokeWidth={2.5} />
          </ControlButton>
        </Controls>
        <FitOnSettle nonce={settled} anchor={selectedId} placed={placed} />
      </ReactFlow>
    </div>
  );
}
