import { describe, expect, it } from "vitest";
import { labelSize, layoutGraph, mainPath, type LayoutEdge, type LayoutNode, type Point } from "./graph-layout";
import { routeAcrossRows } from "./route-repair";

const STEP = { width: 210, height: 96 };
const SMALL = { width: 150, height: 84 };
const STUB = { width: 120, height: 40 };

// The refund pack (definitions/packs/refund-triage/workflow.yaml) as the run canvas lays it out: steps in workflow
// order, each step's routes in declared order, thirteen steps on the happy path and a "nothing" end. The shared
// "failed" end is drawn as one small stub per step that can fail ("failed@requests"), reached by that step's
// failure routes (denied / error / rejected / timeout / fail) on one edge.
const WORKFLOW: [id: string, routes: Record<string, string>][] = [
  ["start", { next: "recall" }],
  ["recall", { next: "requests" }],
  ["requests", { next: "orders", "denied · error": "failed@requests" }],
  ["orders", { next: "charges", "denied · error": "failed@orders" }],
  ["charges", { next: "triage", "denied · error": "failed@charges" }],
  ["triage", { next: "check" }],
  ["check", { nothing: "nothing", human_review: "review" }],
  ["review", { resolved: "draft", "rejected · timeout": "failed@review" }],
  ["draft", { next: "approve" }],
  ["approve", { granted: "send", "denied · timeout": "failed@approve" }],
  ["send", { ok: "verify", "denied · error": "failed@send" }],
  ["verify", { pass: "done", fail: "failed@verify" }],
  ["nothing", {}],
  ["done", {}],
];
const MAIN = [
  "start",
  "recall",
  "requests",
  "orders",
  "charges",
  "triage",
  "check",
  "review",
  "draft",
  "approve",
  "send",
  "verify",
  "done",
];
const SMALL_IDS = new Set(["start", "done", "nothing"]);
const STUB_IDS = WORKFLOW.flatMap(([, routes]) => Object.values(routes)).filter((id) => id.startsWith("failed@"));
const NODES: LayoutNode[] = [
  ...WORKFLOW.map(([id]) => ({ id, ...(SMALL_IDS.has(id) ? SMALL : STEP) })),
  ...STUB_IDS.map((id) => ({ id, ...STUB })),
];
const ROUTES = WORKFLOW.flatMap(([source, routes]) =>
  Object.entries(routes).map(([route, target]) => ({
    id: `${source}:${route}`,
    source,
    target,
    label: route === "next" ? undefined : route,
    failure: target.startsWith("failed@"),
  })),
);
const PRIMARY = mainPath(ROUTES.filter((e) => !e.failure));
const EDGES: LayoutEdge[] = ROUTES.map(({ id, source, target, label }) => ({
  id,
  source,
  target,
  label,
  primary: PRIMARY.has(id),
}));

// The reconciliation run (run_1042): two agents in parallel, a human review branch, and a revision edge back.
const RECON_NODES: LayoutNode[] = [
  "start",
  "read",
  "retail",
  "finance",
  "decide",
  "human",
  "verify",
  "memory",
  "report",
  "done",
].map((id) => ({ id, ...(id === "start" || id === "done" ? SMALL : STEP) }));
const RECON_LINKS = (
  [
    ["start", "read"],
    ["read", "retail"],
    ["read", "finance"],
    ["retail", "decide"],
    ["finance", "decide"],
    ["decide", "verify", "approved"],
    ["decide", "human", "human review"],
    ["human", "verify", "accepted"],
    ["human", "finance", "revision required"],
    ["verify", "memory", "verified"],
    ["memory", "report"],
    ["report", "done"],
  ] as [string, string, string?][]
).map(([source, target, label]) => ({ id: `${source}:${target}`, source, target, label }));
// As the run canvas marks it: the longest chain of onward routes, never the revision loop.
const RECON_PRIMARY = mainPath(RECON_LINKS.filter((e) => e.id !== "human:finance"));
const RECON_EDGES: LayoutEdge[] = RECON_LINKS.map((e) => ({ ...e, primary: RECON_PRIMARY.has(e.id) }));

const size = (id: string) => NODES.find((n) => n.id === id)!;
const TOL = 2;
const ROUTE_MARGIN = 60;
/** The canvas's own shape (about 1100 by 420), a square, and none (no wrapping). */
const ASPECTS = [2.6, 1, undefined];
/** Every snapped aspect the canvas asks for from tall-ish to very wide (quarter powers of two), and none. */
const SWEEP_ASPECTS = [0.84, 1, 1.19, 1.41, 1.68, 2, 2.38, 2.83, 3.36, 4, undefined];

