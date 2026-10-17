"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { Controller, type FieldErrors, type Resolver, get, useForm, useWatch } from "react-hook-form";
import { z } from "zod";
import { Checkbox, Choices, Select, useToast } from "@/components/base";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Button, ButtonLink, Callout, SimTag } from "@/components/ui";
import { type ApiError, type ApiIssue, toApiError } from "@/lib/api/errors";
import { useErrorText } from "@/lib/api/use-error-text";
import { usePack } from "@/lib/queries/catalog";
import { useStartRun } from "@/lib/queries/runs";
import {
  MIN_RUN_BUDGET,
  budgetChoices,
  budgetLimit,
  defaultBudget as defaultRunBudget,
  packRunFee,
} from "@/lib/run-budget";
import { useNow } from "@/lib/clock";
import { businessDay } from "@/lib/format";
import type { Money } from "@/lib/types";
import { useFormat } from "@/lib/use-format";
import { createIdempotencyKeys, isDefiniteRejection } from "./idempotency";
import {
  type InputField,
  type InputValues,
  buildInput,
  fieldForIssue,
  inputFields,
  validateInput,
} from "./input-schema";

/** The budget a run of `pack` starts with (see run-budget: never above what the API accepts). */
export const defaultBudget = (pack?: StartablePack) => defaultRunBudget(pack ?? {});

/** Translates a validation message. Pass `useTranslations("forms.startRun")` (or any function with these keys). */
export type ValidationText = (key: "choosePack" | "needInput" | "noteTooLong") => string;

export const makeStartRunSchema = (t: ValidationText) =>
  z.object({
    packSlug: z.string().min(1, t("choosePack")),
    input: z.string().min(1, t("needInput")),
    budgetMinor: z.number().int().positive(),
    note: z.string().max(500, t("noteTooLong")),
  });

/** What the form holds: the free-text `input` for packs without an input schema, `fields` for the rest. */
export type StartRunValues = z.infer<ReturnType<typeof makeStartRunSchema>> & { fields?: InputValues };
/** What the form submits: `input` is an object built from the pack's input schema, or the free text. */
export type StartRunBody = {
  packSlug: string;
  input: string | Record<string, unknown>;
  budgetMinor: number;
  note: string;
};
export type StartablePack = {
  slug: string;
  name: string;
  inputs: string[];
  /** The spending cap per run chosen when the pack was hired (live workspaces). */
  perRunCap?: Money;
  /** The most one run may be given (the pack's maximum). */
  maxBudget?: Money;
  /** Another workspace's fee per run, paid up front within the per-run cap. */
  packFee?: Money;
  /** The most a run may be given now, as the API works it out for an added pack. */
  runBudgetLimit?: Money;
};

/** Why a run can't start, and the page that fixes it. `text` is shown as given. */
export type Refusal = { text: string; href?: string; action?: string };

/** Puts field errors (by dotted name) under `fields`, the shape react-hook-form reads them in. */
function nestErrors(errors: Record<string, string>): FieldErrors {
  const out: Record<string, unknown> = {};
  for (const [name, message] of Object.entries(errors)) {
    const path = name.split(".");
    let node = out;
    for (const k of path.slice(0, -1)) node = (node[k] ??= {}) as Record<string, unknown>;
    node[path[path.length - 1]] = { type: "validate", message };
  }
  return out as FieldErrors;
}

function useResolver(fields: InputField[] | null): Resolver<StartRunValues> {
  const validation = useTranslations("forms.startRun");
  return useMemo(() => {
    const base = makeStartRunSchema(validation);
    const check = zodResolver(fields ? base.omit({ input: true }) : base, undefined, { raw: true });
    const messages = {
      required: (label: string) => validation("required", { label }),
      number: validation("number"),
      integer: validation("integer"),
      date: validation("date"),
      pattern: validation("pattern"),
      json: validation("json"),
    };
    return async (values, context, options) => {
      const result = await check(values, context, options as never);
      const fieldErrors = fields ? validateInput(fields, values.fields, messages) : {};
      if (Object.keys(fieldErrors).length === 0) return result as never;
      return {
        values: {},
        errors: { ...result.errors, fields: nestErrors(fieldErrors) } as FieldErrors<StartRunValues>,
      };
    };
  }, [fields, validation]);
}

