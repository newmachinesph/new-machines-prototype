import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReactFlowProvider } from "@xyflow/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createEditorStore, EditorStoreContext } from "@/lib/builder/store";
import { OVERDUE, PALETTE } from "@/lib/builder/test-fixtures";
import { layoutGraph } from "@/lib/graph-layout";
import { renderWithIntl } from "@/test/intl";
import { EditorCanvas, STEP_MIME, stepFromDrop } from "./editor-canvas";
import { StepIssuesContext } from "./step-node";

vi.mock("@/lib/graph-layout", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/graph-layout")>()),
  layoutGraph: vi.fn(),
}));
// React Flow re-measures a node's handles on request; jsdom cannot measure, so the request itself is checked.
const updateNodeInternals = vi.hoisted(() => vi.fn());
vi.mock("@xyflow/react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@xyflow/react")>()),
  useUpdateNodeInternals: () => updateNodeInternals,
}));
const toast = vi.hoisted(() => vi.fn());
vi.mock("@/components/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/base")>()),
  useToast: () => toast,
}));

// React Flow measures its container and nodes; jsdom has neither API.
vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);
vi.stubGlobal(
  "DOMMatrixReadOnly",
  class {
    m22 = 1;
  },
);

const mocked = vi.mocked(layoutGraph);

function renderEditor(issues: ReadonlyMap<string, number> = new Map()) {
  const store = createEditorStore({ draft: OVERDUE, palette: PALETTE });
  renderWithIntl(
    <EditorStoreContext.Provider value={store}>
      <StepIssuesContext.Provider value={issues}>
        <ReactFlowProvider>
          <div style={{ width: 1200, height: 500 }}>
            <EditorCanvas />
          </div>
        </ReactFlowProvider>
      </StepIssuesContext.Provider>
    </EditorStoreContext.Provider>,
  );
  return store;
}

