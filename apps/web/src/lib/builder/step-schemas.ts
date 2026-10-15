/**
 * Each step type's settings as a small JSON Schema, which SchemaForm draws. Labels and help are keys under
 * `studioFields`. Five extensions say how a field is edited:
 * - `x-cel`: the value may be CEL ("=..."), so the field picker is offered;
 * - `x-multiline`: a long text;
 * - `x-source`: chosen from the palette (agents, tools, spaces or schemas);
 * - `x-args`: the fields are the chosen tool's own inputSchema, from the registry;
 * - `x-map`: named values (an agent step's inputs), each a value or an expression.
 * A decision's settings are its rules, edited by RulesEditor. The helpers at the end read and write a tool's
 * arguments, whose shapes come from the connector definitions rather than from here. Pure: no React.
 */
import type en from "../../../messages/en.json";
import type { Palette } from "@/lib/api/gen/types.gen";
import type { StepConfig, StepNodeData } from "./graph";
import type { StepType } from "./routes";

type Fields = (typeof en)["studioFields"];
export type FieldLabel = keyof Fields["field"];
export type FieldHelp = keyof Fields["help"];
export type EnumValue = keyof Fields["enum"];
export type Source = "agents" | "tools" | "spaces" | "schemas";

export type FieldSchema = {
  type: "string" | "integer" | "array" | "object";
  title: FieldLabel;
  help?: FieldHelp;
  enum?: readonly EnumValue[];
  minimum?: number;
  maximum?: number;
  items?: { type: "string" };
  "x-cel"?: true;
  "x-multiline"?: true;
  "x-source"?: Source;
  "x-args"?: true;
  "x-map"?: true;
};
export type StepSchema = {
  type: "object";
  required: readonly string[];
  properties: Readonly<Record<string, FieldSchema>>;
};

/** Whole seconds, from one second to two days: the API's bounds for a step's timeout_s. */
const TIMEOUT: FieldSchema = { type: "integer", title: "timeout", help: "timeout", minimum: 1, maximum: 172_800 };
const NONE: StepSchema = { type: "object", required: [], properties: {} };

export const STEP_SCHEMAS: Record<StepType, StepSchema> = {
  trigger: NONE,
  memory: {
    type: "object",
    required: ["space"],
    properties: {
      space: { type: "string", title: "space", "x-source": "spaces" },
      query: { type: "string", title: "query", help: "query", "x-cel": true },
    },
  },
  connector: {
    type: "object",
    required: ["tool"],
    properties: {
      tool: { type: "string", title: "tool", "x-source": "tools" },
      for_each: { type: "string", title: "forEach", help: "forEach", "x-cel": true },
      args: { type: "object", title: "args", "x-args": true },
    },
  },
  agent: {
    type: "object",
    required: ["agent", "task"],
    properties: {
      agent: { type: "string", title: "agent", "x-source": "agents" },
      task: { type: "string", title: "task", help: "task", "x-multiline": true },
      inputs: { type: "object", title: "inputs", help: "inputs", "x-map": true, "x-cel": true },
    },
  },
  decision: NONE,
  human_workforce: {
    type: "object",
    required: ["title", "show"],
    properties: {
      title: { type: "string", title: "title" },
      instructions: { type: "string", title: "instructions", "x-multiline": true },
      show: { type: "string", title: "show", help: "show", "x-cel": true },
      timeout_s: TIMEOUT,
    },
  },
  approval: {
    type: "object",
    required: ["title"],
    properties: {
      title: { type: "string", title: "title" },
      summary: { type: "string", title: "summary", help: "summary", "x-cel": true },
      timeout_s: TIMEOUT,
    },
  },
  verification: {
    type: "object",
    required: [],
    properties: {
      schema: { type: "string", title: "schema", "x-source": "schemas" },
      value: { type: "string", title: "value", "x-cel": true },
      checks: { type: "array", title: "checks", help: "checks", items: { type: "string" }, "x-cel": true },
    },
  },
  end: {
    type: "object",
    required: ["status"],
    properties: {
      status: { type: "string", title: "status", enum: ["COMPLETED", "FAILED"] },
      deliverable: { type: "string", title: "deliverable", help: "deliverable", "x-cel": true },
    },
  },
};

