/**
 * The workflow editor's state: one vanilla Zustand store per open pack, given to the editor's components by
 * EditorStoreContext. Every change that should be undoable records the state before it (Synergy's takeSnapshot);
 * drags and typing record once per gesture (the "drag" and "edit" watchers).
 */
import {
  applyEdgeChanges,
  applyNodeChanges,
  type EdgeChange,
  type NodeChange,
  type NodeSelectionChange,
  type XYPosition,
} from "@xyflow/react";
import { createContext, useContext } from "react";
import { createStore, useStore, type StoreApi } from "zustand";
import type { PackDraft, Palette, StepDraft } from "@/lib/api/gen/types.gen";
import type { GraphLayout } from "@/lib/graph-layout";
import {
  edgeIdOf,
  edgeOf,
  entryOf,
  graphToSteps,
  stepsToGraph,
  type NewStep,
  type StepEdge,
  type StepNode,
  type StepNodeData,
} from "./graph";
import { placed, unroute } from "./layout";
import { nextStepId, outcomesOf, STEP_ID } from "./routes";
import { refusalOf, toolIndex, type Link, type Refusal, type ToolIndex } from "./rules";
import {
  getNodesCenterPoint,
  getSelectionWithNodesBetween,
  pasteElements,
  type Selection,
} from "./vendor/synergy/clipboard";
import {
  areSnapshotsEqual,
  emptyHistory,
  processSnapshotWatching,
  redo,
  startSnapshotWatching,
  stopSnapshotWatching,
  takeSnapshot,
  undo,
  type History,
} from "./vendor/synergy/history";

/** Everything about a pack except its steps: what the details form edits. */
export type PackDetails = Omit<PackDraft, "steps" | "entryStep">;
type Snapshot = { nodes: StepNode[]; edges: StepEdge[]; details: PackDetails };

/** How far right of its neighbour a new step goes before the next layout. */
const GRID_X = 260;
const PASTE_OFFSET = 60;
const DRAG = "drag";
const EDIT = "edit";

export type EditorState = Snapshot & {
  palette: Palette;
  tools: ToolIndex;
  selectedId: string | null;
  clipboard: Selection<StepNode, StepEdge> | null;
  history: History<Snapshot>;
  /** Bumped to ask the canvas for a layout; `record` makes the layout an undoable step. */
  layoutRequest: { n: number; record: boolean };
  /**
   * How many times undo or redo has put a stored graph back. A layout is computed off the store, so one asked for
   * before a restore is for a graph that is gone: `applyLayout` drops it when given the count it was asked under.
   */
  restores: number;

  onNodesChange: (changes: NodeChange<StepNode>[]) => void;
  onEdgesChange: (changes: EdgeChange<StepEdge>[]) => void;
  connect: (link: Link) => Refusal | null;
  disconnect: (source: string, outcome: string) => void;
  addStep: (step: NewStep, position?: XYPosition) => string;
  /**
   * `refusal`: the new step could not be connected from the outcome, so nothing was added. `unlinked`: the new step
   * was added, but the step the outcome led to could not be wired after it, so that step is left unconnected.
   * `cut`: the new step has no outcome yet to carry that step (a decision without rules), so the path stops at it.
   */
  insertAfter: (source: string, outcome: string, step: NewStep) => InsertResult;
  updateStep: (id: string, patch: Partial<StepNodeData>, record?: boolean) => void;
  renameStep: (id: string, next: string) => "ok" | "badId" | "taken";
  removeStep: (id: string) => void;
  removeSelected: () => void;
  setDetails: (patch: Partial<PackDetails>, record?: boolean) => void;
  select: (id: string | null) => void;
  startEdit: () => void;
  finishEdit: () => void;
  beginDrag: () => void;
  endDrag: () => void;
  copy: () => void;
  paste: (position?: XYPosition) => void;
  /** Adds a copy of one step beside it, leaving the clipboard as it is. */
  duplicate: (id: string) => void;
  undo: () => void;
  redo: () => void;
  requestLayout: (record: boolean) => void;
  /** Places the steps as laid out; given the `restores` count the layout was asked under, a stale one is dropped. */
  applyLayout: (layout: GraphLayout, restores?: number) => void;
  /** Puts imported steps on the canvas in place of the current ones. False when they have no start: nothing changes. */
  replaceGraph: (steps: StepDraft[]) => boolean;
};

