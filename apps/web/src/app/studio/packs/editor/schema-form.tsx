"use client";

import { Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";
import { Select } from "@/components/base";
import { Button } from "@/components/ui";
import type { Palette, PaletteTool } from "@/lib/api/gen/types.gen";
import { isCel, type CelOption } from "@/lib/builder/cel-fields";
import type { StepConfig } from "@/lib/builder/graph";
import { isBlockedTool } from "@/lib/builder/rules";
import {
  argText,
  asRecord,
  coerceArg,
  isClosed,
  parseArgText,
  rangeOf,
  undeclaredKeys,
  withArg,
  withoutBlank,
  type ArgSchema,
  type FieldSchema,
  type Source,
  type StepSchema,
} from "@/lib/builder/step-schemas";
import { CelField, FIELD_CLASS } from "./cel-field";
import { useReadOnly } from "./read-only";
import { useRowIds } from "./row-ids";

type OnValue = (value: unknown, record: boolean) => void;
type Entries = [string, unknown][];

const helpId = (id: string, help: string | undefined) => (help ? `${id}-help` : undefined);

/**
 * Draws a step's settings from its JSON Schema (STEP_SCHEMAS). `onChange(next, record)`: typing passes `false`,
 * choices and added or removed rows pass `true`, so the settings panel records one undo step per change.
 */
export function SchemaForm({
  stepId,
  schema,
  value,
  onChange,
  cel,
  item,
  palette,
}: {
  stepId: string;
  schema: StepSchema;
  value: StepConfig;
  onChange: (next: StepConfig, record: boolean) => void;
  cel: CelOption[];
  item: CelOption[];
  palette: Palette;
}) {
  const tool = palette.tools.find((x) => x.ref === value.tool);
  const set = (key: string, v: unknown, record: boolean) =>
    onChange(withoutBlank({ ...value, [key]: v }, schema.required), record);
  return (
    <div className="space-y-4">
      {Object.entries(schema.properties).map(([key, field]) => (
        <Field
          key={key}
          id={`${stepId}-${key}`}
          field={field}
          required={schema.required.includes(key)}
          value={value[key]}
          onChange={(v, record) => set(key, v, record)}
          // The runtime binds `item` only inside the tool's own settings while the step repeats over a list.
          cel={key === "args" ? [...cel, ...item] : cel}
          palette={palette}
          tool={tool}
        />
      ))}
    </div>
  );
}

/**
 * A caption above a control and help below it, tied by htmlFor and aria-describedby, so the control's name is the
 * caption alone and the help is its description.
 */
function Labelled({ id, label, help, children }: { id: string; label: string; help?: string; children: ReactNode }) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>
      {children}
      {help ? (
        <p id={helpId(id, help)} className="mt-1 text-xs text-muted">
          {help}
        </p>
      ) : null}
    </div>
  );
}