const INPUT_CLASS =
  "mt-1.5 h-10 w-full rounded-md border border-grey-300 px-3 text-sm outline-none focus:border-ink aria-[invalid=true]:border-blocked";

/** One field of a pack's input schema. Unmounting it (another pack) drops its value. */
function SchemaField({
  field: f,
  control,
  error,
}: {
  field: InputField;
  control: ReturnType<typeof useForm<StartRunValues>>["control"];
  error?: string;
}) {
  const t = useTranslations("runs.new");
  const id = `run-field-${f.name}`;
  const errorId = `${id}-error`;
  const helpId = `${id}-help`;
  const describedBy = [error ? errorId : null, f.description ? helpId : null].filter(Boolean).join(" ") || undefined;
  // A required field of an optional object is marked by its object's legend instead.
  const optional = !f.required && !f.requiredInGroup;
  const caption = (
    <>
      {f.label}
      {optional ? <span className="font-normal text-muted"> {t("optional")}</span> : null}
    </>
  );
  // An optional choice with no default can be cleared again.
  const options = (f.options ?? []).map((o) => ({ value: o, label: o }));
  const choices = !f.required && f.initial === "" ? [{ value: "", label: t("noChoice") }, ...options] : options;
  return (
    <Controller
      control={control}
      name={`fields.${f.name}` as "fields"}
      defaultValue={f.initial as never}
      shouldUnregister
      render={({ field }) => (
        <div>
          {f.kind === "boolean" ? (
            <Checkbox
              checked={field.value === (true as never)}
              onCheckedChange={field.onChange}
              describedBy={describedBy}
              invalid={!!error}
            >
              {caption}
            </Checkbox>
          ) : (
            <>
              <label htmlFor={id} className="block text-sm font-medium">
                {caption}
              </label>
              {f.kind === "enum" ? (
                <div className="mt-1.5">
                  <Select
                    id={id}
                    label={f.label}
                    describedBy={describedBy}
                    invalid={!!error}
                    value={String(field.value ?? "")}
                    onValueChange={field.onChange}
                    items={choices}
                  />
                </div>
              ) : f.kind === "json" ? (
                <textarea
                  id={id}
                  name={field.name}
                  value={String(field.value ?? "")}
                  onChange={field.onChange}
                  onBlur={field.onBlur}
                  ref={field.ref}
                  rows={3}
                  aria-invalid={error ? true : undefined}
                  aria-describedby={describedBy}
                  className="mt-1.5 w-full rounded-md border border-grey-300 px-3 py-2 font-mono text-[13px] outline-none focus:border-ink"
                />
              ) : (
                <input
                  id={id}
                  name={field.name}
                  // Numbers are typed as text so a bad entry reaches the check and gets an error, instead of
                  // a number input quietly reporting it as empty.
                  type={f.kind === "date" ? "date" : "text"}
                  inputMode={f.kind === "integer" ? "numeric" : f.kind === "number" ? "decimal" : undefined}
                  value={String(field.value ?? "")}
                  onChange={field.onChange}
                  onBlur={field.onBlur}
                  ref={field.ref}
                  aria-invalid={error ? true : undefined}
                  aria-describedby={describedBy}
                  className={INPUT_CLASS}
                />
              )}
            </>
          )}
          {f.description ? (
            <p id={helpId} className="mt-1 text-xs text-muted">
              {f.description}
            </p>
          ) : null}
          {error ? (
            <p id={errorId} role="alert" className="mt-1 text-xs text-blocked">
              {error}
            </p>
          ) : null}
        </div>
      )}
    />
  );
}

