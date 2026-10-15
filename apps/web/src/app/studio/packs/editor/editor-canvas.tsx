"use client";

import {
  Background,
  ControlButton,
  Controls,
  MarkerType,
  ReactFlow,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type FinalConnectionState,
  type NodeChange,
} from "@xyflow/react";
import { Workflow } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useState, type DragEvent, type KeyboardEvent } from "react";
import { useShallow } from "zustand/react/shallow";
import { useToast } from "@/components/base";
import { RoutedEdge } from "@/components/routed-edge";
import type { DecisionRules } from "@/lib/api/gen/types.gen";
import type { NewStep, StepEdge, StepNode } from "@/lib/builder/graph";
import { layoutInput } from "@/lib/builder/layout";
import { STEP_TYPES, type StepType } from "@/lib/builder/routes";
import { refusalOf, type Link } from "@/lib/builder/rules";
import { useEditor, useEditorApi } from "@/lib/builder/store";
import { layoutGraph } from "@/lib/graph-layout";
import { StepNodeView } from "./step-node";

/** The drag data type the palette and the guided list use for a new step. */
export const STEP_MIME = "application/x-nm-step";

const nodeTypes = { step: StepNodeView };
const edgeTypes = { routed: RoutedEdge };
// As on the run canvas: steps are placed by their vertical centre, and the view opens at most at 1:1. The padding
// keeps the outermost steps and the labels on their edges clear of the pane's sides.
const NODE_ORIGIN: [number, number] = [0, 0.5];
const FIT_OPTIONS = { padding: 0.18, maxZoom: 1 };
const DEFAULT_EDGE = { markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: "#c5c5cb" } };

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

/** A decision's rules from drag data, when they have the shape the canvas draws handles from; otherwise none. */
function rulesOf(value: unknown): DecisionRules | undefined {
  if (!isRecord(value) || !isRecord(value.default) || typeof value.default.route !== "string") return undefined;
  const rules = value.rules ?? [];
  if (!Array.isArray(rules) || !rules.every((r) => isRecord(r) && typeof r.route === "string")) return undefined;
  return value as DecisionRules;
}

/** A dropped step, checked: drag data comes from outside React. */
export function stepFromDrop(raw: string): NewStep | null {
  try {
    const value: unknown = JSON.parse(raw);
    if (!isRecord(value)) return null;
    const { type, config } = value;
    // A pack has exactly one start, and it is already on the canvas.
    if (type === "trigger" || !STEP_TYPES.includes(type as StepType) || !isRecord(config)) return null;
    const rules = rulesOf(value.rules);
    return { type: type as StepType, config, ...(rules ? { rules } : {}) };
  } catch {
    return null;
  }
}

