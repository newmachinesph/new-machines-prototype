import { describe, expect, it } from "vitest";
import type { DecisionRule, PaletteTool } from "@/lib/api/gen/types.gen";
import { edgeIdOf, edgeOf, stepsToGraph, type StepNode } from "./graph";
import { graphIssues, isWrite, MAX_STEPS, refusalOf, toolIndex } from "./rules";
import { OVERDUE, PALETTE } from "./test-fixtures";

const tools = toolIndex(PALETTE.tools);
const graph = () => stepsToGraph(OVERDUE.steps);
const issuesOf = (nodes: StepNode[], edges = graph().edges) => graphIssues(nodes, edges, tools, PALETTE);
const withConfig = (nodes: StepNode[], id: string, config: Record<string, unknown>) =>
  nodes.map((n) => (n.id === id ? { ...n, data: { ...n.data, config } } : n));

/** A made-up read tool whose schema names required arguments, as the real connector definitions do. */
const CHARGES: PaletteTool = {
  ref: "stripe.list_charges",
  app: "Stripe",
  name: "List charges",
  description: "Stripe list_charges",
  actionClass: "read",
  capability: "charges.read",
  inputSchema: {
    type: "object",
    additionalProperties: false,
    required: ["created"],
    properties: {
      created: {
        type: "object",
        additionalProperties: false,
        required: ["gte"],
        properties: { gte: { type: "integer" }, lte: { type: "integer" } },
      },
      limit: { type: "integer" },
    },
  },
};
/** A made-up read tool whose schema is open: extra keys are allowed, and it names no fields of its own. */
const OPEN: PaletteTool = {
  ref: "notion.search",
  app: "Notion",
  name: "Search",
  description: "Notion search",
  actionClass: "read",
  capability: "pages.read",
  inputSchema: { type: "object" },
};
const withCharges = toolIndex([...PALETTE.tools, CHARGES, OPEN]);

describe("connection rules", () => {
  const { nodes } = graph();

  it("refuses a step leading to itself or back to the start", () => {
    expect(refusalOf({ source: "plan", sourceHandle: "next", target: "plan" }, nodes, tools)).toBe("self");
    expect(refusalOf({ source: "plan", sourceHandle: "next", target: "start" }, nodes, tools)).toBe("intoStart");
  });

  it("refuses a connection that does not leave from one of the step's outcomes", () => {
    expect(refusalOf({ source: "approve", sourceHandle: "next", target: "verify" }, nodes, tools)).toBe(
      "unknownOutcome",
    );
    expect(refusalOf({ source: "approve", sourceHandle: null, target: "verify" }, nodes, tools)).toBe("unknownOutcome");
  });

  it("lets a step that changes data be entered only from an approval's granted outcome", () => {
    expect(refusalOf({ source: "draft", sourceHandle: "next", target: "send" }, nodes, tools)).toBe(
      "writeNeedsApproval",
    );
    expect(refusalOf({ source: "approve", sourceHandle: "denied", target: "send" }, nodes, tools)).toBe(
      "writeNeedsApproval",
    );
    expect(refusalOf({ source: "approve", sourceHandle: "granted", target: "send" }, nodes, tools)).toBeNull();
    // Reading needs no approval.
    expect(refusalOf({ source: "recall", sourceHandle: "next", target: "invoices" }, nodes, tools)).toBeNull();
  });
});