/** The schema's fields, grouped one level deep the way the schema nests them. */
function SchemaFields({
  fields,
  control,
  errors,
}: {
  fields: InputField[];
  control: ReturnType<typeof useForm<StartRunValues>>["control"];
  errors: FieldErrors<StartRunValues>;
}) {
  const t = useTranslations("runs.new");
  if (fields.length === 0) return <p className="text-sm text-muted">{t("noInputNeeded")}</p>;
  const groups: { group?: string; fields: InputField[] }[] = [];
  for (const f of fields) {
    const last = groups[groups.length - 1];
    if (last && f.group && last.group === f.group) last.fields.push(f);
    else groups.push({ group: f.group, fields: [f] });
  }
  const errorOf = (f: InputField) => get(errors, `fields.${f.name}`)?.message as string | undefined;
  return (
    <div className="space-y-4">
      {groups.map((g, i) =>
        g.group ? (
          <fieldset key={`${g.group}-${i}`} className="space-y-4 rounded-md border border-rule px-4 pt-2 pb-4">
            <legend className="px-1 text-sm font-medium">
              {g.group}
              {g.fields[0]?.groupRequired === false ? (
                <span className="font-normal text-muted"> {t("optional")}</span>
              ) : null}
            </legend>
            {g.fields.map((f) => (
              <SchemaField key={f.name} field={f} control={control} error={errorOf(f)} />
            ))}
          </fieldset>
        ) : (
          g.fields.map((f) => <SchemaField key={f.name} field={f} control={control} error={errorOf(f)} />)
        ),
      )}
    </div>
  );
}