export type EditorStore = StoreApi<EditorState>;
/** Why an insert left the path cut: the new step needs routes before anything can follow it. */
export type InsertCut = "needsRoutes";
export type InsertResult = {
  id: string | null;
  refusal: Refusal | null;
  unlinked: Refusal | null;
  cut: InsertCut | null;
};

const snapshotOf = (s: Snapshot): Snapshot => ({ nodes: s.nodes, edges: s.edges, details: s.details });

/** What a change can be undone to: selection and React Flow's measurements are not edits. */
const comparable = (s: Snapshot) => ({
  nodes: s.nodes.map((n) => ({ id: n.id, position: n.position, data: n.data })),
  edges: s.edges.map((e) => ({ id: e.id, target: e.target })),
  details: s.details,
});

/** Ends a watched gesture: records where it started, unless it changed nothing. */
function settle(history: History<Snapshot>, name: string, present: Snapshot): History<Snapshot> {
  const started = history.watchers[name];
  if (!started) return history;
  return areSnapshotsEqual(comparable(started), comparable(present))
    ? stopSnapshotWatching(history, name)
    : processSnapshotWatching(history, name);
}

const withSelection = (nodes: StepNode[], id: string | null) =>
  nodes.map((n) => (!!n.selected === (n.id === id) ? n : { ...n, selected: n.id === id }));

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * Rewrites `nodes.<old>` to `nodes.<new>` for every pair in `renames`, in every expression of a step's settings.
 * One pass over one alternation, so chained renames (a to a_2 while a_2 goes to a_3) cannot run into each other.
 */
function renameRefs<T>(value: T, renames: ReadonlyMap<string, string>): T {
  if (!renames.size) return value;
  const names = [...renames.keys()].map(escapeRegExp).join("|");
  const pattern = new RegExp(`\\bnodes\\.(${names})\\b`, "g");
  return JSON.parse(JSON.stringify(value).replace(pattern, (_, name: string) => `nodes.${renames.get(name)}`)) as T;
}

const sameData = (a: StepNodeData, b: StepNodeData) => JSON.stringify(a) === JSON.stringify(b);

/**
 * A decision's outcomes are its routes, so changing its rules moves its edges. A name on both sides keeps its edge.
 * Position i is a rename (the edge follows) only when `was[i]` is gone and `now[i]` is new, with the same count.
 * An edge whose route is gone goes, and so does a stray edge already sitting on a renamed-to outcome.
 */
function rerouted(id: string, edges: StepEdge[], was: string[], now: string[]): StepEdge[] {
  const wasSet = new Set(was);
  const nowSet = new Set(now);
  const renamed = new Map<string, string>();
  if (was.length === now.length)
    for (let i = 0; i < was.length; i++) if (!nowSet.has(was[i]) && !wasSet.has(now[i])) renamed.set(was[i], now[i]);
  const renamedTo = new Set(renamed.values());
  return edges.flatMap((e) => {
    if (e.source !== id) return [e];
    const handle = e.sourceHandle ?? "";
    if (renamedTo.has(handle)) return [];
    const outcome = renamed.get(handle) ?? handle;
    if (!nowSet.has(outcome)) return [];
    return outcome === handle ? [e] : [{ ...e, id: edgeIdOf(id, outcome), sourceHandle: outcome, label: outcome }];
  });
}

const isPicked = (c: NodeChange<StepNode>): c is NodeSelectionChange => c.type === "select" && c.selected;

const isStart = (n: StepNode) => n.data.type === "trigger";
/** How many start steps the graph has. A pack has exactly one, so the last one can never be removed. */
export const startCount = (nodes: readonly StepNode[]) => nodes.filter(isStart).length;

export function detailsOf(draft: PackDraft): PackDetails {
  return Object.fromEntries(
    Object.entries(draft).filter(([key]) => key !== "steps" && key !== "entryStep"),
  ) as PackDetails;
}

