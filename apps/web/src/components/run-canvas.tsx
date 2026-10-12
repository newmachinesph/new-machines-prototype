"use client";

import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { useTranslations } from "next-intl";
import { memo, useMemo, useState } from "react";
import { cn } from "@/lib/cn";
import type { NodeType, Run, RunNode } from "@/lib/types";
import { ActorGlyph, NodeStatusPill } from "./ui";

const ACCENT: Record<RunNode["actor"], string> = {
  machine: "before:bg-machine",
  human: "before:bg-human",
  policy: "before:bg-blocked",
  system: "before:bg-grey-300",
  buyer: "before:bg-ink",
};

type StepData = { node: RunNode; selected: boolean };

const Step = memo(function Step({ data }: NodeProps<Node<StepData>>) {
  const { node, selected } = data;
  const t = useTranslations("run.canvas");
  const small = node.type === "trigger" || node.type === "end";
  const waiting = node.status === "WAITING";
  const blocked = node.status === "BLOCKED" || node.status === "FAILED" || node.status === "TIMED_OUT";
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-[10px] border bg-paper py-2.5 pr-3 pl-3.5 text-left shadow-[0_1px_2px_rgb(17_17_17/0.05)] transition-shadow",
        "before:absolute before:inset-y-0 before:left-0 before:w-[3px]",
        ACCENT[node.actor],
        small ? "w-[150px]" : "w-[210px]",
        selected
          ? "border-ink ring-2 ring-ink/10"
          : waiting
            ? "border-human/60"
            : blocked
              ? "border-blocked/50"
              : "border-rule",
        node.status === "CREATED" && "opacity-70",
      )}
    >
      <Handle type="target" position={Position.Left} />
      <div className="flex items-center gap-1.5 text-[11px] text-muted">
        <ActorGlyph actor={node.actor} className="size-2.5" />
        {t(`nodeType.${node.type satisfies NodeType}`)}
        {node.attempts && node.attempts > 1 ? (
          <span className="tnum ml-auto">{t("attempt", { n: node.attempts })}</span>
        ) : null}
      </div>
      <div className="mt-1 text-[13px] leading-snug font-semibold text-ink">{node.label}</div>
      {node.subtitle && !small ? <div className="mt-0.5 truncate text-[11.5px] text-muted">{node.subtitle}</div> : null}
      <div className="mt-2">
        <NodeStatusPill status={node.status} />
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
});

const nodeTypes = { step: Step };

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
  const nodes = useMemo<Node<StepData>[]>(
    () =>
      run.nodes.map((n) => ({
        id: n.id,
        type: "step",
        position: { x: n.x, y: n.y },
        data: { node: n, selected: n.id === selectedId },
        draggable: false,
        connectable: false,
        ariaLabel: t("nodeAria", { label: n.label, status: tNode(n.status) }),
      })),
    [run.nodes, selectedId, t, tNode],
  );

  const edges = useMemo<Edge[]>(
    () =>
      run.edges.map((e) => ({
        id: `${e.from}-${e.to}`,
        source: e.from,
        target: e.to,
        label: e.label,
        type: e.revision ? "default" : "smoothstep",
        className: cn(e.taken && "taken", e.revision && "revision"),
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 14,
          height: 14,
          color: e.taken ? (e.revision ? "#b45309" : "#111111") : "#c5c5cb",
        },
        labelBgPadding: [4, 2] as [number, number],
        focusable: false,
      })),
    [run.edges],
  );

  // Open zoomed in around the step that matters (the initial selection), not the whole graph;
  // long workflows are unreadable when squeezed to fit. Users pan for the rest.
  const [focus] = useState(() => {
    const anchor = run.nodes.find((n) => n.id === selectedId) ?? run.nodes[0];
    return run.nodes.filter((n) => Math.abs(n.x - anchor.x) <= 620).map((n) => ({ id: n.id }));
  });

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={(_, n) => onSelect(n.id)}
      fitView
      fitViewOptions={{ padding: 0.14, nodes: focus, maxZoom: 1 }}
      minZoom={0.35}
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
        if (picked && "id" in picked) onSelect(picked.id);
      }}
    >
      <Background gap={20} size={1} color="#dcdde1" />
      <Controls showInteractive={false} position="bottom-right" />
    </ReactFlow>
  );
}