function Field({
  id,
  field,
  required,
  value,
  onChange,
  cel,
  palette,
  tool,
}: {
  id: string;
  field: FieldSchema;
  required: boolean;
  value: unknown;
  onChange: OnValue;
  cel: CelOption[];
  palette: Palette;
  tool: PaletteTool | undefined;
}) {
  const t = useTranslations("studioFields");
  const readOnly = useReadOnly();
  const name = t(`field.${field.title}`);
  const label = required ? t("required", { label: name }) : name;
  const help = field.help ? t(`help.${field.help}`) : undefined;
  const source = field["x-source"];

  if (source)
    return (
      <SourceField id={id} label={label} source={source} value={argText(value)} onChange={onChange} palette={palette} />
    );
  if (field.enum)
    return (
      <Labelled id={id} label={label} help={help}>
        <div className="mt-1.5">
          <Select
            id={id}
            label={label}
            describedBy={helpId(id, help)}
            className="w-full"
            disabled={readOnly}
            // The API reads a missing choice as the first one.
            value={argText(value) || field.enum[0]}
            onValueChange={(v) => onChange(v, true)}
            items={field.enum.map((v) => ({ value: v, label: t(`enum.${v}`) }))}
          />
        </div>
      </Labelled>
    );
  if (field["x-args"])
    return <ArgsField id={id} label={label} tool={tool} value={value} onChange={onChange} options={cel} />;
  if (field["x-map"])
    return <MapField id={id} label={label} help={help} value={asRecord(value)} onChange={onChange} options={cel} />;
  if (field.type === "array")
    return (
      <ListField
        id={id}
        label={label}
        help={help}
        value={Array.isArray(value) ? value.map(argText) : []}
        onChange={onChange}
        options={cel}
      />
    );
  if (field.type === "integer")
    return (
      <Labelled id={id} label={label} help={help}>
        <input
          id={id}
          type="number"
          min={field.minimum}
          max={field.maximum}
          aria-describedby={helpId(id, help)}
          className={`${FIELD_CLASS} h-10 max-w-40`}
          value={argText(value)}
          onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value), false)}
        />
      </Labelled>
    );
  if (field["x-cel"])
    return (
      <CelField
        id={id}
        label={label}
        value={argText(value)}
        onChange={onChange}
        options={cel}
        multiline={field["x-multiline"]}
        help={help}
      />
    );
  return (
    <Labelled id={id} label={label} help={help}>
      {field["x-multiline"] ? (
        <textarea
          id={id}
          rows={4}
          aria-describedby={helpId(id, help)}
          className={`${FIELD_CLASS} py-2 leading-relaxed`}
          value={argText(value)}
          onChange={(e) => onChange(e.target.value, false)}
        />
      ) : (
        <input
          id={id}
          aria-describedby={helpId(id, help)}
          className={`${FIELD_CLASS} h-10`}
          value={argText(value)}
          onChange={(e) => onChange(e.target.value, false)}
        />
      )}
    </Labelled>
  );
}

/** A choice from the registry. A tool that a pack may not use is left out; one that changes data says so. */
function SourceField({
  id,
  label,
  source,
  value,
  onChange,
  palette,
}: {
  id: string;
  label: string;
  source: Source;
  value: string;
  onChange: OnValue;
  palette: Palette;
}) {
  const t = useTranslations("studioFields");
  const readOnly = useReadOnly();
  const options: Record<Source, { value: string; label: string }[]> = {
    agents: palette.agents.map((a) => ({ value: a.key, label: a.builtByTeam ? `${a.name} · ${t("team")}` : a.name })),
    tools: palette.tools
      .filter((tool) => !isBlockedTool(tool))
      .map((tool) => ({
        value: tool.ref,
        label: `${tool.app}: ${tool.name}${tool.actionClass === "write" ? ` · ${t("changesData")}` : ""}`,
      })),
    spaces: palette.spaces.map((s) => ({ value: s.key, label: s.name })),
    schemas: palette.schemas.map((s) => ({ value: s.key, label: s.title })),
  };
  const known = options[source];
  const items = [
    { value: "", label: t("choose") },
    ...known,
    ...(value && !known.some((o) => o.value === value) ? [{ value, label: t("unknown", { key: value }) }] : []),
  ];
  return (
    <Labelled id={id} label={label}>
      <div className="mt-1.5">
        <Select
          id={id}
          label={label}
          className="w-full"
          disabled={readOnly}
          value={value}
          onValueChange={(v) => onChange(v, true)}
          items={items}
        />
      </div>
    </Labelled>
  );
}

/**
 * A tool's arguments, drawn from its inputSchema: one field per property, as the schema shapes it, then the keys
 * the schema does not name: editable where the schema allows them, otherwise shown so they can be removed.
 * Numbers stay numbers.
 */
