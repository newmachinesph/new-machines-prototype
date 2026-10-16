/**
 * The start-run form built from a pack's input JSON Schema: strings, numbers, integers, booleans, enums,
 * `format: date` and one level of nested objects. Anything else (arrays, deeper objects) is entered as JSON.
 */

type JsonSchema = {
  type?: string | string[];
  title?: string;
  description?: string;
  enum?: unknown[];
  format?: string;
  pattern?: string;
  default?: unknown;
  properties?: Record<string, JsonSchema>;
  required?: string[];
};

export type FieldKind = "string" | "date" | "number" | "integer" | "boolean" | "enum" | "json";

export type InputField = {
  /** Dotted path, such as "since" or "period.since". */
  name: string;
  path: string[];
  label: string;
  description?: string;
  kind: FieldKind;
  options?: string[];
  /** Always required: a top-level required field, or a required child of a required object. */
  required: boolean;
  pattern?: string;
  /** The label of the object this field sits in, for one level of nesting. */
  group?: string;
  /** The key of that object ("period" for "period.since"). */
  groupKey?: string;
  /** Whether the object itself is required. An optional object is sent only when one of its fields is filled. */
  groupRequired?: boolean;
  /** Required within its object: always when the object is required, otherwise once the object is filled in. */
  requiredInGroup?: boolean;
  /** The schema's default, as the form holds it. */
  initial: string | boolean;
};

export type InputValues = Record<string, unknown>;

/** Messages for the client-side checks. Pass translated text. */
export type InputMessages = {
  required: (label: string) => string;
  number: string;
  integer: string;
  date: string;
  pattern: string;
  json: string;
};

/** A string matching exactly YYYY-MM-DD is a date, whether the schema says `format: date` or spells the pattern. */
const DATE_PATTERN = "^\\d{4}-\\d{2}-\\d{2}$";
const DATE = /^\d{4}-\d{2}-\d{2}$/;

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const typeOf = (s: JsonSchema) => (Array.isArray(s.type) ? s.type.find((t) => t !== "null") : s.type);

