/**
 * What the canvas refuses and what it reports while you edit, mirroring the API's builder rules
 * (apps/api/app/studio_build.py), so problems show at once. The API checks again on Validate and Save; its answer
 * wins. Pure: no React.
 */
import type { Palette, PaletteTool } from "@/lib/api/gen/types.gen";
import type { StepEdge, StepNode, StepNodeData } from "./graph";
import { outcomesOf, STEP_ID } from "./routes";
import { isClosed, undeclaredKeys } from "./step-schemas";

export type ToolIndex = ReadonlyMap<string, PaletteTool>;
export const toolIndex = (tools: PaletteTool[]): ToolIndex => new Map(tools.map((tool) => [tool.ref, tool]));

/** Action classes a pack may not use at all: the gateway refuses them (the API's blocked classes). */
const BLOCKED_CLASSES: ReadonlySet<string> = new Set(["delete", "money"]);
export const isBlockedTool = (tool: PaletteTool | undefined) =>
  tool !== undefined && BLOCKED_CLASSES.has(tool.actionClass);

function toolOf(data: StepNodeData | undefined, tools: ToolIndex) {
  const ref = data?.type === "connector" ? data.config.tool : undefined;
  return typeof ref === "string" ? tools.get(ref) : undefined;
}

/**
 * A step that changes data in an app: a connector whose tool does anything but read, as the API's approval check
 * (`_approval_issues`) has it, so a class the connector schema gains later needs an approval here too. A tool the
 * registry does not have is reported as missing instead.
 */
export const isWrite = (data: StepNodeData | undefined, tools: ToolIndex) => {
  const tool = toolOf(data, tools);
  return tool !== undefined && !isReadTool(tool);
};
/** The one action class that needs no approval. */
export const isReadTool = (tool: PaletteTool) => tool.actionClass === "read";

export type Refusal = "self" | "intoStart" | "unknownOutcome" | "writeNeedsApproval";
export type Link = { source: string; target: string; sourceHandle?: string | null };

/** Why the canvas will not draw `link`, or null when it may. */
export function refusalOf(link: Link, nodes: StepNode[], tools: ToolIndex): Refusal | null {
  if (link.source === link.target) return "self";
  const source = nodes.find((n) => n.id === link.source);
  const target = nodes.find((n) => n.id === link.target);
  if (!source || !target) return "unknownOutcome";
  if (target.data.type === "trigger") return "intoStart";
  if (!link.sourceHandle || !outcomesOf(source.data).includes(link.sourceHandle)) return "unknownOutcome";
  const approved = source.data.type === "approval" && link.sourceHandle === "granted";
  if (isWrite(target.data, tools) && !approved) return "writeNeedsApproval";
  return null;
}

export type IssueCode =
  | "noStart"
  | "manyStarts"
  | "unrouted"
  | "unreachable"
  | "neverCompletes"
  | "writeWithoutApproval"
  | "blockedTool"
  | "missingTool"
  | "missingArg"
  | "unknownArg"
  | "argsExpression"
  | "missingAgent"
  | "missingSpace"
  | "noRules"
  | "missingRules"
  | "missingTitle"
  | "missingShow"
  | "missingCheck"
  | "badId"
  | "tooFewSteps"
  | "tooManySteps";
/** `arg` names a missing or undeclared connector argument, dotted for a field inside an object argument (`created.gte`). */
export type LocalIssue = { code: IssueCode; step?: string; outcome?: string; arg?: string };
type Refs = Pick<Palette, "agents" | "spaces">;

const filled = (v: unknown) => typeof v === "string" && v.trim().length > 0;
const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
/** A value written as CEL stands for the whole thing, so nothing inside it can be checked here. */
const isExpression = (v: unknown) => typeof v === "string" && v.startsWith("=");

/**
 * Rules that exist but are not finished: the request check refuses an empty question, condition, route or
 * explanation. No rules at all is a different problem (`noRules`): the request takes it, and the API names it.
 */
function rulesComplete(rules: NonNullable<StepNodeData["rules"]>): boolean {
  if (!filled(rules.question)) return false;
  const routes = [...(rules.rules ?? []), rules.default];
  return (
    (rules.rules ?? []).every((r) => filled(r.when)) &&
    routes.every((r) => STEP_ID.test(r.route) && filled(r.explanation))
  );
}

/**
 * The tool's required arguments that `args` does not set, as dotted paths. A required object argument given as a
 * literal is checked inside; one given as an expression is taken as whole. Mirrors the gateway's argument check
 * (`_argument_errors`), which otherwise fails the run, after a person has approved a write.
 */
function missingArgs(schema: unknown, args: unknown, path = ""): string[] {
  if (!isRecord(schema) || !isRecord(args)) return [];
  const required = Array.isArray(schema.required)
    ? schema.required.filter((k): k is string => typeof k === "string")
    : [];
  const properties = isRecord(schema.properties) ? schema.properties : {};
  return required.flatMap((key) => {
    const at = path ? `${path}.${key}` : key;
    const value = args[key];
    if (value === undefined || value === null || value === "") return [at];
    if (isExpression(value)) return [];
    return missingArgs(properties[key], value, at);
  });
}

/**
 * Arguments a closed schema (`additionalProperties: false`) does not declare, as dotted paths; a closed schema that
 * names no fields refuses every key. They come from an import, a paste or a tool whose pinned version changed its
 * schema, and the gateway refuses them ("Additional properties are not allowed"), as the API's own arg check does.
 * A literal object argument is checked inside against its own schema; an expression stands for the whole value.
 */
