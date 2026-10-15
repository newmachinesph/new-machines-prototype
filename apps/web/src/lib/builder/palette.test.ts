import { describe, expect, it } from "vitest";
import { stepsToGraph } from "./graph";
import { readingOrder } from "./guided";
import { ADD_KINDS, paletteEntries } from "./palette";
import { OVERDUE, PALETTE } from "./test-fixtures";

describe("the palette", () => {
  const entries = paletteEntries(PALETTE);

  it("offers every kind of step, then what the registry has", () => {
    expect(entries.filter((e) => e.kind === "step")).toHaveLength(ADD_KINDS.length);
    expect(entries.find((e) => e.key === "agent:org-a1--invoice-helper")).toMatchObject({ kind: "agent", team: true });
    expect(entries.find((e) => e.key === "tool:gmail.create_draft")).toMatchObject({ writes: true, blocked: false });
    expect(entries.find((e) => e.key === "tool:stripe.refund_charge")).toMatchObject({ blocked: true });
    expect(entries.find((e) => e.key === "space:customer-accounts")?.step).toEqual({
      type: "memory",
      config: { op: "recall", space: "customer-accounts" },
    });
  });

  it("marks every tool that is not a read as changing data, unless the pack may not use it at all", () => {
    const exporting = { ...PALETTE.tools[1], ref: "notion.export", actionClass: "export" };
    const withExport = paletteEntries({ ...PALETTE, tools: [...PALETTE.tools, exporting] });
    expect(withExport.find((e) => e.key === "tool:notion.export")).toMatchObject({ writes: true, blocked: false });
    expect(withExport.find((e) => e.key === "tool:stripe.list_invoices")).toMatchObject({ writes: false });
    expect(withExport.find((e) => e.key === "tool:stripe.refund_charge")).toMatchObject({
      writes: false,
      blocked: true,
    });
  });

  it("adds an agent with its output schema already set", () => {
    expect(entries.find((e) => e.key === "agent:writer-agent")?.step).toEqual({
      type: "agent",
      config: { agent: "writer-agent", inputs: {}, output_schema: "shared/drafts" },
    });
  });

  it("starts an app step with no arguments, so the required ones show as missing", () => {
    expect(entries.find((e) => e.key === "tool:gmail.create_draft")?.step).toEqual({
      type: "connector",
      config: { tool: "gmail.create_draft", args: {} },
    });
  });
});

describe("the guided step list's order", () => {
  it("reads from the start along the happy path, with ends last", () => {
    const { nodes, edges } = stepsToGraph(OVERDUE.steps);
    expect(readingOrder(nodes, edges).map((n) => n.id)).toEqual([
      "start",
      "recall",
      "invoices",
      "plan",
      "check",
      "review",
      "draft",
      "approve",
      "send",
      "verify",
      "nothing",
      "done",
      "failed",
    ]);
  });

  it("lists steps nothing reaches at the end", () => {
    const { nodes, edges } = stepsToGraph(OVERDUE.steps);
    // Without the way into verify, done is out of reach too: both come after every reached step.
    const order = readingOrder(
      nodes,
      edges.filter((e) => e.target !== "verify"),
    );
    expect(order.slice(-2).map((n) => n.id)).toEqual(["verify", "done"]);
  });

  it("lists every step when there is no start", () => {
    const { nodes, edges } = stepsToGraph(OVERDUE.steps.filter((s) => s.id !== "start"));
    expect(readingOrder(nodes, edges)).toHaveLength(nodes.length);
  });
});
