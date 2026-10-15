/**
 * What a step's CEL can read, for the field picker: the run's input fields (`input.<name>`), recalled memory
 * (`memory`, after a recall step), each step that runs before this one (`nodes.<id>.output`, with an agent's
 * output fields from its schema), and inside a connector's for_each the current `item`. Pure: no React.
 */
import type { Palette } from "@/lib/api/gen/types.gen";
import type { StepEdge, StepNode, StepNodeData } from "./graph";
import type { PackDetails } from "./store";

export type CelGroup = "input" | "memory" | "steps" | "item";
/**
 * `label` is data shown as sent (a step id, a schema title, an input field's label). `fixed` names the options
 * whose label is one of our own words, so the field can show it translated: `memory`, the `item` of a for_each,
 * and a looped connector's `results` (its label is `<step id> · results`).
 */
export type CelOption = { group: CelGroup; expr: string; label: string; fixed?: "memory" | "item" | "results" };

/** A run input field's name is a CEL identifier, the API's InputField.name rule (details.ts reports a bad one). */
const IDENTIFIER = /^[A-Za-z_][A-Za-z0-9_]*$/;

type Schema = { title?: string; properties?: Record<string, Schema>; items?: Schema };
const asSchema = (v: unknown): Schema | undefined => (v && typeof v === "object" ? (v as Schema) : undefined);
const fieldsOf = (schema: Schema | undefined) => Object.entries(schema?.properties ?? {});

/** A value starting with "=" is CEL, as in workflow.yaml; anything else is plain text. */
export const isCel = (value: unknown): value is string => typeof value === "string" && value.startsWith("=");

/** Every step on some path into `id`. */
export function upstreamOf(id: string, edges: StepEdge[]): Set<string> {
  const into = new Map<string, string[]>();
  for (const e of edges) into.set(e.target, [...(into.get(e.target) ?? []), e.source]);
  const seen = new Set<string>();
  const visit = (at: string) => {
    for (const from of into.get(at) ?? [])
      if (from !== id && !seen.has(from)) {
        seen.add(from);
        visit(from);
      }
  };
  visit(id);
  return seen;
}

/** An agent step's output schema: the schema it names, from the palette, else its agent's own. */
export function outputSchemaOf(node: StepNode, palette: Palette): Schema | undefined {
  if (node.data.type !== "agent") return undefined;
  const ref = node.data.config.output_schema;
  const shared = palette.schemas.find((s) => s.key === ref)?.body;
  if (shared) return asSchema(shared);
  const agent = palette.agents.find((a) => a.key === node.data.config.agent);
  return agent && (!ref || agent.outputSchemaRef === ref) ? asSchema(agent.outputSchema) : undefined;
}

/** Steps whose output is not read through `nodes.<id>.output`: the start, ends, and memory (read as `memory`). */
const NO_OUTPUT = new Set(["trigger", "end", "memory"]);

/** A memory step that recalls: the runtime sets `memory` only for a recall, and "recall" is the default op. */
const recalls = (data: StepNodeData) => data.type === "memory" && (data.config.op ?? "recall") === "recall";

export function celOptions(
  id: string,
  nodes: StepNode[],
  edges: StepEdge[],
  details: Pick<PackDetails, "inputFields">,
  palette: Palette,
): CelOption[] {
  const upstream = upstreamOf(id, edges);
  const before = nodes.filter((n) => upstream.has(n.id));
  const options: CelOption[] = [];
  const named = new Set<string>();
  for (const f of details.inputFields ?? []) {
    if (!IDENTIFIER.test(f.name) || named.has(f.name)) continue;
    named.add(f.name);
    options.push({ group: "input", expr: `input.${f.name}`, label: f.label || f.name });
  }
  if (before.some((n) => recalls(n.data)))
    options.push({ group: "memory", expr: "memory", label: "memory", fixed: "memory" });
  for (const n of before) {
    if (NO_OUTPUT.has(n.data.type)) continue;
    const base = `nodes.${n.id}.output`;
    options.push({ group: "steps", expr: base, label: n.id });
    for (const [field, schema] of fieldsOf(outputSchemaOf(n, palette)))
      options.push({ group: "steps", expr: `${base}.${field}`, label: `${n.id} · ${schema.title ?? field}` });
    if (n.data.type === "connector" && isCel(n.data.config.for_each))
      options.push({ group: "steps", expr: `${base}.results`, label: `${n.id} · results`, fixed: "results" });
  }
  return options;
}

const FOR_EACH = /^=\s*nodes\.([a-z][a-z0-9_]*)\.output\.([A-Za-z_][A-Za-z0-9_]*)\s*$/;

/** Inside a connector's for_each: `item`, and its fields when the list comes from an agent's output schema. */
export function itemOptions(forEach: unknown, nodes: StepNode[], palette: Palette): CelOption[] {
  if (!isCel(forEach)) return [];
  const match = FOR_EACH.exec(forEach);
  const node = match ? nodes.find((n) => n.id === match[1]) : undefined;
  const items = node && match ? outputSchemaOf(node, palette)?.properties?.[match[2]]?.items : undefined;
  return [
    { group: "item" as const, expr: "item", label: "item", fixed: "item" as const },
    ...fieldsOf(items).map(([field, schema]) => ({
      group: "item" as const,
      expr: `item.${field}`,
      label: schema.title ?? field,
    })),
  ];
}