function ArgsField({
  id,
  label,
  tool,
  value,
  onChange,
  options,
}: {
  id: string;
  label: string;
  tool: PaletteTool | undefined;
  value: unknown;
  onChange: OnValue;
  options: CelOption[];
}) {
  const t = useTranslations("studioFields");
  const schema = asRecord(tool?.inputSchema);
  const args = asRecord(value);
  // Only a closed schema that names nothing takes no settings; an open one takes whatever is added.
  const takesNone = isClosed(schema) && !Object.keys(asRecord(schema.properties)).length && !Object.keys(args).length;
  return (
    <fieldset className="space-y-3 rounded-md border border-rule p-3">
      <legend className="px-1 text-sm font-medium">{label}</legend>
      {!tool ? (
        <p className="text-sm text-muted">{t("chooseToolFirst")}</p>
      ) : isCel(value) ? (
        <CelField
          id={id}
          label={label}
          value={value}
          onChange={onChange}
          options={options}
          help={t("argsExpressionHelp")}
        />
      ) : takesNone ? (
        <p className="text-sm text-muted">{t("noArgs")}</p>
      ) : (
        <ArgFields id={id} schema={schema} value={args} onChange={onChange} options={options} />
      )}
    </fieldset>
  );
}

/** The fields of one object schema, declared ones first, then any the object carries that the schema does not name. */
function ArgFields({
  id,
  schema,
  value,
  onChange,
  options,
}: {
  id: string;
  schema: ArgSchema;
  value: Record<string, unknown>;
  onChange: OnValue;
  options: CelOption[];
}) {
  const properties = asRecord(schema.properties);
  const required = Array.isArray(schema.required) ? schema.required : [];
  const set = (name: string, v: unknown, record: boolean) => onChange(withArg(value, name, v), record);
  const undeclared = undeclaredKeys(schema, value);
  return (
    <>
      {Object.entries(properties).map(([name, raw]) => (
        <ArgField
          key={name}
          id={`${id}-${name}`}
          name={name}
          schema={asRecord(raw)}
          required={required.includes(name)}
          value={value[name]}
          onChange={(v, record) => set(name, v, record)}
          options={options}
        />
      ))}
      {isClosed(schema) ? (
        undeclared.map((name) => (
          <UnknownArg
            key={name}
            id={`${id}-${name}`}
            name={name}
            value={value[name]}
            onRemove={() => set(name, undefined, true)}
          />
        ))
      ) : (
        <ExtraArgs id={`${id}-extra`} names={undeclared} value={value} onChange={onChange} options={options} />
      )}
    </>
  );
}

/**
 * One argument, by its schema: a choice for an enum; nested fields for an object with named fields; an expression or
 * JSON for a list or an open object; otherwise text that may be an expression, with a number's range in its help.
 */