describe("EditorCanvas", () => {
  beforeEach(() => {
    toast.mockReset();
    mocked.mockReset();
    mocked.mockImplementation(async (nodes) => ({
      positions: Object.fromEntries(nodes.map((n, i) => [n.id, { x: i * 300, y: 0 }])),
      routes: {},
    }));
  });

  it("lays the pack out when it opens, with the shared layout", async () => {
    const store = renderEditor();
    await waitFor(() => expect(store.getState().nodes.find((n) => n.id === "send")?.position.x).toBe(8 * 300));
    const [nodes, edges] = mocked.mock.calls[0];
    expect(nodes.find((n) => n.id === "approve")).toEqual({ id: "approve", width: 210, height: 96 });
    expect(edges.find((e) => e.id === "approve:denied")?.primary).toBe(false);
    expect(store.getState().history.past).toHaveLength(0);
  });

  it("draws each step with its kind and what it uses, and marks the step that changes data", () => {
    renderEditor();
    expect(screen.getByText("Gmail: Create draft")).toBeInTheDocument();
    expect(screen.getByText("Collections Agent")).toBeInTheDocument();
    expect(screen.getAllByText("Changes data")).toHaveLength(1);
    expect(screen.getAllByText("Human review").length).toBeGreaterThan(0);
  });

  it("shows how many problems a step has", () => {
    renderEditor(new Map([["review", 2]]));
    expect(screen.getByText("2 problems")).toBeInTheDocument();
  });

  it("auto-arranges as a step that can be undone", async () => {
    const store = renderEditor();
    await waitFor(() => expect(mocked).toHaveBeenCalledTimes(1));
    await userEvent.click(screen.getByRole("button", { name: "Auto-arrange" }));
    await waitFor(() => expect(store.getState().history.past).toHaveLength(1));
    expect(mocked).toHaveBeenCalledTimes(2);
  });

  it("adds a step dropped from the palette", () => {
    const store = renderEditor();
    const pane = document.querySelector(".react-flow");
    if (!pane) throw new Error("no canvas");
    const data = JSON.stringify({ type: "approval", config: { title: "Second look" } });
    fireEvent.drop(pane, {
      dataTransfer: { getData: (t: string) => (t === STEP_MIME ? data : ""), types: [STEP_MIME] },
    });
    expect(store.getState().nodes.find((n) => n.id === "approve_2")?.data.config.title).toBe("Second look");
  });

  it("deletes, undoes and redoes from the keyboard", () => {
    const store = renderEditor();
    act(() => store.getState().select("verify"));
    const canvas = screen.getByRole("group", { name: "Workflow canvas" });
    fireEvent.keyDown(canvas, { key: "Delete" });
    expect(store.getState().nodes.some((n) => n.id === "verify")).toBe(false);
    fireEvent.keyDown(canvas, { key: "z", ctrlKey: true });
    expect(store.getState().nodes.some((n) => n.id === "verify")).toBe(true);
    fireEvent.keyDown(canvas, { key: "z", ctrlKey: true, shiftKey: true });
    expect(store.getState().nodes.some((n) => n.id === "verify")).toBe(false);
  });

  it("copies, pastes and redoes with Ctrl+Y from the keyboard", () => {
    const store = renderEditor();
    act(() => store.getState().select("verify"));
    const canvas = screen.getByRole("group", { name: "Workflow canvas" });
    fireEvent.keyDown(canvas, { key: "c", ctrlKey: true });
    fireEvent.keyDown(canvas, { key: "v", metaKey: true });
    expect(store.getState().nodes.some((n) => n.id === "verify_2")).toBe(true);
    fireEvent.keyDown(canvas, { key: "z", ctrlKey: true });
    expect(store.getState().nodes.some((n) => n.id === "verify_2")).toBe(false);
    fireEvent.keyDown(canvas, { key: "y", ctrlKey: true });
    expect(store.getState().nodes.some((n) => n.id === "verify_2")).toBe(true);
  });

  it("will not delete the start step from the keyboard", () => {
    const store = renderEditor();
    act(() => store.getState().select("start"));
    fireEvent.keyDown(screen.getByRole("group", { name: "Workflow canvas" }), { key: "Backspace" });
    expect(store.getState().nodes.some((n) => n.id === "start")).toBe(true);
  });

  it("asks React Flow to re-measure a step's handles when its outcomes change, and only then", () => {
    const store = renderEditor();
    const check = store.getState().nodes.find((n) => n.id === "check");
    if (!check?.data.rules) throw new Error("no decision");
    updateNodeInternals.mockClear();
    const review = store.getState().nodes.find((n) => n.id === "review");
    act(() => store.getState().updateStep("review", { config: { ...review?.data.config, title: "Look" } }));
    expect(updateNodeInternals).not.toHaveBeenCalled();
    const rules = {
      ...check.data.rules,
      rules: [
        ...(check.data.rules.rules ?? []),
        {
          when: "size(nodes.plan.output.messages) > 50",
          route: "escalate",
          verdict: "HUMAN_REVIEW" as const,
          explanation: "Many.",
        },
      ],
    };
    act(() => store.getState().updateStep("check", { rules }));
    expect(updateNodeInternals).toHaveBeenCalledWith("check");
    // Handles are drag targets only, hidden from assistive technology; the Goes to choices are the accessible path.
    const handle = document.querySelector('[data-handleid="escalate"]');
    expect(handle).not.toBeNull();
    expect(handle).toHaveAttribute("aria-hidden", "true");
    expect(handle).not.toHaveAttribute("aria-label");
  });
});

describe("stepFromDrop", () => {
  it("rejects what is not a step", () => {
    expect(stepFromDrop("not json")).toBeNull();
    expect(stepFromDrop("null")).toBeNull();
    expect(stepFromDrop(JSON.stringify({ type: "parallel", config: {} }))).toBeNull();
    expect(stepFromDrop(JSON.stringify({ type: "approval" }))).toBeNull();
    expect(stepFromDrop(JSON.stringify({ type: "approval", config: ["a"] }))).toBeNull();
  });

  it("rejects a start step: a pack has exactly one", () => {
    expect(stepFromDrop(JSON.stringify({ type: "trigger", config: {} }))).toBeNull();
  });

  it("keeps a decision's rules when they are well formed, and drops them when they are not", () => {
    const rules = {
      question: "Any?",
      rules: [{ when: "x > 1", route: "many", verdict: "APPROVED", explanation: "Many." }],
      default: { route: "few", verdict: "APPROVED", explanation: "Few." },
    };
    expect(stepFromDrop(JSON.stringify({ type: "decision", config: {}, rules }))).toEqual({
      type: "decision",
      config: {},
      rules,
    });
    expect(stepFromDrop(JSON.stringify({ type: "decision", config: {}, rules: { question: "Any?" } }))).toEqual({
      type: "decision",
      config: {},
    });
    const noRoute = { ...rules, rules: [{ when: "x" }] };
    expect(stepFromDrop(JSON.stringify({ type: "decision", config: {}, rules: noRoute }))).toEqual({
      type: "decision",
      config: {},
    });
  });
});