export function StartRunFields({
  packs,
  defaultPack,
  onSubmit,
  pending,
  schema,
  schemaPending = false,
  onPackChange,
  refusal,
  refusalBlocks = false,
  issues,
}: {
  packs: StartablePack[];
  defaultPack?: string;
  onSubmit: (v: StartRunBody) => void;
  pending: boolean;
  /** The selected pack's input JSON Schema; without one the pack takes the free-text input. */
  schema?: unknown;
  schemaPending?: boolean;
  onPackChange?: (slug: string) => void;
  /** Why the selected pack can't start a run now, with the page that fixes it. */
  refusal?: Refusal | null;
  /** True when the refusal is known before submitting (nothing to retry until it is fixed). */
  refusalBlocks?: boolean;
  /** Field errors from the API (422), placed on their fields. */
  issues?: ApiIssue[];
}) {
  const t = useTranslations("runs.new");
  const { money } = useFormat();
  const first = packs.find((p) => p.slug === defaultPack) ?? packs[0];
  const today = businessDay(useNow());
  const fields = useMemo(() => inputFields(schema, today), [schema, today]);
  const form = useForm<StartRunValues>({
    resolver: useResolver(fields),
    shouldFocusError: true,
    defaultValues: {
      packSlug: first?.slug ?? "",
      input: first?.inputs[0] ?? "",
      budgetMinor: defaultBudget(first),
      note: "",
    },
  });
  const selectedSlug = useWatch({ control: form.control, name: "packSlug" });
  const pack = packs.find((p) => p.slug === selectedSlug);
  const { errors, isSubmitted } = form.formState;
  const budgets = budgetChoices(pack ?? {});
  // The fee leaves too little of the per-run cap for any budget the API would accept: say so, offer nothing.
  const noRoom = !!pack && budgets.length === 0;
  const budgetKey = budgets.join(",");
  const fallback = pack && budgets.length ? defaultBudget(pack) : undefined;
  // A limit learned after the form opened (the pack's detail) can rule out the chosen budget: move to the default.
  useEffect(() => {
    if (fallback === undefined || budgetKey.split(",").map(Number).includes(form.getValues("budgetMinor"))) return;
    form.setValue("budgetMinor", fallback);
  }, [budgetKey, fallback, form]);
  // The pack's defaults fill its fields when they arrive and again when they change (the detail read again, the
  // business day moved on), but only the fields nobody has touched: what was typed stays.
  useEffect(() => {
    if (!fields) return;
    for (const f of fields) {
      const name = `fields.${f.name}` as "fields";
      const { isDirty, isTouched } = form.getFieldState(name, form.formState);
      if (!isDirty && !isTouched) form.resetField(name, { defaultValue: f.initial as never });
    }
  }, [fields, form]);

  // Without a schema, the API's input errors belong to the free-text input when it is on screen.
  const onInput = !fields && !!pack?.inputs.length;
  // The API's field errors land on the fields they name; the rest are listed above the button, once.
  const unplaced = useMemo(() => {
    if (!issues?.length || onInput) return [];
    return issues.filter((i) => !(fields ? fieldForIssue(fields, i.path) : null));
  }, [issues, fields, onInput]);
  useEffect(() => {
    if (!issues?.length) return;
    if (onInput) {
      const message = issues.map((i) => i.message).join(" ");
      form.setError("input", { type: "server", message }, { shouldFocus: true });
      return;
    }
    let focused = false;
    for (const issue of issues) {
      const f = fields ? fieldForIssue(fields, issue.path) : undefined;
      if (!f) continue;
      form.setError(
        `fields.${f.name}` as "fields",
        { type: "server", message: issue.message },
        { shouldFocus: !focused },
      );
      focused = true;
    }
  }, [issues, fields, form, onInput]);

  const submit = form.handleSubmit((v) => {
    const input = fields ? buildInput(fields, v.fields) : v.input;
    onSubmit({ packSlug: v.packSlug, input, budgetMinor: v.budgetMinor, note: v.note });
  });

  return (
    <form onSubmit={submit} className="space-y-6" noValidate>
      <Controller
        control={form.control}
        name="packSlug"
        render={({ field }) => (
          <div>
            <label htmlFor="run-pack" className="mb-1.5 block text-sm font-medium">
              {t("pack")}
            </label>
            <Select
              id="run-pack"
              describedBy={errors.packSlug ? "run-pack-error" : undefined}
              invalid={!!errors.packSlug}
              label={t("pack")}
              value={field.value}
              onValueChange={(v) => {
                field.onChange(v);
                onPackChange?.(v);
                const next = packs.find((p) => p.slug === v);
                form.setValue("input", next?.inputs[0] ?? "", { shouldValidate: isSubmitted });
                form.setValue("budgetMinor", defaultBudget(next));
              }}
              items={packs.map((p) => ({ value: p.slug, label: p.name }))}
            />
            {errors.packSlug ? (
              <p id="run-pack-error" role="alert" className="mt-1 text-xs text-blocked">
                {errors.packSlug.message}
              </p>
            ) : null}
          </div>
        )}
      />
      {schemaPending ? (
        <Skeleton className="h-20" />
      ) : fields ? (
        <fieldset>
          <legend className="mb-1.5 text-sm font-medium">{t("input")}</legend>
          <SchemaFields key={selectedSlug} fields={fields} control={form.control} errors={errors} />
        </fieldset>
      ) : (
        <Controller
          control={form.control}
          name="input"
          render={({ field }) => (
            <div>
              <label htmlFor="run-input" className="mb-1.5 block text-sm font-medium">
                {t("input")}
              </label>
              {pack?.inputs.length ? (
                <Select
                  id="run-input"
                  describedBy={errors.input ? "run-input-error" : undefined}
                  invalid={!!errors.input}
                  label={t("input")}
                  value={field.value}
                  onValueChange={field.onChange}
                  items={pack.inputs.map((i) => ({ value: i, label: i }))}
                />
              ) : (
                <p id="run-input" className="text-sm text-grey-700">
                  {t("needInput")}{" "}
                  <Link href="/app/connections" className="link">
                    {t("goConnections")}
                  </Link>
                </p>
              )}
              {errors.input && pack?.inputs.length ? (
                <p id="run-input-error" role="alert" className="mt-1 text-xs text-blocked">
                  {errors.input.message}
                </p>
              ) : null}
            </div>
          )}
        />
      )}
      <Controller
        control={form.control}
        name="budgetMinor"
        render={({ field }) => (
          <fieldset>
            <legend className="mb-1.5 text-sm font-medium">{t("budget")}</legend>
            {noRoom && pack?.perRunCap ? (
              <Callout
                tone="warn"
                title={
                  <>
                    {t("noRoom", {
                      fee: money(pack.packFee ?? 0),
                      cap: money(pack.perRunCap),
                      min: money(MIN_RUN_BUDGET),
                    })}{" "}
                    <SimTag />
                  </>
                }
                action={
                  <ButtonLink
                    href={`/app/marketplace/${pack.slug}/install`}
                    variant="secondary"
                    className="h-8 shrink-0"
                  >
                    {t("changeCap")}
                  </ButtonLink>
                }
              />
            ) : (
              <Choices
                label={t("budget")}
                layout="row"
                value={String(field.value)}
                onValueChange={(v) => field.onChange(Number(v))}
                options={budgets.map((b) => ({ value: String(b), label: money(b) }))}
              />
            )}
            {pack?.maxBudget && budgetLimit(pack) === pack.maxBudget.amountMinor ? (
              <p className="mt-1.5 text-xs text-muted">{t("maxBudget", { max: money(pack.maxBudget) })}</p>
            ) : null}
            {pack?.perRunCap && !noRoom ? (
              <p className="mt-1.5 text-xs text-muted">
                {pack.packFee
                  ? t("perRunCapWithFee", { cap: money(pack.perRunCap), fee: money(pack.packFee) })
                  : t("perRunCap", { cap: money(pack.perRunCap) })}{" "}
                {pack.packFee ? (
                  <>
                    <SimTag />{" "}
                  </>
                ) : null}
                <Link href={`/app/marketplace/${pack.slug}/install`} className="link">
                  {t("changeCap")}
                </Link>
              </p>
            ) : null}
          </fieldset>
        )}
      />
      <div className="text-sm">
        <label htmlFor="run-note" className="font-medium">
          {t("note")}
        </label>
        <textarea
          id="run-note"
          {...form.register("note")}
          rows={3}
          aria-invalid={errors.note ? true : undefined}
          aria-describedby={errors.note ? "run-note-error" : undefined}
          className="mt-1.5 w-full rounded-md border border-grey-300 px-3 py-2 text-sm outline-none focus:border-ink"
        />
        {errors.note ? (
          <p id="run-note-error" role="alert" className="mt-1 text-xs text-blocked">
            {errors.note.message}
          </p>
        ) : null}
      </div>
      {unplaced.length ? (
        <ul role="alert" className="space-y-1 text-xs text-blocked">
          {unplaced.map((i) => (
            <li key={`${i.path}-${i.message}`}>{i.path ? `${i.path}: ${i.message}` : i.message}</li>
          ))}
        </ul>
      ) : null}
      {refusal ? (
        <Callout
          tone="warn"
          title={refusal.text}
          action={
            refusal.href && refusal.action ? (
              <ButtonLink href={refusal.href} variant="secondary" className="h-8 shrink-0">
                {refusal.action}
              </ButtonLink>
            ) : null
          }
        />
      ) : null}
      <Button
        type="submit"
        className="h-10"
        disabled={pending || schemaPending || noRoom || (!!refusal && refusalBlocks)}
      >
        {pending ? t("starting") : t("start")}
      </Button>
    </form>
  );
}