/** Lays the graph out with the shared ELK layout whenever the store asks: on open, after an insert or import, and on Auto-arrange. */
function useAutoLayout() {
  const api = useEditorApi();
  const request = useEditor((s) => s.layoutRequest.n);
  const { fitView } = useReactFlow();
  // Counts layouts put on the canvas. The view is fitted in an effect of the render that placed the steps, so
  // React Flow has their new places when it measures the whole; a frame callback could run before that render.
  const [placed, setPlaced] = useState(0);
  useEffect(() => {
    let live = true;
    // `restores` stamps the request: an undo or redo while ELK works swaps the graph, and the store drops the result.
    const { nodes, edges, restores } = api.getState();
    const input = layoutInput(nodes, edges);
    layoutGraph(input.nodes, input.edges).then(
      (layout) => {
        if (!live) return;
        api.getState().applyLayout(layout, restores);
        setPlaced((n) => n + 1);
      },
      // The steps keep their places; the editor still works.
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [request, api]);
  useEffect(() => {
    if (placed) void fitView(FIT_OPTIONS);
  }, [placed, fitView]);
}

/** The connection a drag described, whichever end it started from. */
function linkOf(state: FinalConnectionState): Link | null {
  const { fromNode, toNode, fromHandle, toHandle } = state;
  if (!fromNode || !toNode || !fromHandle) return null;
  const fromSource = fromHandle.type === "source";
  return fromSource
    ? { source: fromNode.id, sourceHandle: fromHandle.id, target: toNode.id }
    : { source: toNode.id, sourceHandle: toHandle?.id, target: fromNode.id };
}

/**
 * The workflow on a canvas. `readOnly` is for a pack the signed-in member may only read: steps can be selected
 * (their settings still show) but not moved, connected, dropped in, removed or pasted.
 */
export function EditorCanvas({ readOnly = false }: { readOnly?: boolean }) {
  const t = useTranslations("studioCanvas");
  const toast = useToast();
  const api = useEditorApi();
  const { nodes, edges } = useEditor(useShallow((s) => ({ nodes: s.nodes, edges: s.edges })));
  const { screenToFlowPosition } = useReactFlow();
  useAutoLayout();

  const isValidConnection = useCallback(
    (c: Connection | Edge) => {
      const s = api.getState();
      return refusalOf({ source: c.source, target: c.target, sourceHandle: c.sourceHandle }, s.nodes, s.tools) === null;
    },
    [api],
  );

  const onConnectEnd = useCallback(
    (_: unknown, state: FinalConnectionState) => {
      if (state.isValid !== false) return;
      const link = linkOf(state);
      if (!link) return;
      const s = api.getState();
      const refusal = refusalOf(link, s.nodes, s.tools);
      if (refusal) toast(t("refused"), t(`refusal.${refusal}`), "blocked");
    },
    [api, t, toast],
  );

  const onDragOver = useCallback(
    (e: DragEvent) => {
      if (readOnly || !e.dataTransfer.types.includes(STEP_MIME)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
    },
    [readOnly],
  );
  const onDrop = useCallback(
    (e: DragEvent) => {
      if (readOnly) return;
      const step = stepFromDrop(e.dataTransfer.getData(STEP_MIME));
      if (!step) return;
      e.preventDefault();
      api.getState().addStep(step, screenToFlowPosition({ x: e.clientX, y: e.clientY }));
    },
    [api, readOnly, screenToFlowPosition],
  );

  // Shortcuts work while the canvas has focus, so typing in the settings never deletes a step.
  const onKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (readOnly) return;
      const s = api.getState();
      const mod = e.ctrlKey || e.metaKey;
      const key = e.key.toLowerCase();
      if (e.key === "Delete" || e.key === "Backspace") s.removeSelected();
      else if (mod && key === "z" && e.shiftKey) s.redo();
      else if (mod && key === "z") s.undo();
      else if (mod && key === "y") s.redo();
      else if (mod && key === "c") s.copy();
      else if (mod && key === "v") s.paste();
      else return;
      e.preventDefault();
    },
    [api, readOnly],
  );

  const onNodesChange = useCallback((changes: NodeChange<StepNode>[]) => api.getState().onNodesChange(changes), [api]);
  const onEdgesChange = useCallback((changes: EdgeChange<StepEdge>[]) => api.getState().onEdgesChange(changes), [api]);
  const onConnect = useCallback((c: Connection) => void api.getState().connect(c), [api]);
  const onNodeDragStart = useCallback(() => api.getState().beginDrag(), [api]);
  const onNodeDragStop = useCallback(() => api.getState().endDrag(), [api]);
  const autoArrange = useCallback(() => api.getState().requestLayout(true), [api]);

  const ariaLabelConfig = useMemo(
    () => ({
      // Members cannot move steps, so their help leaves the arrow keys out.
      "node.a11yDescription.default": t(readOnly ? "nodeHelpReadOnly" : "nodeHelp"),
      "edge.a11yDescription.default": t("edgeHelp"),
      "controls.ariaLabel": t("zoomControls"),
      "controls.zoomIn.ariaLabel": t("zoomIn"),
      "controls.zoomOut.ariaLabel": t("zoomOut"),
      "controls.fitView.ariaLabel": t("fitView"),
    }),
    [t, readOnly],
  );

  return (
    <div
      role="group"
      aria-label={t("canvas")}
      className="nm-editor size-full"
      onKeyDown={onKeyDown}
      onDragOver={onDragOver}
      onDrop={onDrop}
    >
      <ReactFlow<StepNode, StepEdge>
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        nodeOrigin={NODE_ORIGIN}
        defaultEdgeOptions={DEFAULT_EDGE}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onConnectEnd={onConnectEnd}
        isValidConnection={isValidConnection}
        onNodeDragStart={onNodeDragStart}
        onNodeDragStop={onNodeDragStop}
        nodesDraggable={!readOnly}
        nodesConnectable={!readOnly}
        deleteKeyCode={null}
        minZoom={0.2}
        maxZoom={1.4}
        fitView
        fitViewOptions={FIT_OPTIONS}
        ariaLabelConfig={ariaLabelConfig}
      >
        <Background gap={20} size={1} color="#dcdde1" />
        <Controls showInteractive={false} position="bottom-right">
          {/* The run canvas's arrange control: the same button, laying out with the same ELK layout. A layout is an undoable edit, so a reader does not get it. */}
          {readOnly ? null : (
            <ControlButton onClick={autoArrange} title={t("autoArrange")} aria-label={t("autoArrange")}>
              <Workflow aria-hidden style={{ fill: "none" }} strokeWidth={2.5} />
            </ControlButton>
          )}
        </Controls>
      </ReactFlow>
    </div>
  );
}