type Seg = { a: Point; b: Point };
type Rect = { x: number; y: number; width: number; height: number };
const segments = (points: Point[]): Seg[] => points.slice(1).map((b, i) => ({ a: points[i], b }));
const span = (p: number, q: number) => [Math.min(p, q), Math.max(p, q)];
const overlap = ([a0, a1]: number[], [b0, b1]: number[]) => Math.min(a1, b1) - Math.max(a0, b0);
const horizontal = (s: Seg) => Math.abs(s.a.y - s.b.y) < 0.5;
const vertical = (s: Seg) => Math.abs(s.a.x - s.b.x) < 0.5;
/** The segment passes through the box's inside, not just along its edge. (A segment has no width across itself.) */
const crosses = (s: Seg, b: Rect) => {
  const [[x0, x1], [y0, y1]] = [span(s.a.x, s.b.x), span(s.a.y, s.b.y)];
  return x1 > b.x + 1 && x0 < b.x + b.width - 1 && y1 > b.y + 1 && y0 < b.y + b.height - 1;
};
/** The two segments lie on one line and share more than a pixel of it. */
const collinear = (s: Seg, u: Seg) => {
  if (horizontal(s) !== horizontal(u)) return false;
  return horizontal(s)
    ? Math.abs(s.a.y - u.a.y) < 0.5 && overlap(span(s.a.x, s.b.x), span(u.a.x, u.b.x)) > 1
    : Math.abs(s.a.x - u.a.x) < 0.5 && overlap(span(s.a.y, s.b.y), span(u.a.y, u.b.y)) > 1;
};

describe("mainPath", () => {
  it("follows the longest chain of onward routes, skipping a branch that ends early", () => {
    const path = [...PRIMARY].map((id) => ROUTES.find((e) => e.id === id)!.target);
    expect(path).toEqual(MAIN.slice(1));
  });

  it("breaks ties by the workflow's own order and survives cycles", () => {
    const edges = [
      { id: "a-b", source: "a", target: "b" },
      { id: "a-c", source: "a", target: "c" },
      { id: "b-d", source: "b", target: "d" },
      { id: "c-d", source: "c", target: "d" },
      { id: "d-b", source: "d", target: "b" },
    ];
    expect([...mainPath(edges)]).toEqual(["a-b", "b-d"]);
    expect(mainPath([])).toEqual(new Set());
  });
});