function ArgField({
  id,
  name,
  schema,
  required,
  value,
  onChange,
  options,
}: {
  id: string;
  name: string;
  schema: ArgSchema;
  required: boolean;
  value: unknown;
  onChange: OnValue;
  options: CelOption[];
}) {
  const t = useTranslations("studioFields");
  const readOnly = useReadOnly();
  const label = required ? t("required", { label: name }) : name;
  const description = typeof schema.description === "string" ? schema.description : undefined;
  const type = schema.type;

  if (Array.isArray(schema.enum)) {
    const choices = schema.enum.map(String);
    const current = argText(value);
    const items = [
      { value: "", label: t("notSet") },
      ...choices.map((v) => ({ value: v, label: v })),
      ...(current && !choices.includes(current) ? [{ value: current, label: t("unknown", { key: current }) }] : []),
    ];
    return (
      <Labelled id={id} label={label} help={description}>
        <div className="mt-1.5">
          <Select
            id={id}
            label={label}
            describedBy={helpId(id, description)}
            className="w-full"
            disabled={readOnly}
            value={current}
            onValueChange={(v) => onChange(coerceArg(v, type), true)}
            items={items}
          />
        </div>
      </Labelled>
    );
  }
  if (type === "object" && Object.keys(asRecord(schema.properties)).length) {
    if (isCel(value))
      return (
        <CelField
          id={id}
          label={label}
          value={value}
          onChange={onChange}
          options={options}
          help={[description, t("wholeExpression")].filter(Boolean).join(" ")}
        />
      );
    return (
      <fieldset className="space-y-3 rounded-md border border-rule p-3" aria-describedby={helpId(id, description)}>
        <legend className="px-1 text-sm font-medium">{label}</legend>
        {description ? (
          <p id={helpId(id, description)} className="text-xs text-muted">
            {description}
          </p>
        ) : null}
        <ArgFields id={id} schema={schema} value={asRecord(value)} onChange={onChange} options={options} />
      </fieldset>
    );
  }
  if (type === "array" || type === "object")
    return <JsonField id={id} label={label} help={description} kind={type} value={value} onChange={onChange} />;

  const { min, max } = type === "integer" || type === "number" ? rangeOf(schema) : { min: undefined, max: undefined };
  const range =
    min !== undefined && max !== undefined
      ? t("range.both", { min, max })
      : min !== undefined
        ? t("range.min", { min })
        : max !== undefined
          ? t("range.max", { max })
          : undefined;
  return (
    <CelField
      id={id}
      label={label}
      help={[description, range].filter(Boolean).join(" ") || undefined}
      value={argText(value)}
      options={options}
      onChange={(v, record) => onChange(coerceArg(v, type), record)}
    />
  );
}

/**
 * A list, or an object with no named fields: an expression for the whole value, or JSON read when the field is
 * left, since JSON half typed is not a value yet.
 */
function JsonField({
  id,
  label,
  help,
  kind,
  value,
  onChange,
}: {
  id: string;
  label: string;
  help?: string;
  kind: "array" | "object";
  value: unknown;
  onChange: OnValue;
}) {
  const t = useTranslations("studioFields");
  const [draft, setDraft] = useState(argText(value));
  const [seen, setSeen] = useState(value);
  const [invalid, setInvalid] = useState(false);
  if (seen !== value) {
    // The value changed from outside the field (a commit, an undo, a paste): show it as it now is.
    setSeen(value);
    setDraft(argText(value));
    setInvalid(false);
  }
  const commit = () => {
    const parsed = parseArgText(draft, kind);
    setInvalid(!parsed.ok);
    if (parsed.ok) onChange(parsed.value, false);
  };
  const hint = `${id}-hint`;
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>
      <textarea
        id={id}
        rows={2}
        aria-describedby={hint}
        aria-invalid={invalid || undefined}
        className={`${FIELD_CLASS} py-2 font-mono text-[13px] leading-relaxed`}
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          setInvalid(false);
        }}
        onBlur={commit}
      />
      {invalid ? (
        <p id={hint} role="alert" className="mt-1 text-xs text-blocked">
          {t(`jsonInvalid.${kind}`)}
        </p>
      ) : (
        <p id={hint} className="mt-1 text-xs text-muted">
          {help ? `${help} ` : ""}
          {t("jsonHelp")}
        </p>
      )}
    </div>
  );
}

/** A setting a closed schema does not declare (from an import, a paste or a tool whose schema changed), shown so it can be removed. */
function UnknownArg({ id, name, value, onRemove }: { id: string; name: string; value: unknown; onRemove: () => void }) {
  const t = useTranslations("studioFields");
  return (
    <div className="flex items-end gap-2">
      <div className="min-w-0 flex-1">
        <label htmlFor={id} className="block text-sm font-medium">
          {t("unknownSetting", { key: name })}
        </label>
        <input
          id={id}
          readOnly
          aria-describedby={`${id}-help`}
          className={`${FIELD_CLASS} h-10 font-mono text-[13px] text-muted`}
          value={argText(value)}
        />
        <p id={`${id}-help`} className="mt-1 text-xs text-muted">
          {t("unknownSettingHelp")}
        </p>
      </div>
      <Button
        variant="ghost"
        className="mb-6 h-10 px-2"
        aria-label={t("removeSetting", { key: name })}
        onClick={onRemove}
      >
        <X className="size-4" aria-hidden />
      </Button>
    </div>
  );
}