type RefusalKey = "hireThis" | "goConnections" | "seeUsage" | "changeCap" | "budgetTooHigh" | "budgetRequired";

/**
 * A start refused by the API, with the page that fixes it; null for errors a toast should report. `max` is the
 * pack's maximum budget, formatted, when it is known: a budget over it is refused (BUDGET_TOO_HIGH).
 */
export function refusalFor(
  e: ApiError,
  slug: string,
  t: (key: RefusalKey, values?: Record<string, string>) => string,
  max?: string,
): Refusal | null {
  const text = e.detail;
  switch (e.code) {
    case "BUDGET_TOO_HIGH":
      return { text: max ? t("budgetTooHigh", { max }) : text };
    case "BUDGET_REQUIRED":
      return { text: t("budgetRequired") };
    case "PACK_NOT_HIRED":
      return { text, href: `/app/marketplace/${slug}`, action: t("hireThis") };
    case "APPS_NOT_CONNECTED":
      return { text, href: "/app/connections", action: t("goConnections") };
    case "SPEND_CAP":
      return { text, href: "/app/usage", action: t("seeUsage") };
    case "RUN_BUDGET_OVER_CAP":
      return { text, href: `/app/marketplace/${slug}/install`, action: t("changeCap") };
  }
  // Other refusals (a policy, a paused platform): the API's own words, nothing to link.
  if (e.status === 403 || e.status === 409 || e.status === 423) return { text };
  return null;
}