describe("layoutGraph", () => {
  it("without an aspect ratio, keeps the happy path on one straight row, reading left to right", async () => {
    const { positions } = await layoutGraph(NODES, EDGES);
    const centres = MAIN.map((id) => positions[id].y + size(id).height / 2);
    for (const c of centres) expect(Math.abs(c - centres[0])).toBeLessThanOrEqual(TOL);
    for (let i = 1; i < MAIN.length; i++) expect(positions[MAIN[i]].x).toBeGreaterThan(positions[MAIN[i - 1]].x);
  });

  it("with an aspect ratio, wraps the happy path into rows that read in order", async () => {
    for (const aspectRatio of [2.6, 1]) {
      const { positions } = await layoutGraph(NODES, EDGES, { aspectRatio });
      const centre = (id: string) => positions[id].y + size(id).height / 2;
      let rows = 1;
      for (let i = 1; i < MAIN.length; i++) {
        const [a, b] = [MAIN[i - 1], MAIN[i]];
        const at = `${a} -> ${b} (aspect ${aspectRatio})`;
        if (Math.abs(centre(b) - centre(a)) <= TOL) {
          // Same row: reads left to right.
          expect(positions[b].x, at).toBeGreaterThan(positions[a].x);
        } else {
          // A wrap: the next row is further down and starts back at the left.
          expect(centre(b), at).toBeGreaterThan(centre(a) + STEP.height);
          expect(positions[b].x, at).toBeLessThan(positions[a].x);
          rows++;
        }
      }
      expect(rows, `rows at aspect ${aspectRatio}`).toBeGreaterThan(1);
    }
  });

  it("matches the requested aspect ratio", async () => {
    for (const aspectRatio of [2.6, 1.6, 1]) {
      const { positions } = await layoutGraph(NODES, EDGES, { aspectRatio });
      const right = Math.max(...NODES.map((n) => positions[n.id].x + n.width));
      const left = Math.min(...NODES.map((n) => positions[n.id].x));
      const top = Math.min(...NODES.map((n) => positions[n.id].y));
      const bottom = Math.max(...NODES.map((n) => positions[n.id].y + n.height));
      const ratio = (right - left) / (bottom - top);
      expect(ratio, `aspect ${aspectRatio}`).toBeGreaterThan(aspectRatio / 1.6);
      expect(ratio, `aspect ${aspectRatio}`).toBeLessThan(aspectRatio * 1.6);
    }
  });

  it("never overlaps two node boxes", async () => {
    for (const aspectRatio of ASPECTS) {
      const { positions } = await layoutGraph(NODES, EDGES, { aspectRatio });
      for (let i = 0; i < NODES.length; i++) {
        for (let j = i + 1; j < NODES.length; j++) {
          const a = { ...positions[NODES[i].id], ...NODES[i] };
          const b = { ...positions[NODES[j].id], ...NODES[j] };
          const apart = a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y;
          expect(apart, `${a.id} overlaps ${b.id} (aspect ${aspectRatio})`).toBe(true);
        }
      }
    }
  });

  it("routes every edge from the source's right side to the target's left side", async () => {
    for (const aspectRatio of ASPECTS) {
      const { positions, routes } = await layoutGraph(NODES, EDGES, { aspectRatio });
      for (const e of EDGES) {
        const at = `${e.id} (aspect ${aspectRatio})`;
        const route = routes[e.id];
        expect(route, at).toBeDefined();
        expect(route.points.length, at).toBeGreaterThanOrEqual(2);
        const first = route.points[0];
        const last = route.points[route.points.length - 1];
        const s = { ...positions[e.source], ...size(e.source) };
        const t = { ...positions[e.target], ...size(e.target) };
        expect(Math.abs(first.x - (s.x + s.width)), `${at} start x`).toBeLessThanOrEqual(TOL);
        expect(first.y, `${at} start y`).toBeGreaterThanOrEqual(s.y);
        expect(first.y, `${at} start y`).toBeLessThanOrEqual(s.y + s.height);
        expect(Math.abs(last.x - t.x), `${at} end x`).toBeLessThanOrEqual(TOL);
        expect(last.y, `${at} end y`).toBeGreaterThanOrEqual(t.y);
        expect(last.y, `${at} end y`).toBeLessThanOrEqual(t.y + t.height);
      }
    }
  });

  it("places each label on its edge's route", async () => {
    for (const aspectRatio of ASPECTS) {
      const { routes } = await layoutGraph(NODES, EDGES, { aspectRatio });
      for (const e of EDGES.filter((edge) => edge.label)) {
        const at = `${e.id} (aspect ${aspectRatio})`;
        const { points, label } = routes[e.id];
        expect(label, at).toBeDefined();
        const xs = points.map((p) => p.x);
        const ys = points.map((p) => p.y);
        expect(label!.x, at).toBeGreaterThanOrEqual(Math.min(...xs) - 1);
        expect(label!.x, at).toBeLessThanOrEqual(Math.max(...xs) + 1);
        expect(label!.y, at).toBeGreaterThanOrEqual(Math.min(...ys) - 20);
        expect(label!.y, at).toBeLessThanOrEqual(Math.max(...ys) + 20);
      }
    }
  });

  it("keeps each failure stub next to the step it belongs to", async () => {
    const roomForLabel = 70 + 2 * labelSize("rejected · timeout").width;
    for (const aspectRatio of ASPECTS) {
      const { positions } = await layoutGraph(NODES, EDGES, { aspectRatio });
      for (const id of STUB_IDS) {
        const source = id.split("@")[1];
        const s = { ...positions[source], ...size(source) };
        const stub = positions[id];
        const at = `${id} (aspect ${aspectRatio})`;
        expect(stub.x, at).toBeGreaterThan(s.x + s.width);
        expect(stub.x - (s.x + s.width), at).toBeLessThan(roomForLabel);
        expect(Math.abs(stub.y - s.y), at).toBeLessThan(2 * STEP.height + 40);
      }
    }
  });

  it("keeps every route orthogonal and attached to its nodes when wrapping, whatever the aspect ratio", async () => {
    // ELK's wrapping can leave an edge that skips a layer across a cut with a broken route; those are redrawn.
    for (const aspectRatio of [0.84, 1, 1.41, 2, 2.38, 2.83, 3.36]) {
      const { positions, routes } = await layoutGraph(RECON_NODES, RECON_EDGES, { aspectRatio });
      const box = (id: string) => ({ ...positions[id], ...RECON_NODES.find((n) => n.id === id)! });
      const boxes = RECON_NODES.map((n) => box(n.id));
      // Fitting the view frames the nodes, so a route that strays far outside them is cut off.
      const bounds = {
        left: Math.min(...boxes.map((b) => b.x)) - ROUTE_MARGIN,
        right: Math.max(...boxes.map((b) => b.x + b.width)) + ROUTE_MARGIN,
      };
      for (const e of RECON_EDGES) {
        const at = `${e.id} (aspect ${aspectRatio})`;
        const points = routes[e.id].points;
        for (const p of points) {
          expect(p.x >= bounds.left && p.x <= bounds.right, `${at} stays in frame (x ${p.x})`).toBe(true);
        }
        const [s, t] = [box(e.source), box(e.target)];
        const [first, last] = [points[0], points[points.length - 1]];
        expect(Math.abs(first.x - (s.x + s.width)), at).toBeLessThanOrEqual(TOL);
        expect(first.y >= s.y && first.y <= s.y + s.height, at).toBe(true);
        expect(Math.abs(last.x - t.x), at).toBeLessThanOrEqual(TOL);
        expect(last.y >= t.y && last.y <= t.y + t.height, at).toBe(true);
        for (let i = 1; i < points.length; i++) {
          const straight =
            Math.abs(points[i].x - points[i - 1].x) < 0.5 || Math.abs(points[i].y - points[i - 1].y) < 0.5;
          expect(straight, `${at} segment ${i}`).toBe(true);
        }
      }
    }
  });

  it("never runs a route through another step, or along another route, whatever the aspect ratio", async () => {
    const fixtures = [
      ["refund", NODES, EDGES],
      ["recon", RECON_NODES, RECON_EDGES],
    ] as const;
    for (const [name, nodes, edges] of fixtures) {
      for (const aspectRatio of SWEEP_ASPECTS) {
        const { positions, routes } = await layoutGraph(nodes, edges, { aspectRatio });
        const box = (id: string) => ({ ...positions[id], ...nodes.find((n) => n.id === id)! });
        for (const e of edges) {
          const at = `${name} ${e.id} (aspect ${aspectRatio})`;
          for (const s of segments(routes[e.id].points)) {
            for (const n of nodes) {
              if (n.id === e.source || n.id === e.target) continue;
              expect(crosses(s, box(n.id)), `${at} crosses ${n.id}`).toBe(false);
            }
          }
          // Routes leaving one port (or entering one) share their first (or last) stretch, like a bus; others never.
          for (const f of edges) {
            if (f.id <= e.id || f.source === e.source || f.target === e.target) continue;
            const shared = segments(routes[e.id].points).some((s) =>
              segments(routes[f.id].points).some((u) => collinear(s, u)),
            );
            expect(shared, `${at} runs along ${f.id}`).toBe(false);
          }
        }
      }
    }
  });

  it("handles parallel branches and a revision loop back to an earlier step", async () => {
    const [nodes, edges] = [RECON_NODES, RECON_EDGES];
    const { positions, routes } = await layoutGraph(nodes, edges);
    const box = (id: string) => ({ ...positions[id], ...nodes.find((n) => n.id === id)! });

    // Workflow order holds: the loop back to finance is the edge that runs backwards, nothing else.
    const order = ["start", "read", "finance", "decide", "human", "verify", "memory", "report", "done"];
    for (let i = 1; i < order.length; i++)
      expect(positions[order[i]].x, order[i]).toBeGreaterThan(positions[order[i - 1]].x);
    expect(positions.retail.x).toBe(positions.finance.x);

    for (const e of edges) {
      const points = routes[e.id].points;
      const s = box(e.source);
      const t = box(e.target);
      expect(Math.abs(points[0].x - (s.x + s.width)), `${e.id} start`).toBeLessThanOrEqual(TOL);
      expect(Math.abs(points[points.length - 1].x - t.x), `${e.id} end`).toBeLessThanOrEqual(TOL);
    }
    const centre = (id: string) => box(id).y + box(id).height / 2;
    for (const id of ["read", "retail", "decide", "human", "verify", "memory", "report", "done"]) {
      expect(Math.abs(centre(id) - centre("start")), id).toBeLessThanOrEqual(TOL);
    }
  });

  it("is deterministic and handles an empty graph", async () => {
    const [a, b] = await Promise.all([
      layoutGraph(NODES, EDGES, { aspectRatio: 2.6 }),
      layoutGraph(NODES, EDGES, { aspectRatio: 2.6 }),
    ]);
    expect(a).toEqual(b);
    expect(await layoutGraph([], [])).toEqual({ positions: {}, routes: {} });
  });

  it("lays out top to bottom when asked", async () => {
    const { positions } = await layoutGraph(NODES, EDGES, { direction: "DOWN" });
    for (let i = 1; i < MAIN.length; i++) expect(positions[MAIN[i]].y).toBeGreaterThan(positions[MAIN[i - 1]].y);
  });
});