describe("local issues", () => {
  it("finds none in the seed pack", () => {
    expect(issuesOf(graph().nodes)).toEqual([]);
  });

  it("reports an outcome with nowhere to go and the steps it cut off", () => {
    const edges = graph().edges.filter((e) => e.id !== edgeIdOf("approve", "granted"));
    expect(issuesOf(graph().nodes, edges)).toEqual(
      expect.arrayContaining([
        { code: "unrouted", step: "approve", outcome: "granted" },
        { code: "unreachable", step: "send" },
        { code: "unreachable", step: "verify" },
        { code: "unreachable", step: "done" },
      ]),
    );
  });

  it("reports a decision's own routes when they have nowhere to go", () => {
    const edges = graph().edges.filter((e) => e.source !== "check");
    expect(issuesOf(graph().nodes, edges)).toEqual(
      expect.arrayContaining([
        { code: "unrouted", step: "check", outcome: "nothing" },
        { code: "unrouted", step: "check", outcome: "human_review" },
      ]),
    );
  });

  it("follows a route back to an earlier step without looping or crying unreachable", () => {
    const edges = graph().edges.map((e) =>
      e.id === edgeIdOf("review", "rejected") ? edgeOf("review", "rejected", "plan") : e,
    );
    expect(issuesOf(graph().nodes, edges)).toEqual([]);
  });

  it("reports a write whose way in is not an approval", () => {
    const edges = [...graph().edges.filter((e) => e.target !== "send"), edgeOf("draft", "next", "send")];
    expect(issuesOf(graph().nodes, edges)).toContainEqual({ code: "writeWithoutApproval", step: "send" });
  });

  it("reports tools a pack may not use and things the registry does not have", () => {
    let nodes = withConfig(graph().nodes, "invoices", { tool: "stripe.refund_charge", args: {} });
    nodes = withConfig(nodes, "plan", { agent: "gone-agent" });
    nodes = withConfig(nodes, "recall", { op: "recall", space: "" });
    nodes = withConfig(nodes, "review", { title: " ", show: "" });
    expect(issuesOf(nodes)).toEqual(
      expect.arrayContaining([
        { code: "blockedTool", step: "invoices" },
        { code: "missingAgent", step: "plan" },
        { code: "missingSpace", step: "recall" },
        { code: "missingTitle", step: "review" },
        { code: "missingShow", step: "review" },
      ]),
    );
  });

  it("reports a connector's required arguments that are not set", () => {
    let nodes = withConfig(graph().nodes, "send", { tool: "gmail.create_draft", args: { subject: "=item.subject" } });
    nodes = withConfig(nodes, "invoices", { tool: "stripe.list_charges", args: { limit: 5 } });
    const issues = graphIssues(nodes, graph().edges, withCharges, PALETTE);
    expect(issues).toEqual(
      expect.arrayContaining([
        { code: "missingArg", step: "send", arg: "recipient_email" },
        { code: "missingArg", step: "send", arg: "body" },
        { code: "missingArg", step: "invoices", arg: "created" },
      ]),
    );
    expect(issues).not.toContainEqual({ code: "missingArg", step: "send", arg: "subject" });
    expect(issues).not.toContainEqual(expect.objectContaining({ code: "missingArg", arg: "limit" }));
  });

  it("looks inside a required object argument given as a literal", () => {
    const nodes = withConfig(graph().nodes, "invoices", { tool: "stripe.list_charges", args: { created: { lte: 5 } } });
    expect(graphIssues(nodes, graph().edges, withCharges, PALETTE)).toContainEqual({
      code: "missingArg",
      step: "invoices",
      arg: "created.gte",
    });
    // An expression stands for the whole object, so nothing inside it can be missing.
    const expr = withConfig(graph().nodes, "invoices", {
      tool: "stripe.list_charges",
      args: { created: "=input.range" },
    });
    expect(graphIssues(expr, graph().edges, withCharges, PALETTE).filter((i) => i.code === "missingArg")).toEqual([]);
  });

  it("reports a pack with no start, or more than one, or with no way to complete", () => {
    const { nodes, edges } = graph();
    expect(
      issuesOf(
        nodes.filter((n) => n.id !== "start"),
        edges,
      ),
    ).toContainEqual({ code: "noStart" });
    const twoStarts = [...nodes, { ...nodes[0], id: "start_2" }];
    expect(issuesOf(twoStarts, edges)).toContainEqual({ code: "manyStarts" });
    const failing = withConfig(withConfig(nodes, "nothing", { status: "FAILED" }), "done", { status: "FAILED" });
    expect(issuesOf(failing, edges)).toContainEqual({ code: "neverCompletes" });
  });

  it("counts an end with no status as completing, as the API does", () => {
    const { nodes, edges } = graph();
    const bare = withConfig(withConfig(nodes, "nothing", { status: "FAILED" }), "done", {});
    expect(issuesOf(bare, edges)).not.toContainEqual({ code: "neverCompletes" });
  });

  it("reports arguments a closed schema does not declare, inside closed objects too, and lets an open one be", () => {
    let nodes = withConfig(graph().nodes, "send", {
      tool: "gmail.create_draft",
      args: { recipient_email: "=item.to", subject: "=item.subject", body: "=item.body", extra: 1 },
    });
    nodes = withConfig(nodes, "invoices", {
      tool: "stripe.list_charges",
      args: { created: { gte: 1, until: 2 }, limit: 5 },
    });
    nodes = withConfig(nodes, "recall", { tool: "notion.search", args: { query: "x", anything: 1 } });
    const issues = graphIssues(nodes, graph().edges, withCharges, PALETTE);
    expect(issues).toContainEqual({ code: "unknownArg", step: "send", arg: "extra" });
    expect(issues).toContainEqual({ code: "unknownArg", step: "invoices", arg: "created.until" });
    expect(issues.filter((i) => i.code === "unknownArg")).toHaveLength(2);
  });

  it("reports every argument of a closed schema that names none", () => {
    const bare: PaletteTool = {
      ...OPEN,
      ref: "notion.me",
      inputSchema: { type: "object", additionalProperties: false },
    };
    const nodes = withConfig(graph().nodes, "invoices", { tool: "notion.me", args: { anything: 1 } });
    expect(graphIssues(nodes, graph().edges, toolIndex([bare]), PALETTE)).toContainEqual({
      code: "unknownArg",
      step: "invoices",
      arg: "anything",
    });
  });

  it("reports a tool's arguments given as one expression, which the API refuses", () => {
    const nodes = withConfig(graph().nodes, "invoices", { tool: "stripe.list_invoices", args: "=input.args" });
    const issues = issuesOf(nodes);
    expect(issues).toContainEqual({ code: "argsExpression", step: "invoices" });
    expect(issues.filter((i) => i.step === "invoices")).toHaveLength(1);
  });

  it.each([["paid"], [["paid"]]])("reports a tool's arguments that are not named values (%j)", (args) => {
    const nodes = withConfig(graph().nodes, "invoices", { tool: "stripe.list_invoices", args });
    expect(issuesOf(nodes)).toContainEqual({ code: "argsExpression", step: "invoices" });
  });

  it("reports a decision rule whose condition or explanation is empty", () => {
    const rules = graph().nodes.find((n) => n.id === "check")!.data.rules!;
    const withRule = (patch: Partial<DecisionRule>) =>
      graph().nodes.map((n) =>
        n.id === "check"
          ? { ...n, data: { ...n.data, rules: { ...rules, rules: [{ ...rules.rules![0], ...patch }] } } }
          : n,
      );
    expect(issuesOf(withRule({ when: "" }))).toContainEqual({ code: "missingRules", step: "check" });
    expect(issuesOf(withRule({ explanation: " " }))).toContainEqual({ code: "missingRules", step: "check" });
    expect(issuesOf(withRule({}))).not.toContainEqual({ code: "missingRules", step: "check" });
  });

  it("reports a pack of fewer than two steps, which the API does not take", () => {
    const [start] = graph().nodes;
    expect(issuesOf([start], [])).toEqual(
      expect.arrayContaining([{ code: "tooFewSteps" }, { code: "unrouted", step: "start", outcome: "next" }]),
    );
    expect(issuesOf(graph().nodes)).not.toContainEqual({ code: "tooFewSteps" });
  });

  it("reports a decision with no rules yet apart from unfinished ones, and a bad step name", () => {
    const nodes = graph().nodes.map((n) =>
      n.id === "check" ? { ...n, id: "Check", data: { ...n.data, rules: undefined } } : n,
    );
    const issues = issuesOf(nodes);
    expect(issues).toEqual(
      expect.arrayContaining([
        { code: "badId", step: "Check" },
        { code: "noRules", step: "Check" },
      ]),
    );
    expect(issues).not.toContainEqual({ code: "missingRules", step: "Check" });
    // Rules that exist but are not finished are a different problem: the request check refuses them.
    const unfinished = { question: "", default: { route: "", explanation: "" } };
    const blank = graph().nodes.map((n) => (n.id === "check" ? { ...n, data: { ...n.data, rules: unfinished } } : n));
    expect(issuesOf(blank)).toContainEqual({ code: "missingRules", step: "check" });
    expect(issuesOf(blank)).not.toContainEqual({ code: "noRules", step: "check" });
  });

  it("reports a pack of more than sixty steps, which the API does not take", () => {
    const { nodes, edges } = graph();
    const filler = (n: number): StepNode[] =>
      Array.from({ length: n }, (_, i) => ({ ...nodes[1], id: `recall_${i + 2}` }));
    const atCap = [...nodes, ...filler(MAX_STEPS - nodes.length)];
    expect(atCap).toHaveLength(60);
    expect(issuesOf(atCap, edges)).not.toContainEqual({ code: "tooManySteps" });
    expect(issuesOf([...atCap, ...filler(1)], edges)).toContainEqual({ code: "tooManySteps" });
  });
});