export function StartRunForm({
  packs,
  defaultPack,
  blocked = {},
}: {
  packs: StartablePack[];
  defaultPack?: string;
  /** Packs that can't start a run now (apps not connected, spend cap), by slug. */
  blocked?: Record<string, Refusal | undefined>;
}) {
  const t = useTranslations("runs.new");
  const errorText = useErrorText();
  const router = useRouter();
  const toast = useToast();
  const start = useStartRun();
  const keys = useRef(createIdempotencyKeys());
  const [slug, setSlug] = useState(() => (packs.find((p) => p.slug === defaultPack) ?? packs[0])?.slug ?? "");
  const detail = usePack(slug);
  const [refused, setRefused] = useState<{ slug: string; refusal: Refusal } | null>(null);
  const [issues, setIssues] = useState<ApiIssue[]>([]);
  const serverRefusal = refused?.slug === slug ? refused.refusal : null;
  const refusal = serverRefusal ?? blocked[slug] ?? null;
  const { money } = useFormat();
  // The detail names the pack's maximum where the list may not (the demo workspace's packs that run for real),
  // and the maximum and limit of the version the workspace holds.
  const held = detail.data;
  const withTerms = held
    ? packs.map((p) =>
        p.slug === slug
          ? {
              ...p,
              maxBudget: held.maxBudget ?? p.maxBudget,
              runBudgetLimit: held.runBudgetLimit ?? p.runBudgetLimit,
              packFee: held.runFee ? packRunFee(held) : p.packFee,
            }
          : p,
      )
    : packs;

  // Without the pack's detail there is no input schema to build the form from: report the failure (with
  // its retry) instead of a form whose Start can't send what the pack needs.
  if (slug !== "" && detail.isError && detail.data === undefined)
    return (
      <QueryState query={detail} skeleton={<Skeleton className="h-72" />}>
        {() => null}
      </QueryState>
    );

  return (
    <StartRunFields
      packs={withTerms}
      defaultPack={defaultPack}
      pending={start.isPending}
      schema={detail.data?.inputSchema}
      schemaPending={slug !== "" && detail.isPending}
      onPackChange={(next) => {
        setSlug(next);
        setIssues([]);
      }}
      refusal={refusal}
      refusalBlocks={!serverRefusal && !!blocked[slug]}
      issues={issues}
      onSubmit={(v) => {
        const body = { ...v, note: v.note || undefined };
        setIssues([]);
        setRefused(null);
        start.mutate(
          { body, headers: { "Idempotency-Key": keys.current.keyFor(body) } },
          {
            onSuccess: (run) => router.push(`/app/runs/${run.id}`),
            onError: (e) => {
              const err = toApiError(e);
              if (isDefiniteRejection(err.status)) keys.current.reset();
              if (err.code === "INVALID_INPUT" && err.issues.length) {
                setIssues(err.issues);
                return;
              }
              const max = withTerms.find((p) => p.slug === v.packSlug)?.maxBudget;
              const r = refusalFor(err, v.packSlug, t, max ? money(max) : undefined);
              if (r) setRefused({ slug: v.packSlug, refusal: r });
              else toast(t("failed"), errorText(err), "blocked");
            },
          },
        );
      }}
    />
  );
}
