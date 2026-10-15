/*!
 * @license Apache-2.0
 * Adapted from Synergy Codes Workflow Builder, apps/demo/src/app/plugins/copy-paste/libs/
 * (utils/get-selection-with-nodes-between.ts, utils/calculate-pasted-node-position.ts, utils/paste-elements.ts,
 * utils/position-utils.ts (the source of getNodesCenterPoint) and the GetHandleId type in types.ts)
 * (https://github.com/synergycodes/workflowbuilder, commit 4bbe6512f590f5aea90bce0134f9630e8961a594).
 * Copyright 2025-2026 Synergia Pro Sp. z o.o. Licensed under the Apache License, Version 2.0 (see ./LICENSE).
 *
 * Changes from the original: pure functions that take nodes and edges and return new arrays, instead of calling
 * getters and setters; getSelectionWithNodesBetween no longer mutates the selection it is given; the centre of
 * the copied nodes is computed here from their positions alone, not from their measured bounds (the original
 * imports getNodesCenterPoint and point helpers that read node width and height); generateId receives the node
 * being pasted; a pasted edge's id comes from `edgeId` instead of crypto.randomUUID(), so it keeps the editor's
 * own id form; an edge end point that was not among the copied nodes falls back to the original node's id
 * instead of being dropped.
 */
import type { Edge, Node, XYPosition } from "@xyflow/react";

export type Selection<N extends Node, E extends Edge> = { nodes: N[]; edges: E[] };

export type GetHandleId = (params: {
  /** The type of handle to get the id for. */
  type: "source" | "target";
  /** The id of the new node. */
  newNodeId: string;
  /** The id of the copied node's handle. */
  oldHandleId: string | null;
  /** The id of the copied node. */
  oldNodeId: string;
}) => string | null;

const getEdgesByNodeId = <E extends Edge>(nodeId: string, edges: E[]) =>
  edges.filter((edge) => edge.source === nodeId || edge.target === nodeId);

/** The chosen nodes and every edge that runs between two of them. */
export function getSelectionWithNodesBetween<N extends Node, E extends Edge>(nodes: N[], edges: E[]): Selection<N, E> {
  const nodesIds = new Set(nodes.map((node) => node.id));
  const allEdges = nodes.flatMap((node) => getEdgesByNodeId(node.id, edges));
  const uniqueEdges = [...new Map(allEdges.map((edge) => [edge.id, edge])).values()];
  return { nodes, edges: uniqueEdges.filter((edge) => nodesIds.has(edge.source) && nodesIds.has(edge.target)) };
}

export function getNodesCenterPoint(nodes: Node[]): XYPosition {
  const xs = nodes.map((node) => node.position.x);
  const ys = nodes.map((node) => node.position.y);
  return { x: (Math.min(...xs) + Math.max(...xs)) / 2, y: (Math.min(...ys) + Math.max(...ys)) / 2 };
}

export const calculateNodePastePositionOffset = (nodes: Node[], pastePosition: XYPosition): XYPosition => {
  const nodesCenterPoint = getNodesCenterPoint(nodes);
  return { x: pastePosition.x - nodesCenterPoint.x, y: pastePosition.y - nodesCenterPoint.y };
};

/** Pastes `elements` centred on `position`: new ids, edges remapped, the pasted elements selected. */
export function pasteElements<N extends Node, E extends Edge>({
  elements,
  position,
  nodes,
  edges,
  generateId,
  getHandleId,
  edgeId,
}: {
  elements: Selection<N, E>;
  position: XYPosition;
  nodes: N[];
  edges: E[];
  generateId: (node: N) => string;
  getHandleId: GetHandleId;
  edgeId: (edge: { source: string; target: string; sourceHandle: string | null }) => string;
}): { nodes: N[]; edges: E[] } {
  const mappedIds: Record<string, string> = {};
  let nextNodes = nodes;
  let nextEdges = edges;

  if (elements.nodes.length > 0) {
    const nodePasteOffset = calculateNodePastePositionOffset(elements.nodes, position);
    const nodesToPaste = elements.nodes.map((node) => {
      const newId = generateId(node);
      mappedIds[node.id] = newId;
      return {
        ...node,
        id: newId,
        position: { x: node.position.x + nodePasteOffset.x, y: node.position.y + nodePasteOffset.y },
        selected: true,
      };
    });
    nextNodes = [...nodes.map((node) => (node.selected ? { ...node, selected: false } : node)), ...nodesToPaste];
  }

  if (elements.edges.length > 0) {
    const pasted = elements.edges.map(({ source, target, sourceHandle = null, targetHandle = null, ...edge }) => {
      const newSource = mappedIds[source] || source;
      const newTarget = mappedIds[target] || target;
      const newSourceHandle = getHandleId({
        type: "source",
        newNodeId: newSource,
        oldNodeId: source,
        oldHandleId: sourceHandle,
      });
      return {
        ...edge,
        selected: true,
        sourceHandle: newSourceHandle,
        targetHandle: getHandleId({
          type: "target",
          newNodeId: newTarget,
          oldNodeId: target,
          oldHandleId: targetHandle,
        }),
        source: newSource,
        target: newTarget,
        id: edgeId({ source: newSource, target: newTarget, sourceHandle: newSourceHandle }),
      } as unknown as E;
    });
    nextEdges = [...edges.map((edge) => (edge.selected ? { ...edge, selected: false } : edge)), ...pasted];
  }

  return { nodes: nextNodes, edges: nextEdges };
}