describe("what counts as a write", () => {
  /** A tool of a class the connector schema does not have yet: the API treats anything but a read as a write. */
  const EXPORT: PaletteTool = { ...OPEN, ref: "notion.export", actionClass: "export" };
  const withExport = toolIndex([...PALETTE.tools, EXPORT]);

  it("is any tool that is not a read, as the API's approval check has it", () => {
    const { nodes, edges } = graph();
    const exporting = withConfig(nodes, "invoices", { tool: "notion.export", args: {} });
    expect(isWrite(exporting.find((n) => n.id === "invoices")?.data, withExport)).toBe(true);
    expect(refusalOf({ source: "recall", sourceHandle: "next", target: "invoices" }, exporting, withExport)).toBe(
      "writeNeedsApproval",
    );
    expect(graphIssues(exporting, edges, withExport, PALETTE)).toContainEqual({
      code: "writeWithoutApproval",
      step: "invoices",
    });
    expect(isWrite(nodes.find((n) => n.id === "invoices")?.data, withExport)).toBe(false);
  });

  it("is not a tool the registry does not have, and a blocked tool is still reported as blocked", () => {
    const { nodes, edges } = graph();
    expect(isWrite(withConfig(nodes, "invoices", { tool: "gone.tool", args: {} })[2].data, tools)).toBe(false);
    const refunding = withConfig(nodes, "invoices", { tool: "stripe.refund_charge", args: {} });
    expect(graphIssues(refunding, edges, tools, PALETTE)).toContainEqual({ code: "blockedTool", step: "invoices" });
  });
});
