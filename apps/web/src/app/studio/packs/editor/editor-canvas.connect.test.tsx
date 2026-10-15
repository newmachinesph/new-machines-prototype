/**
 * The canvas's connection wiring. A connection drag needs measured handles, which jsdom cannot give, so React Flow
 * is stood in for here and the props the canvas hands it are called directly. editor-canvas.test.tsx keeps React
 * Flow real for everything else.
 */
import { act } from "@testing-library/react";
import type { FinalConnectionState, ReactFlowProps } from "@xyflow/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StepEdge, StepNode } from "@/lib/builder/graph";
import { createEditorStore, EditorStoreContext } from "@/lib/builder/store";
import { OVERDUE, PALETTE } from "@/lib/builder/test-fixtures";
import { renderWithIntl } from "@/test/intl";
import { EditorCanvas } from "./editor-canvas";

type Props = ReactFlowProps<StepNode, StepEdge>;
const flow = vi.hoisted(() => ({ props: null as unknown }));
vi.mock("@xyflow/react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@xyflow/react")>()),
  ReactFlow: (props: unknown) => {
    flow.props = props;
    return <div className="react-flow" />;
  },
  useReactFlow: () => ({ fitView: vi.fn(), screenToFlowPosition: (p: { x: number; y: number }) => p }),
}));
vi.mock("@/lib/graph-layout", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/graph-layout")>()),
  layoutGraph: vi.fn(() => new Promise(() => {})),
}));
const toast = vi.hoisted(() => vi.fn());
vi.mock("@/components/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/base")>()),
  useToast: () => toast,
}));

type Side = { node: string; handle: string; type: "source" | "target" };
/** What React Flow reports when a drag ends on a handle it would not connect. */
const refused = (from: Side, to: Side): FinalConnectionState =>
  ({
    isValid: false,
    fromNode: { id: from.node },
    fromHandle: { id: from.handle, type: from.type, nodeId: from.node },
    toNode: { id: to.node },
    toHandle: { id: to.handle, type: to.type, nodeId: to.node },
  }) as unknown as FinalConnectionState;

function renderCanvas() {
  const store = createEditorStore({ draft: OVERDUE, palette: PALETTE });
  renderWithIntl(
    <EditorStoreContext.Provider value={store}>
      <EditorCanvas />
    </EditorStoreContext.Provider>,
  );
  return { store, props: flow.props as Props };
}

const WRITE_RULE = "A step that changes data in an app must follow an approval's “granted” outcome.";

describe("EditorCanvas connections", () => {
  beforeEach(() => toast.mockReset());

  it("checks a connection by the builder rules while it is dragged", () => {
    const { props } = renderCanvas();
    const link = (source: string, sourceHandle: string, target: string) => ({
      source,
      sourceHandle,
      target,
      targetHandle: "in",
    });
    expect(props.isValidConnection?.(link("draft", "next", "send"))).toBe(false);
    expect(props.isValidConnection?.(link("approve", "granted", "send"))).toBe(true);
    expect(props.isValidConnection?.(link("review", "resolved", "start"))).toBe(false);
  });

  it("says why a refused connection was dropped", () => {
    const { props, store } = renderCanvas();
    const from = { node: "draft", handle: "next", type: "source" as const };
    const to = { node: "send", handle: "in", type: "target" as const };
    act(() => props.onConnectEnd?.(new MouseEvent("mouseup"), refused(from, to)));
    expect(toast).toHaveBeenCalledWith("Those steps cannot be connected", WRITE_RULE, "blocked");
    expect(store.getState().edges.some((e) => e.source === "draft" && e.target === "send")).toBe(false);
  });

  it("reads a drag that started from the way in the right way round", () => {
    const { props } = renderCanvas();
    const from = { node: "send", handle: "in", type: "target" as const };
    const to = { node: "draft", handle: "next", type: "source" as const };
    act(() => props.onConnectEnd?.(new MouseEvent("mouseup"), refused(from, to)));
    expect(toast).toHaveBeenCalledWith("Those steps cannot be connected", WRITE_RULE, "blocked");
  });

  it("says nothing when a drag ends on empty canvas, or on a connection it allowed", () => {
    const { props } = renderCanvas();
    const nowhere = { isValid: false, fromNode: { id: "draft" }, toNode: null } as unknown as FinalConnectionState;
    act(() => props.onConnectEnd?.(new MouseEvent("mouseup"), nowhere));
    const allowed = {
      ...refused(
        { node: "approve", handle: "granted", type: "source" },
        { node: "send", handle: "in", type: "target" },
      ),
      isValid: true,
    };
    act(() => props.onConnectEnd?.(new MouseEvent("mouseup"), allowed as FinalConnectionState));
    expect(toast).not.toHaveBeenCalled();
  });

  it("connects what React Flow accepted", () => {
    const { props, store } = renderCanvas();
    act(() => props.onConnect?.({ source: "approve", sourceHandle: "denied", target: "review", targetHandle: "in" }));
    expect(store.getState().edges.find((e) => e.id === "approve:denied")?.target).toBe("review");
  });
});