/** The pack as the API takes it. */
export function draftOf(state: Snapshot): PackDraft {
  return { ...state.details, entryStep: entryOf(state.nodes), steps: graphToSteps(state.nodes, state.edges) };
}

export function createEditorStore({ draft, palette }: { draft: PackDraft; palette: Palette }): EditorStore {
  return createStore<EditorState>()((set, get) => {
    const record = () => set((s) => ({ history: takeSnapshot(s.history, snapshotOf(s)) }));
    const relayout = (s: EditorState) => ({ layoutRequest: { n: s.layoutRequest.n + 1, record: false } });
    const restore = (s: EditorState, step: ReturnType<typeof undo<Snapshot>>) =>
      step
        ? {
            ...step.restore,
            nodes: withSelection(step.restore.nodes, null),
            history: step.history,
            selectedId: null,
            restores: s.restores + 1,
          }
        : s;
    const remove = (wanted: ReadonlySet<string>, wantedEdges: ReadonlySet<string>) => {
      const s = get();
      // A pack has exactly one start, so the last start step stays, with its outgoing edge. An import can bring
      // spare starts: those go, and when every start was chosen the first one is the one kept.
      const starts = s.nodes.filter(isStart);
      const kept = starts.every((n) => wanted.has(n.id)) ? starts[0]?.id : undefined;
      const ids = new Set(s.nodes.filter((n) => wanted.has(n.id) && n.id !== kept).map((n) => n.id));
      const edgeIds = new Set(s.edges.filter((e) => wantedEdges.has(e.id)).map((e) => e.id));
      if (!ids.size && !edgeIds.size) return;
      record();
      set((s) => ({
        nodes: s.nodes.filter((n) => !ids.has(n.id)),
        edges: s.edges.filter((e) => !edgeIds.has(e.id) && !ids.has(e.source) && !ids.has(e.target)),
        selectedId: s.selectedId && ids.has(s.selectedId) ? null : s.selectedId,
      }));
    };
    /** Adds copies of a selection with fresh ids, beside it or at `position`, as one undoable step. */
    const pasteSelection = (selection: Selection<StepNode, StepEdge>, position?: XYPosition) => {
      const s = get();
      const taken = new Set(s.nodes.map((n) => n.id));
      // Old id to new id for every pasted step, so the copies' expressions read from each other, not the originals.
      const renames = new Map<string, string>();
      const generateId = (node: StepNode) => {
        const id = nextStepId(node.data.type, taken);
        taken.add(id);
        renames.set(node.id, id);
        return id;
      };
      const centre = getNodesCenterPoint(selection.nodes);
      const before = new Set(s.edges.map((e) => e.id));
      const pasted = pasteElements({
        elements: selection,
        position: position ?? { x: centre.x + PASTE_OFFSET, y: centre.y + PASTE_OFFSET },
        nodes: s.nodes,
        edges: s.edges,
        generateId,
        getHandleId: ({ oldHandleId }) => oldHandleId,
        edgeId: (e) => edgeIdOf(e.source, e.sourceHandle ?? ""),
      });
      const added = new Set(renames.values());
      record();
      set({
        nodes: pasted.nodes.map((n) => (added.has(n.id) ? { ...n, data: renameRefs(n.data, renames) } : n)),
        // A copied route was laid out for the original's place: draw the copies plainly.
        edges: pasted.edges.map((e) => (before.has(e.id) ? e : { ...e, type: "smoothstep", data: {} })),
        selectedId: added.size === 1 ? [...added][0] : null,
      });
    };
    const newNode = (id: string, step: NewStep, position: XYPosition): StepNode => ({
      id,
      type: "step",
      position,
      selected: true,
      // Its own copy, so steps added from the same blank never share nested settings such as `inputs` or `args`.
      data: { ...step, config: structuredClone(step.config) },
    });

    return {
      ...stepsToGraph(draft.steps),
      details: detailsOf(draft),
      palette,
      tools: toolIndex(palette.tools),
      selectedId: null,
      clipboard: null,
      history: emptyHistory<Snapshot>(),
      layoutRequest: { n: 1, record: false },
      restores: 0,

      onNodesChange: (changes) =>
        set((s) => {
          const moved = new Set(changes.flatMap((c) => (c.type === "position" && c.position ? [c.id] : [])));
          const picked = changes.find(isPicked);
          const dropped = changes.some((c) => c.type === "select" && !c.selected && c.id === s.selectedId);
          return {
            nodes: applyNodeChanges(changes, s.nodes),
            edges: moved.size ? unroute(s.edges, moved) : s.edges,
            selectedId: picked ? picked.id : dropped ? null : s.selectedId,
          };
        }),

      onEdgesChange: (changes) => set((s) => ({ edges: applyEdgeChanges(changes, s.edges) })),

      connect: (link) => {
        const s = get();
        const refusal = refusalOf(link, s.nodes, s.tools);
        if (refusal || !link.sourceHandle) return refusal ?? "unknownOutcome";
        const edge = edgeOf(link.source, link.sourceHandle, link.target);
        if (s.edges.some((e) => e.id === edge.id && e.target === edge.target)) return null;
        record();
        set((t) => ({ edges: [...t.edges.filter((e) => e.id !== edge.id), edge] }));
        return null;
      },

      disconnect: (source, outcome) => {
        const id = edgeIdOf(source, outcome);
        if (!get().edges.some((e) => e.id === id)) return;
        record();
        set((s) => ({ edges: s.edges.filter((e) => e.id !== id) }));
      },

      addStep: (step, position) => {
        const s = get();
        const id = nextStepId(
          step.type,
          s.nodes.map((n) => n.id),
        );
        const near = s.nodes.find((n) => n.id === s.selectedId);
        const right = Math.max(0, ...s.nodes.map((n) => n.position.x));
        const at = position ?? { x: (near?.position.x ?? right) + GRID_X, y: near?.position.y ?? 0 };
        record();
        set((t) => ({ nodes: [...withSelection(t.nodes, null), newNode(id, step, at)], selectedId: id }));
        return id;
      },

      insertAfter: (source, outcome, step) => {
        const s = get();
        const from = s.nodes.find((n) => n.id === source);
        if (!from) return { id: null, refusal: "unknownOutcome", unlinked: null, cut: null };
        const id = nextStepId(
          step.type,
          s.nodes.map((n) => n.id),
        );
        const node = newNode(id, step, { x: from.position.x + GRID_X, y: from.position.y });
        const nodes = [...withSelection(s.nodes, null), node];
        const refusal = refusalOf({ source, sourceHandle: outcome, target: id }, nodes, s.tools);
        if (refusal) return { id: null, refusal, unlinked: null, cut: null };
        const old = s.edges.find((e) => e.id === edgeIdOf(source, outcome));
        const onward = outcomesOf(node.data)[0];
        // The step the outcome led to follows the new step's first outcome, unless the rules refuse that (`unlinked`).
        const unlinked =
          old && onward ? refusalOf({ source: id, sourceHandle: onward, target: old.target }, nodes, s.tools) : null;
        const rewire = old && onward && !unlinked ? [edgeOf(id, onward, old.target)] : [];
        // With no outcome yet, nothing can follow the new step, so the path stops there (`cut`). An end is the one
        // step meant to have no outcome: inserting one ends the path on purpose, so that is not reported.
        const cut = old && !onward && step.type !== "end" ? "needsRoutes" : null;
        record();
        set((t) => ({
          nodes,
          selectedId: id,
          edges: [...t.edges.filter((e) => e.id !== edgeIdOf(source, outcome)), edgeOf(source, outcome, id), ...rewire],
          ...relayout(t),
        }));
        return { id, refusal: null, unlinked, cut };
      },

      updateStep: (id, patch, shouldRecord = true) => {
        const before = get().nodes.find((n) => n.id === id);
        if (!before) return;
        const data: StepNodeData = { ...before.data, ...patch };
        if (sameData(before.data, data)) return;
        if (shouldRecord) record();
        set((s) => {
          const nodes = s.nodes.map((n) => (n.id === id ? { ...n, data } : n));
          if (!("rules" in patch)) return { nodes };
          return { nodes, edges: rerouted(id, s.edges, outcomesOf(before.data), outcomesOf(data)) };
        });
      },

      renameStep: (id, next) => {
        const s = get();
        if (next === id) return "ok";
        if (!STEP_ID.test(next)) return "badId";
        if (s.nodes.some((n) => n.id === next)) return "taken";
        const swap = (v: string) => (v === id ? next : v);
        const renames = new Map([[id, next]]);
        record();
        set((t) => ({
          nodes: t.nodes.map((n) => ({ ...n, id: swap(n.id), data: renameRefs(n.data, renames) })),
          edges: t.edges.map((e) => ({
            ...e,
            id: edgeIdOf(swap(e.source), e.sourceHandle ?? ""),
            source: swap(e.source),
            target: swap(e.target),
          })),
          selectedId: t.selectedId === id ? next : t.selectedId,
        }));
        return "ok";
      },

      removeStep: (id) => remove(new Set([id]), new Set()),

      removeSelected: () => {
        const s = get();
        const ids = new Set(s.nodes.filter((n) => n.selected || n.id === s.selectedId).map((n) => n.id));
        remove(ids, new Set(s.edges.filter((e) => e.selected).map((e) => e.id)));
      },

      setDetails: (patch, shouldRecord = true) => {
        if (shouldRecord) record();
        set((s) => ({ details: { ...s.details, ...patch } }));
      },

      select: (id) => set((s) => ({ selectedId: id, nodes: withSelection(s.nodes, id) })),

      startEdit: () => set((s) => ({ history: startSnapshotWatching(s.history, EDIT, snapshotOf(s)) })),
      finishEdit: () => set((s) => ({ history: settle(s.history, EDIT, snapshotOf(s)) })),
      beginDrag: () => set((s) => ({ history: startSnapshotWatching(s.history, DRAG, snapshotOf(s)) })),
      endDrag: () => set((s) => ({ history: settle(s.history, DRAG, snapshotOf(s)) })),

      copy: () => {
        const s = get();
        // A pack has one start, so the start is never copied.
        const chosen = s.nodes.filter((n) => (n.selected || n.id === s.selectedId) && n.data.type !== "trigger");
        if (chosen.length) set({ clipboard: getSelectionWithNodesBetween(chosen, s.edges) });
      },

      paste: (position) => {
        const { clipboard } = get();
        if (clipboard?.nodes.length) pasteSelection(clipboard, position);
      },

      duplicate: (id) => {
        const s = get();
        const node = s.nodes.find((n) => n.id === id);
        // A pack has one start, so the start is never duplicated.
        if (node && node.data.type !== "trigger") pasteSelection(getSelectionWithNodesBetween([node], s.edges));
      },

      undo: () => set((s) => restore(s, undo(s.history, snapshotOf(s)))),
      redo: () => set((s) => restore(s, redo(s.history, snapshotOf(s)))),

      requestLayout: (shouldRecord) =>
        set((s) => ({ layoutRequest: { n: s.layoutRequest.n + 1, record: shouldRecord } })),

      applyLayout: (layout, restores) => {
        // Asked for before an undo or redo: it is for the graph that was put away, not the one now showing.
        if (restores !== undefined && restores !== get().restores) return;
        if (get().layoutRequest.record) record();
        set((s) => placed(s.nodes, s.edges, layout));
      },

      replaceGraph: (steps) => {
        // The canvas never adds a start, so steps without one could never become a pack: they are not taken.
        if (!steps.some((step) => step.type === "trigger")) return false;
        record();
        set((s) => ({ ...stepsToGraph(steps), selectedId: null, ...relayout(s) }));
        return true;
      },
    };
  });
}

export const EditorStoreContext = createContext<EditorStore | null>(null);

export function useEditorApi(): EditorStore {
  const store = useContext(EditorStoreContext);
  if (!store) throw new Error("The workflow editor's components must be inside its EditorStoreContext.");
  return store;
}

/** Reads from the open pack's store. Return a primitive, a stored value, or use useShallow for several. */
export function useEditor<T>(selector: (state: EditorState) => T): T {
  return useStore(useEditorApi(), selector);
}