/** Settings beyond the ones an open schema names, which the tool accepts: edited like an agent's named inputs. */
function ExtraArgs({
  id,
  names,
  value,
  onChange,
  options,
}: {
  id: string;
  names: string[];
  value: Record<string, unknown>;
  onChange: OnValue;
  options: CelOption[];
}) {
  const t = useTranslations("studioFields");
  const declared = Object.fromEntries(Object.entries(value).filter(([key]) => !names.includes(key)));
  const extras: Entries = names.map((key) => [key, value[key]]);
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted">{t("extraHelp")}</p>
      <NamedRows
        id={id}
        entries={extras}
        taken={Object.keys(value)}
        options={options}
        onChange={(next, record) => onChange({ ...declared, ...Object.fromEntries(next) }, record)}
        words={{
          name: (n) => t("extraName", { n }),
          value: (n) => t("extraValue", { n }),
          add: t("addExtra"),
          remove: (n) => t("removeExtra", { n }),
          prefix: "setting",
        }}
      />
    </div>
  );
}

type Words = {
  name: (n: number) => string;
  value: (n: number) => string;
  add: string;
  remove: (n: number) => string;
  /** New rows are named `<prefix>_1`, `<prefix>_2` and so on, the first free one. */
  prefix: string;
};

/**
 * Rows of a name and a value, each name committed when its field is left. Rows keep their own keys (useRowIds), so
 * removing one leaves the others' half-typed names where they were.
 */
function NamedRows({
  id,
  entries,
  taken,
  onChange,
  options,
  words,
}: {
  id: string;
  entries: Entries;
  /** Every name in use, including ones outside these rows; defaults to the rows' own. */
  taken?: string[];
  onChange: (next: Entries, record: boolean) => void;
  options: CelOption[];
  words: Words;
}) {
  const rows = useRowIds(entries.length);
  const names = taken ?? entries.map(([name]) => name);
  const freeName = () => {
    for (let n = 1; ; n++) if (!names.includes(`${words.prefix}_${n}`)) return `${words.prefix}_${n}`;
  };
  return (
    <>
      {entries.map(([name, v], i) => {
        const row = rows.ids[i];
        return (
          <div key={row} className="space-y-2 rounded-md bg-grey-50 p-2.5">
            <div className="flex items-end gap-2">
              <div className="min-w-0 flex-1">
                <NameField
                  id={`${id}-${row}-name`}
                  label={words.name(i + 1)}
                  value={name}
                  others={names.filter((x) => x !== name)}
                  onChange={(next) =>
                    onChange(
                      entries.map((x, j) => (j === i ? [next, x[1]] : x)),
                      false,
                    )
                  }
                />
              </div>
              <Button
                variant="ghost"
                className="h-9 px-2"
                aria-label={words.remove(i + 1)}
                onClick={() => {
                  rows.remove(i);
                  onChange(
                    entries.filter((_, j) => j !== i),
                    true,
                  );
                }}
              >
                <X className="size-4" aria-hidden />
              </Button>
            </div>
            <CelField
              id={`${id}-${row}`}
              label={words.value(i + 1)}
              value={argText(v)}
              options={options}
              onChange={(next, record) =>
                onChange(
                  entries.map((x, j) => (j === i ? [x[0], next] : x)),
                  record,
                )
              }
            />
          </div>
        );
      })}
      <Button variant="secondary" className="h-8" onClick={() => onChange([...entries, [freeName(), ""]], true)}>
        <Plus className="size-4" aria-hidden />
        {words.add}
      </Button>
    </>
  );
}

/**
 * A key's name, committed when the field is left or on Enter: renaming on every keystroke would move the value to
 * a new key each time, and a name passed through on the way could be another row's and merge the two. A name in
 * use is refused.
 */
