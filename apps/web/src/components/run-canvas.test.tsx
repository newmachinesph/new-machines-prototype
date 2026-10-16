import { act, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RUN_1042 } from "@/data/runs-recon";
import { layoutGraph, type GraphLayout } from "@/lib/graph-layout";
import type { Run } from "@/lib/types";
import { renderWithIntl } from "@/test/intl";
import { READABLE_ZOOM, RunCanvas, snapAspect } from "./run-canvas";

vi.mock("@/lib/graph-layout", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/graph-layout")>()),
  layoutGraph: vi.fn(),
}));

// The canvas's own fits go through useReactFlow().fitView; spy on it, keep the rest of React Flow real.
const fitView = vi.hoisted(() => vi.fn());
vi.mock("@xyflow/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@xyflow/react")>();
  return { ...actual, useReactFlow: () => ({ ...actual.useReactFlow(), fitView }) };
});

// React Flow measures its container and nodes; jsdom has neither API. Observers are kept so a test can fire one.
const observers: { callback: ResizeObserverCallback; targets: Element[] }[] = [];
vi.stubGlobal(
  "ResizeObserver",
  class {
    targets: Element[] = [];
    constructor(callback: ResizeObserverCallback) {
      observers.push({ callback, targets: this.targets });
    }
    observe(el: Element) {
      this.targets.push(el);
    }
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

function deferred() {
  let resolve!: (layout: GraphLayout) => void;
  const promise = new Promise<GraphLayout>((r) => (resolve = r));
  return { promise, resolve };
}

/** A layout that puts every step of RUN_1042 in one row starting at `x0`. */
const layoutAt = (x0: number): GraphLayout => ({
  positions: Object.fromEntries(RUN_1042.nodes.map((n, i) => [n.id, { x: x0 + i * 300, y: 10 }])),
  routes: {},
});

/** The x of a node's translate(), which React Flow sets from its position. */
function xOf(id: string) {
  const el = document.querySelector<HTMLElement>(`.react-flow__node[data-id="${id}"]`);
  const match = el?.style.transform.match(/translate\(\s*(-?[\d.]+)px/);
  return match ? Number(match[1]) : undefined;
}

const canvas = (run: Run = RUN_1042, selectedId = "decide", onSelect = () => {}) => (
  <div style={{ width: 1200, height: 400 }}>
    <RunCanvas run={run} selectedId={selectedId} onSelect={onSelect} />
  </div>
);
const renderCanvas = (run?: Run, selectedId?: string) => renderWithIntl(canvas(run, selectedId));

/** Gives the canvas's container a size and tells its observer it changed. */
function resizeTo(width: number, height: number) {
  const container = document.querySelector(".react-flow")!.parentElement!;
  vi.spyOn(container, "getBoundingClientRect").mockReturnValue({ width, height } as DOMRect);
  act(() => {
    for (const o of observers.filter((o) => o.targets.includes(container))) o.callback([], {} as ResizeObserver);
  });
}

const fittedIds = (call = fitView.mock.calls.length - 1) =>
  (fitView.mock.calls[call][0].nodes as { id: string }[]).map((n) => n.id);

describe("snapAspect", () => {
  it("snaps to quarter powers of two, and falls back to the usual shape when there is no size", () => {
    expect(snapAspect(1200, 400)).toBeCloseTo(2 ** 1.5);
    expect(snapAspect(1180, 400)).toBeCloseTo(2 ** 1.5);
    expect(snapAspect(800, 800)).toBe(1);
    expect(snapAspect(0, 400)).toBe(2.5);
    expect(snapAspect(1200, 0)).toBe(2.5);
  });
});

describe("RunCanvas", () => {
  // A block body: a function returned from beforeEach would be run as its teardown.
  beforeEach(() => {
    mocked.mockReset();
    fitView.mockReset();
    observers.length = 0;
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows the server's positions until the layout is ready, then the laid-out ones", async () => {
    const pending = deferred();
    mocked.mockReturnValue(pending.promise);
    renderCanvas();

    const human = RUN_1042.nodes.find((n) => n.id === "human")!;
    expect(xOf("human")).toBe(human.x);
    expect(mocked).toHaveBeenCalledTimes(1);
    const [nodes, edges] = mocked.mock.calls[0];
    expect(nodes.find((n) => n.id === "start")).toEqual({ id: "start", width: 150, height: 84 });
    expect(nodes.find((n) => n.id === "human")).toEqual({ id: "human", width: 210, height: 96 });
    // The happy path is the longest chain of onward routes; the revision loop is never on it.
    const primary = edges.filter((e) => e.primary).map((e) => `${e.source}>${e.target}`);
    expect(primary).toEqual([
      "start>read",
      "read>retail",
      "retail>decide",
      "decide>human",
      "human>verify",
      "verify>memory",
      "memory>report",
      "report>done",
    ]);

    await act(async () => pending.resolve(layoutAt(1000)));
    expect(xOf("human")).toBe(layoutAt(1000).positions.human.x);
  });

  it("keeps the server's positions when the layout fails, and logs nothing", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    mocked.mockRejectedValue(new Error("no layout"));
    renderCanvas();
    await act(async () => {});
    expect(mocked).toHaveBeenCalledTimes(1);
    expect(xOf("verify")).toBe(RUN_1042.nodes.find((n) => n.id === "verify")!.x);
    expect(error).not.toHaveBeenCalled();
    error.mockRestore();
  });

  it("keeps its layout while a run streams: new statuses and taken routes do not lay it out again", async () => {
    mocked.mockResolvedValue(layoutAt(1000));
    const { rerender } = renderCanvas();
    await act(async () => {});
    const streamed: Run = {
      ...RUN_1042,
      nodes: RUN_1042.nodes.map((n) => ({ ...n, status: "RUNNING" as const })),
      edges: RUN_1042.edges.map((e) => ({ ...e, taken: !e.taken })),
    };
    rerender(canvas(streamed));
    await act(async () => {});
    expect(mocked).toHaveBeenCalledTimes(1);
    expect(xOf("human")).toBe(layoutAt(1000).positions.human.x);
  });

  it("ignores a layout that arrives after a newer one was asked for", async () => {
    const [first, second] = [deferred(), deferred()];
    mocked.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    renderCanvas();
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "Arrange steps" }));
    expect(mocked).toHaveBeenCalledTimes(2);

    await act(async () => second.resolve(layoutAt(2000)));
    await act(async () => first.resolve(layoutAt(1000)));
    expect(xOf("human")).toBe(layoutAt(2000).positions.human.x);
  });

  it("logs nothing when it unmounts before the layout arrives", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const pending = deferred();
    mocked.mockReturnValue(pending.promise);
    const { unmount } = renderCanvas();
    unmount();
    await act(async () => pending.resolve(layoutAt(1000)));
    expect(error).not.toHaveBeenCalled();
    error.mockRestore();
  });

  it("lays out for the canvas's shape (a default until the canvas can be measured)", async () => {
    mocked.mockResolvedValue({ positions: {}, routes: {} });
    renderCanvas();
    await act(async () => {});
    expect(mocked.mock.calls[0][2]).toEqual({ aspectRatio: 2.5 });
  });

  it("lays out again once a resize settles into a new shape, keeping the old layout until then", async () => {
    const next = deferred();
    mocked.mockResolvedValueOnce(layoutAt(1000)).mockReturnValueOnce(next.promise);
    const { rerender } = renderCanvas();
    await act(async () => {});
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });

    resizeTo(1200, 400);
    act(() => vi.advanceTimersByTime(249));
    expect(mocked).toHaveBeenCalledTimes(1);
    act(() => vi.advanceTimersByTime(1));
    expect(mocked).toHaveBeenCalledTimes(2);
    expect(mocked.mock.calls[1][2]!.aspectRatio).toBeCloseTo(2 ** 1.5);
    // No flash of the server's positions while the new layout is on its way.
    expect(xOf("human")).toBe(layoutAt(1000).positions.human.x);

    // The fit after it centres on the step selected now, not the one selected when the canvas opened.
    rerender(canvas(RUN_1042, "report"));
    fitView.mockClear();
    await act(async () => next.resolve(layoutAt(3000)));
    expect(xOf("human")).toBe(layoutAt(3000).positions.human.x);
    expect(fitView).toHaveBeenCalledTimes(1);
    expect(fittedIds()).toContain("report");
    expect(fittedIds()).not.toContain("decide");
    // The fit keeps the steps readable rather than shrinking them all into view.
    expect(fitView.mock.calls[0][0].minZoom).toBe(READABLE_ZOOM);

    // A resize within the same snap step changes nothing.
    resizeTo(1180, 400);
    act(() => vi.advanceTimersByTime(250));
    expect(mocked).toHaveBeenCalledTimes(2);
  });

  it("draws an end reached only by failure routes as a stub beside each step, selecting the real end", async () => {
    mocked.mockResolvedValue({ positions: {}, routes: {} });
    const onSelect = vi.fn();
    const failed = {
      ...RUN_1042.nodes.find((n) => n.id === "done")!,
      id: "failed",
      label: "Failed",
      status: "FAILED" as const,
    };
    const run = {
      ...RUN_1042,
      nodes: [...RUN_1042.nodes, failed],
      edges: [
        ...RUN_1042.edges,
        { from: "read", to: "failed", label: "denied" },
        { from: "read", to: "failed", label: "error" },
        { from: "verify", to: "failed", label: "fail", taken: true },
      ],
    };
    renderWithIntl(canvas(run, "failed", onSelect));
    await act(async () => {});

    const [nodes, edges] = mocked.mock.calls[0];
    expect(nodes.filter((n) => n.id.startsWith("failed"))).toEqual([
      { id: "failed@read", width: 120, height: 40 },
      { id: "failed@verify", width: 120, height: 40 },
    ]);
    expect(edges.find((e) => e.target === "failed@read")).toMatchObject({ label: "denied · error", primary: false });
    expect(document.querySelector('.react-flow__node[data-id="failed"]')).toBeNull();

    // Each stub says which step it follows and how it went there.
    const read = document.querySelector<HTMLElement>('.react-flow__node[data-id="failed@read"]')!;
    expect(read.getAttribute("aria-label")).toBe("Failed after Read orders and payouts, Not started");
    const stub = document.querySelector<HTMLElement>('.react-flow__node[data-id="failed@verify"]')!;
    expect(stub).toHaveTextContent("Failed");
    expect(stub.getAttribute("aria-label")).toBe("Failed after Independent check, Failed");
    fireEvent.click(stub);
    expect(onSelect).toHaveBeenCalledWith("failed");
  });

  it("re-runs the layout from the Arrange steps control, and fits the view once to the selected step", async () => {
    // A new layout object each time, as ELK gives.
    mocked.mockImplementation(async () => layoutAt(1000));
    const { rerender } = renderCanvas();
    await act(async () => {});
    expect(mocked).toHaveBeenCalledTimes(1);

    rerender(canvas(RUN_1042, "memory"));
    fitView.mockClear();
    await userEvent.click(screen.getByRole("button", { name: "Arrange steps" }));
    await act(async () => {});
    expect(mocked).toHaveBeenCalledTimes(2);
    expect(fitView).toHaveBeenCalledTimes(1);
    expect(fittedIds()).toContain("memory");
  });

  it("still fits the server's positions from Arrange steps when there is no layout", async () => {
    mocked.mockRejectedValue(new Error("no layout"));
    renderCanvas();
    await act(async () => {});
    fitView.mockClear();
    await userEvent.click(screen.getByRole("button", { name: "Arrange steps" }));
    expect(fitView).toHaveBeenCalledTimes(1);
    expect(fittedIds()).toContain("decide");
  });
});
