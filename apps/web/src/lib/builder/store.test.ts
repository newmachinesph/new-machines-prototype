import { describe, expect, it } from "vitest";
import type { PackDraft } from "@/lib/api/gen/types.gen";
import { edgeIdOf } from "./graph";
import { createEditorStore, draftOf, startCount } from "./store";
import { OVERDUE, PALETTE } from "./test-fixtures";

const make = () => createEditorStore({ draft: OVERDUE, palette: PALETTE });
const ids = (s: ReturnType<typeof make>) => s.getState().nodes.map((n) => n.id);
const edge = (s: ReturnType<typeof make>, source: string, outcome: string) =>
  s.getState().edges.find((e) => e.id === edgeIdOf(source, outcome));

describe("the editor store", () => {
  it("gives back the pack it was opened with, and asks for a layout", () => {
    const store = make();
    expect(draftOf(store.getState())).toEqual(OVERDUE);
    expect(store.getState().layoutRequest).toEqual({ n: 1, record: false });
  });

  it("connects an outcome, replacing its old edge, and refuses what the rules refuse", () => {
    const store = make();
    expect(store.getState().connect({ source: "draft", sourceHandle: "next", target: "send" })).toBe(
      "writeNeedsApproval",
    );
    expect(store.getState().history.past).toHaveLength(0);
    expect(store.getState().connect({ source: "approve", sourceHandle: "denied", target: "review" })).toBeNull();
    expect(edge(store, "approve", "denied")?.target).toBe("review");
    expect(store.getState().edges.filter((e) => e.source === "approve")).toHaveLength(3);
    store.getState().disconnect("approve", "denied");
    expect(edge(store, "approve", "denied")).toBeUndefined();
  });

  it("duplicates one step, leaving the clipboard and the start alone", () => {
    const store = make();
    store.getState().select("draft");
    store.getState().copy();
    const clipboard = store.getState().clipboard;
    store.getState().duplicate("review");
    expect(ids(store)).toContain("review_2");
    expect(store.getState().selectedId).toBe("review_2");
    expect(store.getState().edges.some((e) => e.source === "review_2" || e.target === "review_2")).toBe(false);
    expect(store.getState().clipboard).toBe(clipboard);
    store.getState().undo();
    expect(ids(store)).not.toContain("review_2");
    store.getState().duplicate("start");
    expect(ids(store).filter((id) => id.startsWith("start"))).toEqual(["start"]);
  });

  it("undoes and redoes adding a step", () => {
    const store = make();
    const id = store.getState().addStep({ type: "approval", config: { title: "Check" } });
    expect(id).toBe("approve_2");
    expect(store.getState().selectedId).toBe("approve_2");
    store.getState().undo();
    expect(ids(store)).not.toContain("approve_2");
    store.getState().redo();
    expect(ids(store)).toContain("approve_2");
  });

  it("inserts a step after an outcome and wires it to where the outcome went", () => {
    const store = make();
    const { id, refusal, unlinked } = store.getState().insertAfter("review", "resolved", {
      type: "approval",
      config: { title: "Second look" },
    });
    expect(refusal).toBeNull();
    expect(unlinked).toBeNull();
    expect(edge(store, "review", "resolved")?.target).toBe(id);
    expect(edge(store, id ?? "", "granted")?.target).toBe("draft");
    expect(store.getState().layoutRequest.n).toBe(2);
    store.getState().undo();
    expect(edge(store, "review", "resolved")?.target).toBe("draft");
  });

  it("records a drag once, and a click that moves nothing not at all", () => {
    const store = make();
    store.getState().beginDrag();
    store.getState().endDrag();
    expect(store.getState().history.past).toHaveLength(0);
    store.getState().beginDrag();
    store.getState().onNodesChange([{ type: "position", id: "plan", position: { x: 40, y: 40 }, dragging: true }]);
    store.getState().onNodesChange([{ type: "position", id: "plan", position: { x: 80, y: 40 }, dragging: true }]);
    store.getState().endDrag();
    expect(store.getState().history.past).toHaveLength(1);
    store.getState().undo();
    expect(store.getState().nodes.find((n) => n.id === "plan")?.position).toEqual({ x: 3 * 260, y: 0 });
  });

  it("records typing in a field once per visit", () => {
    const store = make();
    store.getState().startEdit();
    store.getState().updateStep("review", { config: { title: "C" } }, false);
    store.getState().updateStep("review", { config: { title: "Ch" } }, false);
    store.getState().finishEdit();
    expect(store.getState().history.past).toHaveLength(1);
    store.getState().undo();
    expect(store.getState().nodes.find((n) => n.id === "review")?.data.config.title).toBe(
      "Check the overdue invoice reminders",
    );
  });

  it("renames a step and every expression that reads it", () => {
    const store = make();
    expect(store.getState().renameStep("plan", "Plan")).toBe("badId");
    expect(store.getState().renameStep("plan", "draft")).toBe("taken");
    expect(store.getState().renameStep("plan", "plan_reminders")).toBe("ok");
    const steps = draftOf(store.getState()).steps;
    expect(steps.find((s) => s.id === "review")?.config?.show).toBe("=nodes.plan_reminders.output.review_items");
    expect(steps.find((s) => s.id === "check")?.rules?.rules?.[0].when).toBe(
      "size(nodes.plan_reminders.output.messages) == 0",
    );
    expect(steps.find((s) => s.id === "invoices")?.routes).toMatchObject({ ok: "plan_reminders" });
  });

  it("keeps a renamed route's edge, and drops edges for routes a decision no longer has", () => {
    const store = make();
    const rules = OVERDUE.steps.find((s) => s.id === "check")?.rules;
    if (!rules) throw new Error("fixture");
    store.getState().updateStep("check", {
      rules: { ...rules, rules: [{ ...(rules.rules ?? [])[0], route: "none_due" }] },
    });
    expect(edge(store, "check", "nothing")).toBeUndefined();
    expect(edge(store, "check", "none_due")?.target).toBe("nothing");
    store.getState().updateStep("check", { rules: { ...rules, rules: [] } });
    expect(edge(store, "check", "none_due")).toBeUndefined();
    expect(edge(store, "check", "human_review")?.target).toBe("review");
  });

  it("keeps a decision's model step and its failure route when a rule is edited", () => {
    const check = OVERDUE.steps.find((s) => s.id === "check");
    const base = check?.rules;
    if (!base) throw new Error("fixture");
    const evaluator = { model: "x", on_error: { route: "unsorted" } };
    const draft = {
      ...OVERDUE,
      steps: OVERDUE.steps.map((s) =>
        s.id === "check"
          ? {
              ...s,
              rules: { ...base, question: base.question ?? "Q?", evaluator },
              routes: { ...s.routes, unsorted: "review" },
            }
          : s,
      ) as PackDraft["steps"],
    };
    const store = createEditorStore({ draft, palette: PALETTE });
    expect(edge(store, "check", "unsorted")?.target).toBe("review");
    const rules = store.getState().nodes.find((n) => n.id === "check")?.data.rules;
    if (!rules) throw new Error("rules");
    store.getState().updateStep("check", { rules: { ...rules, question: "Changed?" } });
    expect(edge(store, "check", "unsorted")?.target).toBe("review");
    const kept = draftOf(store.getState()).steps.find((s) => s.id === "check");
    expect(kept?.rules?.evaluator).toEqual(evaluator);
    expect(kept?.routes).toMatchObject({ unsorted: "review" });
  });

  it("keeps edges by name when a decision's routes are reordered", () => {
    const store = make();
    const rules = OVERDUE.steps.find((s) => s.id === "check")?.rules;
    if (!rules) throw new Error("fixture");
    // [nothing, human_review] becomes [human_review, nothing]: the same two routes, swapped.
    store.getState().updateStep("check", {
      rules: {
        ...rules,
        rules: [{ when: "size(nodes.plan.output.messages) > 0", route: "human_review", explanation: "x" }],
        default: { ...rules.default, route: "nothing" },
      },
    });
    expect(edge(store, "check", "nothing")?.target).toBe("nothing");
    expect(edge(store, "check", "human_review")?.target).toBe("review");
  });

  it("drops a removed route's edge and leaves an added route unrouted, in one rules change", () => {
    const rule = (route: string) => ({ when: "true", route, explanation: "x" });
    const store = createEditorStore({
      palette: PALETTE,
      draft: {
        ...OVERDUE,
        steps: [
          { id: "start", type: "trigger", config: {}, routes: { next: "check" } },
          {
            id: "check",
            type: "decision",
            config: {},
            routes: { a: "done", b: "failed", c: "done" },
            rules: { question: "q", rules: [rule("a"), rule("b")], default: { route: "c", explanation: "x" } },
          },
          { id: "done", type: "end", config: {}, routes: {} },
          { id: "failed", type: "end", config: { status: "FAILED" }, routes: {} },
        ],
      },
    });
    // [a, b, c] becomes [a, c, d]: b is gone, d is new, and a and c keep their edges.
    store.getState().updateStep("check", {
      rules: { question: "q", rules: [rule("a"), rule("c")], default: { route: "d", explanation: "x" } },
    });
    expect(edge(store, "check", "a")?.target).toBe("done");
    expect(edge(store, "check", "c")?.target).toBe("done");
    expect(edge(store, "check", "b")).toBeUndefined();
    expect(edge(store, "check", "d")).toBeUndefined();
    expect(store.getState().edges.filter((e) => e.source === "check")).toHaveLength(2);
  });

  it("copies steps with the edges between them and pastes them with fresh names", () => {
    const store = make();
    store.getState().onNodesChange([
      { type: "select", id: "review", selected: true },
      { type: "select", id: "draft", selected: true },
    ]);
    store.getState().copy();
    store.getState().paste();
    expect(ids(store)).toEqual(expect.arrayContaining(["review_2", "agent"]));
    expect(edge(store, "review_2", "resolved")?.target).toBe("agent");
    expect(edge(store, "review_2", "rejected")).toBeUndefined();
    store.getState().undo();
    expect(ids(store)).not.toContain("review_2");
  });

  it("points pasted steps' expressions at each other, and leaves other references alone", () => {
    const store = make();
    store.getState().onNodesChange([
      { type: "select", id: "review", selected: true },
      { type: "select", id: "draft", selected: true },
    ]);
    store.getState().copy();
    store.getState().paste();
    const inputs = store.getState().nodes.find((n) => n.id === "agent")?.data.config.inputs as Record<string, string>;
    expect(inputs.review).toBe("=nodes.review_2.output");
    expect(inputs.items).toBe("=nodes.plan.output.messages");
    // The originals are untouched.
    const original = store.getState().nodes.find((n) => n.id === "draft")?.data.config.inputs as Record<string, string>;
    expect(original.review).toBe("=nodes.review.output");
  });

  it("records nothing for a change that changes nothing", () => {
    const store = make();
    expect(store.getState().connect({ source: "approve", sourceHandle: "granted", target: "send" })).toBeNull();
    store.getState().removeStep("gone");
    store.getState().updateStep("review", { config: { ...store.getState().nodes[5].data.config } });
    expect(store.getState().history.past).toHaveLength(0);
  });

  it("undoes a change to the pack's details, and a new change clears what could be redone", () => {
    const store = make();
    store.getState().setDetails({ name: "Renamed" });
    expect(draftOf(store.getState()).name).toBe("Renamed");
    store.getState().undo();
    expect(draftOf(store.getState()).name).toBe(OVERDUE.name);
    expect(store.getState().history.future).toHaveLength(1);
    store.getState().setDetails({ outcome: "Else" });
    expect(store.getState().history.future).toHaveLength(0);
    store.getState().redo();
    expect(draftOf(store.getState()).outcome).toBe("Else");
  });

  it("adds nothing when the new step cannot be connected from the outcome", () => {
    const store = make();
    const before = store.getState();
    const result = store.getState().insertAfter("review", "resolved", {
      type: "connector",
      config: { tool: "gmail.create_draft", args: {} },
    });
    expect(result).toEqual({ id: null, refusal: "writeNeedsApproval", unlinked: null, cut: null });
    expect(ids(store)).not.toContain("app");
    expect(store.getState().edges).toBe(before.edges);
    expect(store.getState().history.past).toHaveLength(0);
    expect(store.getState().layoutRequest.n).toBe(1);
  });

  it("says when the step the outcome led to could not be wired after the new one", () => {
    const store = make();
    const result = store.getState().insertAfter("approve", "granted", { type: "verification", config: { checks: [] } });
    expect(result).toEqual({ id: "verify_2", refusal: null, unlinked: "writeNeedsApproval", cut: null });
    expect(edge(store, "approve", "granted")?.target).toBe("verify_2");
    expect(edge(store, "verify_2", "pass")).toBeUndefined();
    expect(store.getState().edges.some((e) => e.target === "send")).toBe(false);
    store.getState().undo();
    expect(edge(store, "approve", "granted")?.target).toBe("send");
  });

  it("says when a step with no outcomes yet cuts the path, but not when an end does", () => {
    const store = make();
    const decision = store.getState().insertAfter("review", "resolved", { type: "decision", config: {} });
    expect(decision).toEqual({ id: "check_2", refusal: null, unlinked: null, cut: "needsRoutes" });
    expect(edge(store, "review", "resolved")?.target).toBe("check_2");
    expect(store.getState().edges.some((e) => e.target === "draft")).toBe(false);
    store.getState().undo();
    const end = store.getState().insertAfter("review", "resolved", { type: "end", config: { status: "FAILED" } });
    expect(end).toEqual({ id: "end", refusal: null, unlinked: null, cut: null });
    expect(store.getState().edges.some((e) => e.target === "draft")).toBe(false);
  });

  it("gives a new step its own copy of the settings it was added from", () => {
    const store = make();
    const blank = { type: "agent" as const, config: { inputs: {} } };
    const id = store.getState().addStep(blank);
    const config = store.getState().nodes.find((n) => n.id === id)?.data.config;
    expect(config).toEqual(blank.config);
    expect(config?.inputs).not.toBe(blank.config.inputs);
  });

  it("gives imported steps that share a name their own names", () => {
    const store = make();
    store.getState().replaceGraph([
      { id: "start", type: "trigger", config: {}, routes: { next: "done" } },
      { id: "done", type: "end", config: {}, routes: {} },
      { id: "done", type: "end", config: { status: "FAILED" }, routes: {} },
    ]);
    expect(ids(store)).toEqual(["start", "done", "end"]);
  });

  it("removes the selected steps and their edges in one step", () => {
    const store = make();
    store.getState().select("verify");
    store.getState().removeSelected();
    expect(ids(store)).not.toContain("verify");
    expect(edge(store, "send", "ok")).toBeUndefined();
    store.getState().undo();
    expect(edge(store, "send", "ok")?.target).toBe("verify");
  });

  it("never removes the last start step", () => {
    const store = make();
    store.getState().select("start");
    store.getState().removeSelected();
    store.getState().removeStep("start");
    expect(ids(store)).toContain("start");
    expect(edge(store, "start", "next")?.target).toBe("recall");
    expect(store.getState().history.past).toHaveLength(0);
    // Chosen with another step, the start stays while the other goes.
    store.getState().onNodesChange([
      { type: "select", id: "start", selected: true },
      { type: "select", id: "verify", selected: true },
    ]);
    store.getState().removeSelected();
    expect(ids(store)).toContain("start");
    expect(ids(store)).not.toContain("verify");
  });

  it("removes a spare start step while another remains, and keeps one when every start is chosen", () => {
    const store = make();
    store.getState().replaceGraph([
      { id: "start", type: "trigger", config: {}, routes: { next: "done" } },
      { id: "start_2", type: "trigger", config: {}, routes: { next: "done" } },
      { id: "start_3", type: "trigger", config: {}, routes: {} },
      { id: "done", type: "end", config: {}, routes: {} },
    ]);
    expect(startCount(store.getState().nodes)).toBe(3);
    store.getState().removeStep("start_2");
    expect(ids(store)).toEqual(["start", "start_3", "done"]);
    expect(edge(store, "start_2", "next")).toBeUndefined();
    store.getState().onNodesChange([
      { type: "select", id: "start", selected: true },
      { type: "select", id: "start_3", selected: true },
    ]);
    store.getState().removeSelected();
    expect(ids(store)).toEqual(["start", "done"]);
    expect(edge(store, "start", "next")?.target).toBe("done");
    store.getState().removeStep("start");
    expect(ids(store)).toEqual(["start", "done"]);
  });

  it("drops a layout asked for before an undo or redo, so it never lands on the restored graph", () => {
    const store = make();
    const layout = { positions: { start: { x: 500, y: 0 } }, routes: {} };
    store.getState().insertAfter("review", "resolved", { type: "approval", config: { title: "Second look" } });
    const asked = store.getState().restores;
    store.getState().undo();
    const positions = store.getState().nodes.map((n) => n.position);
    store.getState().applyLayout(layout, asked);
    expect(store.getState().nodes.map((n) => n.position)).toEqual(positions);
    store.getState().redo();
    store.getState().applyLayout(layout, asked);
    expect(store.getState().nodes[0].position).toEqual(positions[0]);
    // One asked for after the restore lands.
    store.getState().applyLayout(layout, store.getState().restores);
    expect(store.getState().nodes[0].position.x).toBe(500);
  });

  it("applies a layout, as an undoable step when the builder asked for it", () => {
    const store = make();
    const layout = {
      positions: { start: { x: 0, y: 0 } },
      routes: {
        [edgeIdOf("start", "next")]: {
          points: [
            { x: 150, y: 42 },
            { x: 260, y: 42 },
          ],
        },
      },
    };
    store.getState().applyLayout(layout);
    expect(store.getState().history.past).toHaveLength(0);
    store.getState().requestLayout(true);
    store.getState().applyLayout(layout);
    expect(store.getState().history.past).toHaveLength(1);
    expect(store.getState().nodes[0].position).toEqual({ x: 0, y: 42 });
    expect(edge(store, "start", "next")?.type).toBe("routed");
  });

  it("replaces the graph with imported steps, undoably", () => {
    const store = make();
    expect(store.getState().replaceGraph(OVERDUE.steps.slice(0, 2))).toBe(true);
    expect(ids(store)).toEqual(["start", "recall"]);
    expect(store.getState().layoutRequest.n).toBe(2);
    store.getState().undo();
    expect(ids(store)).toHaveLength(OVERDUE.steps.length);
  });

  it("refuses imported steps with no start, leaving the canvas as it is", () => {
    const store = make();
    const before = store.getState();
    expect(store.getState().replaceGraph(OVERDUE.steps.slice(1, 3))).toBe(false);
    expect(store.getState().replaceGraph([])).toBe(false);
    expect(store.getState().nodes).toBe(before.nodes);
    expect(store.getState().edges).toBe(before.edges);
    expect(store.getState().history.past).toHaveLength(0);
    expect(store.getState().layoutRequest.n).toBe(1);
  });
});