function NameField({
  id,
  label,
  value,
  others,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  others: string[];
  onChange: (next: string) => void;
}) {
  const t = useTranslations("studioFields");
  const [draft, setDraft] = useState(value);
  const [seen, setSeen] = useState(value);
  const [taken, setTaken] = useState(false);
  if (seen !== value) {
    // The name changed from outside the field (a commit, an undo): show it as it now is.
    setSeen(value);
    setDraft(value);
    setTaken(false);
  }
  const commit = () => {
    const next = draft.trim();
    if (!next || next === value) {
      setDraft(value);
      return;
    }
    if (others.includes(next)) {
      setTaken(true);
      return;
    }
    onChange(next);
  };
  const error = `${id}-error`;
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>
      <input
        id={id}
        className={`${FIELD_CLASS} h-9 font-mono text-[13px]`}
        value={draft}
        aria-invalid={taken || undefined}
        aria-describedby={taken ? error : undefined}
        onChange={(e) => {
          setDraft(e.target.value);
          setTaken(false);
        }}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
        }}
      />
      {taken ? (
        <p id={error} role="alert" className="mt-1 text-xs text-blocked">
          {t("nameTaken")}
        </p>
      ) : null}
    </div>
  );
}

/** Named values, such as an agent step's inputs. */
function MapField({
  id,
  label,
  help,
  value,
  onChange,
  options,
}: {
  id: string;
  label: string;
  help?: string;
  value: Record<string, unknown>;
  onChange: OnValue;
  options: CelOption[];
}) {
  const t = useTranslations("studioFields");
  return (
    <fieldset className="space-y-3 rounded-md border border-rule p-3" aria-describedby={helpId(id, help)}>
      <legend className="px-1 text-sm font-medium">{label}</legend>
      {help ? (
        <p id={helpId(id, help)} className="text-xs text-muted">
          {help}
        </p>
      ) : null}
      <NamedRows
        id={id}
        entries={Object.entries(value)}
        options={options}
        onChange={(next, record) => onChange(Object.fromEntries(next), record)}
        words={{
          name: (n) => t("inputName", { n }),
          value: (n) => t("inputValue", { n }),
          add: t("addInput"),
          remove: (n) => t("removeInput", { n }),
          prefix: "input",
        }}
      />
    </fieldset>
  );
}

/** A list of values, such as a verification step's checks. */
function ListField({
  id,
  label,
  help,
  value,
  onChange,
  options,
}: {
  id: string;
  label: string;
  help?: string;
  value: string[];
  onChange: OnValue;
  options: CelOption[];
}) {
  const t = useTranslations("studioFields");
  return (
    <fieldset className="space-y-3 rounded-md border border-rule p-3" aria-describedby={helpId(id, help)}>
      <legend className="px-1 text-sm font-medium">{label}</legend>
      {help ? (
        <p id={helpId(id, help)} className="text-xs text-muted">
          {help}
        </p>
      ) : null}
      {value.map((v, i) => (
        <div key={i} className="flex items-end gap-2">
          <div className="min-w-0 flex-1">
            <CelField
              id={`${id}-${i}`}
              label={t("itemN", { n: i + 1 })}
              value={v}
              options={options}
              onChange={(next, record) =>
                onChange(
                  value.map((x, j) => (j === i ? next : x)),
                  record,
                )
              }
            />
          </div>
          <Button
            variant="ghost"
            className="mb-6 h-9 px-2"
            aria-label={t("removeItem", { n: i + 1 })}
            onClick={() =>
              onChange(
                value.filter((_, j) => j !== i),
                true,
              )
            }
          >
            <X className="size-4" aria-hidden />
          </Button>
        </div>
      ))}
      <Button variant="secondary" className="h-8" onClick={() => onChange([...value, ""], true)}>
        <Plus className="size-4" aria-hidden />
        {t("addItem")}
      </Button>
    </fieldset>
  );
}