/** "order_ids" or "orderIds" becomes "Order ids". */
export function humanize(key: string): string {
  const words = key
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .trim()
    .toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function kindOf(s: JsonSchema): FieldKind {
  if (Array.isArray(s.enum) && s.enum.length > 0 && s.enum.every((v) => typeof v === "string")) return "enum";
  switch (typeOf(s)) {
    case "string":
      return s.format === "date" || s.pattern === DATE_PATTERN ? "date" : "string";
    case "number":
      return "number";
    case "integer":
      return "integer";
    case "boolean":
      return "boolean";
    default:
      return "json";
  }
}

/** The "(YYYY-MM-DD)" hint some schemas put in a date's description: the date input already sets the format, so
 * the form shows one. A hint sharing its brackets with another note ("(YYYY-MM-DD, read in UTC)") keeps the note. */
const DATE_FORMAT_HINT = /\s*\(\s*YYYY-MM-DD\s*\)/g;
const DATE_FORMAT_LEAD = /\(\s*YYYY-MM-DD\s*,\s*/g;

function describe(kind: FieldKind, s: JsonSchema): string | undefined {
  if (kind !== "date" || !s.description) return s.description;
  return s.description.replace(DATE_FORMAT_HINT, "").replace(DATE_FORMAT_LEAD, "(").trim() || undefined;
}

/** `day` (YYYY-MM-DD) moved by `days`. */
function shiftDay(day: string, days: number): string {
  const at = new Date(`${day}T12:00:00Z`);
  at.setUTCDate(at.getUTCDate() + days);
  return at.toISOString().slice(0, 10);
}

/** The first day of a range ("since", "from", "week_start"): a week back, so a range covers the last 7 days. */
const RANGE_START = /(^|_)(since|from|start)$|^start/;

/** A date field's first value when its schema has none, by its name, from `today`: a range's start a week back,
 * a single "day" yesterday's (the usual day to look back on), anything else (an end, "as of") today. */
function defaultDay(key: string, today: string): string {
  const name = key.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase();
  if (RANGE_START.test(name)) return shiftDay(today, -6);
  if (name === "day") return shiftDay(today, -1);
  return today;
}

function initialOf(kind: FieldKind, s: JsonSchema, key = "", today?: string): string | boolean {
  if (kind === "boolean") return s.default === true;
  if (s.default === undefined || s.default === null) return kind === "date" && today ? defaultDay(key, today) : "";
  return kind === "json" ? JSON.stringify(s.default) : String(s.default);
}

type Group = { key: string; label: string; required: boolean; inner: Set<string> };

function field(path: string[], s: JsonSchema, required: boolean, group?: Group, today?: string): InputField {
  const kind = kindOf(s);
  const key = path[path.length - 1] ?? "";
  return {
    name: path.join("."),
    path,
    label: s.title ?? humanize(key),
    description: describe(kind, s),
    kind,
    options: kind === "enum" ? (s.enum as string[]) : undefined,
    required,
    pattern: kind === "string" && typeof s.pattern === "string" ? s.pattern : undefined,
    ...(group
      ? {
          group: group.label,
          groupKey: group.key,
          groupRequired: group.required,
          requiredInGroup: group.inner.has(key),
        }
      : {}),
    initial: initialOf(kind, s, key, today),
  };
}

/**
 * The form fields of an object input schema, or null when there is no such schema (use free text then). With
 * `today` (YYYY-MM-DD), a date field the schema gives no default starts at a sensible day (see defaultDay); an
 * optional object's dates stay empty, so the object is still left out until someone fills it in.
 */
export function inputFields(schema: unknown, today?: string): InputField[] | null {
  if (!isRecord(schema)) return null;
  const root = schema as JsonSchema;
  if (typeOf(root) !== "object" && !isRecord(root.properties)) return null;
  const required = new Set(root.required ?? []);
  const out: InputField[] = [];
  for (const [key, prop] of Object.entries(root.properties ?? {})) {
    if (!isRecord(prop)) continue;
    if (typeOf(prop) === "object" && isRecord(prop.properties)) {
      const group: Group = {
        key,
        label: prop.title ?? humanize(key),
        required: required.has(key),
        inner: new Set(prop.required ?? []),
      };
      for (const [child, sub] of Object.entries(prop.properties)) {
        if (!isRecord(sub)) continue;
        // Only one level of nesting gets its own fields; deeper objects are entered as JSON.
        const dayFrom = group.required ? today : undefined;
        const f = field([key, child], sub, group.required && group.inner.has(child), group, dayFrom);
        out.push(typeOf(sub) === "object" ? { ...f, kind: "json", initial: initialOf("json", sub) } : f);
      }
    } else {
      out.push(field([key], prop, required.has(key), undefined, required.has(key) ? today : undefined));
    }
  }
  return out;
}

const valueAt = (values: InputValues | undefined, path: string[]): unknown =>
  path.reduce<unknown>((o, k) => (isRecord(o) ? o[k] : undefined), values);

const isEmpty = (v: unknown) => v === undefined || v === null || (typeof v === "string" && v.trim() === "");

/** A field holds something to send: text that isn't blank, or a checkbox moved off its default. */
const isFilled = (f: InputField, values: InputValues | undefined) => {
  const v = valueAt(values, f.path);
  return f.kind === "boolean" ? (v === true) !== (f.initial === true) : !isEmpty(v);
};

/**
 * The optional objects nobody filled in, by key. They are left out of the input entirely, and their
 * required fields only become required once one of their fields is filled.
 */
function untouchedGroups(fields: InputField[], values: InputValues | undefined): Set<string> {
  const keys = new Set(fields.filter((f) => f.groupKey && !f.groupRequired).map((f) => f.groupKey as string));
  for (const f of fields) if (f.groupKey && isFilled(f, values)) keys.delete(f.groupKey);
  return keys;
}

const requiredNow = (f: InputField, untouched: Set<string>) =>
  f.required || (!!f.requiredInGroup && !!f.groupKey && !untouched.has(f.groupKey));

/** Client-side problems by field name. The API checks the input against the full schema again. */
export function validateInput(fields: InputField[], values: InputValues | undefined, m: InputMessages) {
  const errors: Record<string, string> = {};
  const untouched = untouchedGroups(fields, values);
  for (const f of fields) {
    const v = valueAt(values, f.path);
    if (f.kind === "boolean") continue;
    if (isEmpty(v)) {
      if (requiredNow(f, untouched)) errors[f.name] = m.required(f.label);
      continue;
    }
    const text = String(v).trim();
    if (f.kind === "number" && !Number.isFinite(Number(text))) errors[f.name] = m.number;
    if (f.kind === "integer" && !Number.isInteger(Number(text))) errors[f.name] = m.integer;
    if (f.kind === "date" && !DATE.test(text)) errors[f.name] = m.date;
    if (f.kind === "json") {
      try {
        JSON.parse(text);
      } catch {
        errors[f.name] = m.json;
      }
    }
    if (f.kind === "string" && f.pattern) {
      try {
        if (!new RegExp(f.pattern, "u").test(text)) errors[f.name] = m.pattern;
      } catch {
        // A pattern this browser can't compile is left to the API.
      }
    }
  }
  return errors;
}

/**
 * The input object to send: typed values at their paths, empty optional fields left out, and an optional
 * object nobody filled in left out whole. A required object is always sent, even when it ends up empty.
 */
export function buildInput(fields: InputField[], values: InputValues | undefined): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  const untouched = untouchedGroups(fields, values);
  for (const f of fields) {
    if (f.groupKey && untouched.has(f.groupKey)) continue;
    if (f.groupKey && !isRecord(out[f.groupKey])) out[f.groupKey] = {};
    const v = valueAt(values, f.path);
    let typed: unknown;
    if (f.kind === "boolean") typed = v === true;
    else if (isEmpty(v)) continue;
    else {
      const text = String(v).trim();
      if (f.kind === "number" || f.kind === "integer") typed = Number(text);
      else if (f.kind === "json") typed = JSON.parse(text);
      else typed = text;
    }
    let node = out;
    for (const k of f.path.slice(0, -1)) {
      if (!isRecord(node[k])) node[k] = {};
      node = node[k] as Record<string, unknown>;
    }
    node[f.path[f.path.length - 1] ?? f.name] = typed;
  }
  return out;
}

/**
 * The form field an API input error points at ("period/since" is "period.since"). A deeper path lands on
 * the field holding it, such as "period/range/from" on a JSON field "period.range": the longest field name
 * the path starts with.
 */
export function fieldForIssue(fields: InputField[], path: string): InputField | undefined {
  const name = path.replace(/^\//, "").replaceAll("/", ".");
  let best: InputField | undefined;
  for (const f of fields) {
    const holds = name === f.name || name.startsWith(`${f.name}.`);
    if (holds && (!best || f.name.length > best.name.length)) best = f;
  }
  return best;
}