describe("routeAcrossRows", () => {
  const box = (x: number, y: number): Rect => ({ x, y, width: 210, height: 96 });
  // Three wrapped rows whose columns do not line up. The middle one is uneven: a branch (C) sits high, the targets
  // (T, U) low, and D bridges them, so a target's own band does not reach the top of its row.
  const B: Record<string, Rect> = {
    A: box(0, 0),
    R: box(280, 0),
    S: box(560, 0),
    C: box(280, 150),
    D: box(600, 200),
    T: box(0, 260),
    U: box(870, 260),
    E: box(140, 420),
    F: box(420, 420),
    G: box(700, 420),
  };
  const BOXES = Object.values(B);

  function expectClean(from: string, to: string, points: Point[]) {
    const [s, t] = [B[from], B[to]];
    expect(points[0]).toEqual({ x: s.x + s.width, y: s.y + s.height / 2 });
    expect(points[points.length - 1]).toEqual({ x: t.x, y: t.y + t.height / 2 });
    for (const seg of segments(points)) {
      expect(horizontal(seg) || vertical(seg), `${from}>${to} turns only at right angles`).toBe(true);
      for (const [id, b] of Object.entries(B)) {
        if (id !== from && id !== to) expect(crosses(seg, b), `${from}>${to} crosses ${id}`).toBe(false);
      }
    }
  }

  it("runs along the gap above the target's whole row, not just above the target", () => {
    const { points, label } = routeAcrossRows(B.S, B.T, BOXES, []);
    expectClean("S", "T", points);
    expect(segments(points).some((s) => horizontal(s) && s.a.y > 96 && s.a.y < 150)).toBe(true);
    expect(segments(points).some((s) => onSegment(label!, s))).toBe(true);
  });

  it("gives each route rerouted through one gap its own lane", () => {
    const first = routeAcrossRows(B.S, B.T, BOXES, []).points;
    const second = routeAcrossRows(B.R, B.U, BOXES, segments(first)).points;
    expectClean("R", "U", second);
    const shared = segments(second).some((s) => segments(first).some((u) => collinear(s, u)));
    expect(shared).toBe(false);
  });

  it("drops straight past a band of branches when nothing is in the way, rather than going round", () => {
    // run_1042's shape: a branch (K) hangs in a band of its own under the first row, left of the source.
    const P = box(0, 0);
    const Q = box(300, 0);
    const K = box(0, 136);
    const V = box(150, 360);
    const { points } = routeAcrossRows(Q, V, [P, Q, K, V], []);
    expect(Math.min(...points.map((p) => p.x))).toBeGreaterThanOrEqual(0);
    for (const seg of segments(points)) {
      for (const b of [P, K]) expect(crosses(seg, b)).toBe(false);
    }
  });

  it("goes around rows it skips, forwards and back", () => {
    expectClean("S", "E", routeAcrossRows(B.S, B.E, BOXES, []).points);
    expectClean("G", "R", routeAcrossRows(B.G, B.R, BOXES, []).points);
    expectClean("D", "C", routeAcrossRows(B.D, B.C, BOXES, []).points);
  });
});

const onSegment = (p: Point, s: Seg) =>
  overlap(span(s.a.x, s.b.x), [p.x, p.x]) >= -0.5 &&
  overlap(span(s.a.y, s.b.y), [p.y, p.y]) >= -0.5 &&
  (horizontal(s) ? Math.abs(p.y - s.a.y) < 0.5 : Math.abs(p.x - s.a.x) < 0.5);