/** Settings that follow from others: an agent step reads its agent's output schema; a new tool has new arguments. */
export function withDerived(data: StepNodeData, next: StepConfig, palette: Palette): StepConfig {
  if (data.type === "agent" && next.agent !== data.config.agent) {
    const agent = palette.agents.find((a) => a.key === next.agent);
    return { ...next, output_schema: agent?.outputSchemaRef ?? "" };
  }
  if (data.type === "connector" && next.tool !== data.config.tool) return { ...next, args: {} };
  return next;
}

/**
 * A tool argument as typed: a number or a boolean when its schema says so, otherwise the text or expression. Only
 * text that reads back as the same number is a number, so "1." and "1e" stay text while they are being typed.
 */
export function coerceArg(value: string, type: unknown): unknown {
  if (value === "" || value.startsWith("=")) return value;
  const trimmed = value.trim();
  const n = Number(trimmed);
  if ((type === "integer" || type === "number") && trimmed !== "" && Number.isFinite(n) && String(n) === trimmed)
    return n;
  if (type === "boolean" && (value === "true" || value === "false")) return value === "true";
  return value;
}

/** Leaves out optional settings that are empty, so the saved workflow.yaml has no blank keys. */
export const withoutBlank = (config: StepConfig, required: readonly string[]): StepConfig =>
  Object.fromEntries(Object.entries(config).filter(([key, v]) => v !== "" || required.includes(key)));

/* ── A tool's arguments, whose shapes are the connector definition's inputSchema ── */

/** A property schema from a tool's inputSchema, as the registry sends it. */
export type ArgSchema = Record<string, unknown>;

export const asRecord = (v: unknown): Record<string, unknown> =>
  v !== null && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};

/** A schema that names its fields and refuses any other (`additionalProperties: false`), as every connector tool's does. */
export const isClosed = (schema: unknown) => asRecord(schema).additionalProperties === false;

/** The keys of `args` that `schema.properties` does not name. An expression, or anything but an object, has none. */
export function undeclaredKeys(schema: unknown, args: unknown): string[] {
  if (args === null || typeof args !== "object" || Array.isArray(args)) return [];
  const properties = asRecord(asRecord(schema).properties);
  return Object.keys(args).filter((key) => !Object.hasOwn(properties, key));
}

const isEmptyObject = (v: unknown) =>
  v !== null && typeof v === "object" && !Array.isArray(v) && Object.keys(v).length === 0;

/**
 * `args` with one argument set, keeping the others' order. A cleared value ("" or undefined) removes the key, and
 * so does an object with nothing left inside it, so a half-filled nested argument does not save as `{}`.
 */
export function withArg(args: Record<string, unknown>, key: string, value: unknown): Record<string, unknown> {
  if (value === undefined || value === "" || isEmptyObject(value))
    return Object.fromEntries(Object.entries(args).filter(([k]) => k !== key));
  return { ...args, [key]: value };
}

export type ArgText = { ok: true; value: unknown } | { ok: false };

/**
 * A list or object argument as typed: empty clears it, "=" starts an expression for the whole value, and anything
 * else must be JSON of that shape. Read when the field is left, since partial JSON is not a value.
 */
export function parseArgText(text: string, kind: "array" | "object"): ArgText {
  const trimmed = text.trim();
  if (trimmed === "" || trimmed.startsWith("=")) return { ok: true, value: trimmed };
  try {
    const value: unknown = JSON.parse(trimmed);
    const fits = kind === "array" ? Array.isArray(value) : !Array.isArray(value) && isRecordValue(value);
    return fits ? { ok: true, value } : { ok: false };
  } catch {
    return { ok: false };
  }
}
const isRecordValue = (v: unknown) => v !== null && typeof v === "object";

/** An argument as a field shows it: a string as it is, anything else as JSON, never "[object Object]". */
export const argText = (value: unknown): string =>
  value === undefined || value === null ? "" : typeof value === "string" ? value : JSON.stringify(value);

/** A number argument's bounds, for the field's help and limits. */
export const rangeOf = (schema: ArgSchema): { min: number | undefined; max: number | undefined } => ({
  min: typeof schema.minimum === "number" ? schema.minimum : undefined,
  max: typeof schema.maximum === "number" ? schema.maximum : undefined,
});
