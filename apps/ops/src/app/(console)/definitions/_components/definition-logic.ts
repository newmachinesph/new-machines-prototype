import type { DefinitionKind } from "@/lib/queries/definitions";

export const KINDS = [
  "pack",
  "workflow",
  "contract",
  "agent",
  "connector",
  "decision_rules",
  "memory_space",
  "schema",
  "models",
  "taxonomy",
] as const satisfies readonly DefinitionKind[];

export const KIND_LABEL: Record<DefinitionKind, string> = {
  pack: "Pack",
  workflow: "Workflow",
  contract: "Work contract",
  agent: "Agent",
  connector: "Connector",
  decision_rules: "Decision rules",
  memory_space: "Memory space",
  schema: "Schema",
  models: "Model profiles",
  taxonomy: "Taxonomy",
};

/** Taxonomy and model profiles exist once (key `default`), so they can be edited but not created. */
export const CREATABLE_KINDS = KINDS.filter((k) => k !== "models" && k !== "taxonomy");

export const isKind = (value: string): value is DefinitionKind => (KINDS as readonly string[]).includes(value);

/** The editor's address. A schema key's slash stays a path separator; the route joins the segments back. */
export function definitionHref(kind: DefinitionKind, key: string, version?: number | null): string {
  const path = `/definitions/${kind}/${key.split("/").map(encodeURIComponent).join("/")}`;
  return version ? `${path}?version=${version}` : path;
}

/** The API's rule for new keys: `[a-z0-9][a-z0-9_-]{0,63}`, and `<pack>/<name>` for schemas. */
const SLUG = "[a-z0-9][a-z0-9_-]{0,63}";
const KEY_PATTERN = new RegExp(`^${SLUG}$`);
const SCHEMA_KEY_PATTERN = new RegExp(`^${SLUG}/${SLUG}$`);

export function keyProblem(kind: DefinitionKind, key: string): string | null {
  if (!key) return "Enter a key.";
  if (kind === "schema") {
    return SCHEMA_KEY_PATTERN.test(key)
      ? null
      : "Use <pack>/<name>, each part lowercase letters, numbers, hyphens or underscores.";
  }
  return KEY_PATTERN.test(key)
    ? null
    : "Use lowercase letters, numbers, hyphens or underscores, starting with a letter or number, up to 64 characters.";
}

/** The file a definition lives in, as the export names it (see `path_for` in the API). */
export function mainFileName(kind: DefinitionKind, key: string): string {
  switch (kind) {
    case "taxonomy":
    case "models":
    case "pack":
    case "workflow":
    case "contract":
      return `${kind}.yaml`;
    case "agent":
      return "agent.yaml";
    case "schema":
      return `${key.split("/").pop()}.json`;
    default:
      return `${key}.yaml`;
  }
}

/** Top-level fields that name the definition itself; nested fields with the same names are references. */
const IDENTITY_FIELDS = ["key", "slug", "agent_id", "contract_id", "workflow_id"];

/** A top-level `name:` line holding a one-line value (not a `|` or `>` block). */
const NAME_LINE = /^name:[ \t]+(?![|>])\S.*$/m;
/** Characters that would end or change a plain YAML scalar; such names are written double-quoted. */
const NEEDS_QUOTES = /: | #|:$|\s$|^[\s'"&*!|>%@`{[\]-]|[\t\n]/;

/** `name: <value>` as YAML, quoted only when a plain scalar would not read back as the same text. */
const nameLine = (value: string) => `name: ${NEEDS_QUOTES.test(value) ? JSON.stringify(value) : value}`;

/**
 * A copy of another definition's main file with its own identity swapped to `newKey`. When the original has a
 * `name` (pass the parsed body's), the copy is named "Copy of <name>" so the two are not confused in lists.
 */
export function templateFrom(yaml: string, fromKey: string, newKey: string, name?: unknown): string {
  const escaped = fromKey.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const identity = new RegExp(`^(${IDENTITY_FIELDS.join("|")}):[ \\t]*(['"]?)${escaped}\\2[ \\t]*$`, "gm");
  const swapped = yaml.replace(identity, `$1: ${newKey}`);
  if (typeof name !== "string" || !name.trim()) return swapped;
  return swapped.replace(NAME_LINE, () => nameLine(`Copy of ${name.trim()}`));
}

const SKILL_PATH = /^skills\/[a-z0-9][a-z0-9_-]{0,63}\.md$/;

/** Whether `path` can be added as an agent's Markdown file. */
export function markdownPathProblem(path: string, existing: readonly string[]): string | null {
  if (!SKILL_PATH.test(path)) return "Use skills/<name>.md, with a lowercase name.";
  if (existing.includes(path)) return `${path} is already a file of this agent.`;
  return null;
}

/** Browsers drop folders from download names, so the path is kept in the name: `a/b/c.md` → `a__b__c.md`. */
export const exportFileName = (path: string) => path.split("/").join("__");