function unknownArgs(schema: unknown, args: unknown, path = ""): string[] {
  if (!isRecord(schema) || !isRecord(args)) return [];
  const at = (key: string) => (path ? `${path}.${key}` : key);
  const own = isClosed(schema) ? undeclaredKeys(schema, args).map(at) : [];
  const properties = isRecord(schema.properties) ? schema.properties : {};
  const inside = Object.entries(args).flatMap(([key, value]) =>
    Object.hasOwn(properties, key) && !isExpression(value) ? unknownArgs(properties[key], value, at(key)) : [],
  );
  return [...own, ...inside];
}

/** What one step is missing, from its own settings. */
function stepIssues(node: StepNode, tools: ToolIndex, refs: Refs): LocalIssue[] {
  const { type, config } = node.data;
  const step = node.id;
  const out: LocalIssue[] = [];
  if (!STEP_ID.test(step)) out.push({ code: "badId", step });
  switch (type) {
    case "connector": {
      const tool = toolOf(node.data, tools);
      if (!tool) out.push({ code: "missingTool", step });
      else if (isBlockedTool(tool)) out.push({ code: "blockedTool", step });
      // The API takes a tool's arguments as named values only: never one expression, string or list.
      else if (config.args !== undefined && !isRecord(config.args)) out.push({ code: "argsExpression", step });
      else {
        const args = config.args ?? {};
        for (const arg of missingArgs(tool.inputSchema, args)) out.push({ code: "missingArg", step, arg });
        for (const arg of unknownArgs(tool.inputSchema, args)) out.push({ code: "unknownArg", step, arg });
      }
      break;
    }
    case "agent":
      if (!refs.agents.some((a) => a.key === config.agent)) out.push({ code: "missingAgent", step });
      break;
    case "memory":
      if (!refs.spaces.some((s) => s.key === config.space)) out.push({ code: "missingSpace", step });
      break;
    case "decision":
      if (!node.data.rules) out.push({ code: "noRules", step });
      else if (!rulesComplete(node.data.rules)) out.push({ code: "missingRules", step });
      break;
    case "human_workforce":
      if (!filled(config.title)) out.push({ code: "missingTitle", step });
      if (!filled(config.show)) out.push({ code: "missingShow", step });
      break;
    case "approval":
      if (!filled(config.title)) out.push({ code: "missingTitle", step });
      break;
    case "verification": {
      const checks = Array.isArray(config.checks) ? config.checks.filter(filled) : [];
      if (!checks.length && !filled(config.schema)) out.push({ code: "missingCheck", step });
      break;
    }
    case "trigger":
    case "end":
      break;
    default: {
      // A step type with no rule above fails to compile; at run time an unknown type simply has no rule.
      const unknownType: never = type;
      void unknownType;
      break;
    }
  }
  return out;
}

function reachableFrom(start: string, outgoing: Map<string, StepEdge[]>): Set<string> {
  const seen = new Set<string>([start]);
  const visit = (at: string) => {
    for (const e of outgoing.get(at) ?? [])
      if (!seen.has(e.target)) {
        seen.add(e.target);
        visit(e.target);
      }
  };
  visit(start);
  return seen;
}

/** An end completes the run unless it says otherwise: the API reads a missing status as COMPLETED. */
const completes = (data: StepNodeData) => data.type === "end" && (data.config.status ?? "COMPLETED") === "COMPLETED";

/** The API takes a pack of at least two steps (PackDraft.steps min_length); the start alone is not a pack. */
export const MIN_STEPS = 2;
/** And of at most sixty (PackDraft.steps max_length): pasting, duplicating or an import can pass that. */
export const MAX_STEPS = 60;

/** Everything the editor can see is wrong with the graph, in step order. */
export function graphIssues(nodes: StepNode[], edges: StepEdge[], tools: ToolIndex, refs: Refs): LocalIssue[] {
  const out: LocalIssue[] = [];
  if (nodes.length < MIN_STEPS) out.push({ code: "tooFewSteps" });
  if (nodes.length > MAX_STEPS) out.push({ code: "tooManySteps" });
  const starts = nodes.filter((n) => n.data.type === "trigger");
  if (starts.length === 0) out.push({ code: "noStart" });
  if (starts.length > 1) out.push({ code: "manyStarts" });
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const outgoing = new Map<string, StepEdge[]>();
  for (const e of edges) outgoing.set(e.source, [...(outgoing.get(e.source) ?? []), e]);
  const reached = starts.length ? reachableFrom(starts[0].id, outgoing) : null;

  for (const node of nodes) {
    out.push(...stepIssues(node, tools, refs));
    const routed = new Set((outgoing.get(node.id) ?? []).map((e) => e.sourceHandle));
    for (const outcome of outcomesOf(node.data))
      if (!routed.has(outcome)) out.push({ code: "unrouted", step: node.id, outcome });
    const unapproved = edges.some(
      (e) => e.target === node.id && !(byId.get(e.source)?.data.type === "approval" && e.sourceHandle === "granted"),
    );
    if (isWrite(node.data, tools) && unapproved) out.push({ code: "writeWithoutApproval", step: node.id });
    if (reached && !reached.has(node.id)) out.push({ code: "unreachable", step: node.id });
  }

  const completing = nodes.some((n) => reached?.has(n.id) && completes(n.data));
  if (reached && !completing) out.push({ code: "neverCompletes" });
  return out;
}
