"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Plus, Trash2 } from "lucide-react";
import { type ReactNode, useId, useState } from "react";
import { Controller, useFieldArray, useForm } from "react-hook-form";
import { z } from "zod";
import { Modal, Select, useToast } from "@/components/base";
import { REASON_MAX } from "@/components/confirm-action";
import { Button } from "@/components/ui";
import { errorText } from "@/lib/api/error-text";
import { cn } from "@/lib/cn";
import { useConnectors } from "@/lib/queries/connectors";
import { useCreatePack } from "@/lib/queries/marketplace";
import { slugify, SLUG_PATTERN } from "./pack-state";

const ACCESS = [
  { value: "read", label: "Read" },
  { value: "write (approval)", label: "Write (approval)" },
  { value: "write", label: "Write" },
] as const;
const RISK = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
] as const;

const required = (what: string, max?: number, label = what) => {
  const base = z.string().trim().min(1, `Enter ${what}.`);
  return max ? base.max(max, `Keep ${label} to ${max} characters or fewer.`) : base;
};

/** The API's bounds for a new pack: Name 120, Slug 60, ShortText 40, Text 1000, at most 20 connectors. */
export const MAX_CONNECTORS = 20;

export const newPackSchema = z.object({
  name: required("a name", 120, "the name"),
  slug: z
    .string()
    .trim()
    .min(1, "Enter a slug.")
    .max(60, "Keep the slug to 60 characters or fewer.")
    .regex(SLUG_PATTERN, "Use lowercase letters and numbers, separated by single hyphens."),
  publisher: required("a publisher", 120, "the publisher"),
  category: required("a category", 40, "the category"),
  riskClass: z.enum(["low", "medium", "high"]),
  outcome: required("the outcome the pack delivers", 1000, "the outcome"),
  description: required("a description", 1000, "the description"),
  humanReview: required("when a person reviews the work", 1000, "the human review note"),
  connectors: z
    .array(
      z.object({
        app: required("an app"),
        access: z.enum(["read", "write (approval)", "write"]),
      }),
    )
    .min(1, "Add at least one connector.")
    .max(MAX_CONNECTORS, `Use ${MAX_CONNECTORS} connectors or fewer.`),
  reason: z
    .string()
    .trim()
    .min(1, "Give a reason. It is recorded in the audit log.")
    .max(REASON_MAX, `Keep the reason to ${REASON_MAX} characters or fewer.`),
});
export type NewPackValues = z.infer<typeof newPackSchema>;

const EMPTY: NewPackValues = {
  name: "",
  slug: "",
  publisher: "",
  category: "",
  riskClass: "medium",
  outcome: "",
  description: "",
  humanReview: "",
  connectors: [{ app: "", access: "read" }],
  reason: "",
};

const INPUT =
  "mt-1.5 block w-full rounded-md border border-grey-300 bg-paper px-3 text-sm outline-none focus:border-ink aria-[invalid]:border-blocked";

function Field({
  label,
  htmlFor,
  error,
  hint,
  className,
  children,
}: {
  label: string;
  htmlFor: string;
  error?: string;
  hint?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("text-sm", className)}>
      <label htmlFor={htmlFor} className="font-medium">
        {label}
      </label>
      {children}
      {hint && !error ? <p className="mt-1 text-xs text-muted">{hint}</p> : null}
      {error ? (
        <p role="alert" className="mt-1 text-xs text-blocked">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function NewPackDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const id = useId();
  const toast = useToast();
  const create = useCreatePack();
  const connectors = useConnectors();
  const [apiError, setApiError] = useState<string | null>(null);
  const [slugEdited, setSlugEdited] = useState(false);

  const form = useForm<NewPackValues>({
    resolver: zodResolver(newPackSchema),
    defaultValues: EMPTY,
    shouldFocusError: true,
  });
  const { register, control, setValue, formState } = form;
  const { errors, isSubmitting } = formState;
  const rows = useFieldArray({ control, name: "connectors" });
  const appNames = connectors.data?.map((c) => c.app) ?? [];

  const close = (next: boolean) => {
    if (isSubmitting) return;
    onOpenChange(next);
    if (!next) {
      form.reset(EMPTY);
      setApiError(null);
      setSlugEdited(false);
    }
  };

  const submit = form.handleSubmit(async (values) => {
    setApiError(null);
    try {
      await create.mutateAsync({ body: values });
      toast(`${values.name} created as a draft`);
      close(false);
    } catch (e) {
      setApiError(errorText(e));
    }
  });

  const nameField = register("name");

  return (
    <Modal
      open={open}
      onOpenChange={close}
      title="New pack"
      description="Creates a draft listing. It stays hidden from tenants until it is submitted and approved."
      className="max-h-[calc(100dvh-2rem)] w-[min(640px,calc(100vw-2rem))] overflow-y-auto"
    >
      <form onSubmit={submit} noValidate className="mt-4 grid gap-4 sm:grid-cols-2">
        <Field label="Name" htmlFor={`${id}-name`} error={errors.name?.message}>
          <input
            id={`${id}-name`}
            className={cn(INPUT, "h-9")}
            aria-invalid={errors.name ? true : undefined}
            {...nameField}
            onChange={(e) => {
              void nameField.onChange(e);
              if (!slugEdited) setValue("slug", slugify(e.target.value), { shouldValidate: formState.isSubmitted });
            }}
          />
        </Field>
        <Field
          label="Slug"
          htmlFor={`${id}-slug`}
          error={errors.slug?.message}
          hint="Filled from the name until you edit it."
        >
          <input
            id={`${id}-slug`}
            className={cn(INPUT, "h-9 font-mono")}
            aria-invalid={errors.slug ? true : undefined}
            {...register("slug", { onChange: () => setSlugEdited(true) })}
          />
        </Field>
        <Field label="Publisher" htmlFor={`${id}-publisher`} error={errors.publisher?.message}>
          <input
            id={`${id}-publisher`}
            className={cn(INPUT, "h-9")}
            aria-invalid={errors.publisher ? true : undefined}
            {...register("publisher")}
          />
        </Field>
        <Field label="Category" htmlFor={`${id}-category`} error={errors.category?.message}>
          <input
            id={`${id}-category`}
            className={cn(INPUT, "h-9")}
            aria-invalid={errors.category ? true : undefined}
            placeholder="Finance, Support, Logistics"
            {...register("category")}
          />
        </Field>
        <Field label="Risk class" htmlFor={`${id}-risk`}>
          <Controller
            control={control}
            name="riskClass"
            render={({ field }) => (
              <Select
                id={`${id}-risk`}
                label="Risk class"
                value={field.value}
                onValueChange={field.onChange}
                items={[...RISK]}
                className="mt-1.5 w-full"
              />
            )}
          />
        </Field>
        <Field label="Outcome" htmlFor={`${id}-outcome`} error={errors.outcome?.message} className="sm:col-span-2">
          <input
            id={`${id}-outcome`}
            className={cn(INPUT, "h-9")}
            aria-invalid={errors.outcome ? true : undefined}
            placeholder="Every refund request is answered within one business day"
            {...register("outcome")}
          />
        </Field>
        <Field
          label="Description"
          htmlFor={`${id}-description`}
          error={errors.description?.message}
          className="sm:col-span-2"
        >
          <textarea
            id={`${id}-description`}
            rows={3}
            className={cn(INPUT, "resize-y py-2")}
            aria-invalid={errors.description ? true : undefined}
            {...register("description")}
          />
        </Field>
        <Field
          label="Human review"
          htmlFor={`${id}-review`}
          error={errors.humanReview?.message}
          hint="When a person checks the work before it is final."
          className="sm:col-span-2"
        >
          <input
            id={`${id}-review`}
            className={cn(INPUT, "h-9")}
            aria-invalid={errors.humanReview ? true : undefined}
            {...register("humanReview")}
          />
        </Field>

        <fieldset className="sm:col-span-2">
          <legend className="text-sm font-medium">Connectors</legend>
          <ul className="mt-1.5 space-y-2">
            {rows.fields.map((row, i) => (
              <li key={row.id} className="grid grid-cols-[1fr_auto] gap-2 sm:grid-cols-[1fr_11rem_auto]">
                <div className="min-w-0">
                  <input
                    aria-label={`Connector ${i + 1} app`}
                    list={`${id}-apps`}
                    placeholder="App, for example Gmail"
                    className={cn(INPUT, "mt-0 h-9")}
                    aria-invalid={errors.connectors?.[i]?.app ? true : undefined}
                    {...register(`connectors.${i}.app`)}
                  />
                  {errors.connectors?.[i]?.app ? (
                    <p role="alert" className="mt-1 text-xs text-blocked">
                      {errors.connectors[i]?.app?.message}
                    </p>
                  ) : null}
                </div>
                <Controller
                  control={control}
                  name={`connectors.${i}.access`}
                  render={({ field }) => (
                    <Select
                      label={`Connector ${i + 1} access`}
                      value={field.value}
                      onValueChange={field.onChange}
                      items={[...ACCESS]}
                      className="col-span-2 row-start-2 w-full sm:col-span-1 sm:row-start-auto"
                    />
                  )}
                />
                <Button
                  variant="ghost"
                  aria-label={`Remove connector ${i + 1}`}
                  disabled={rows.fields.length === 1}
                  onClick={() => rows.remove(i)}
                  className="col-start-2 row-start-1 px-2.5 sm:col-start-auto sm:row-start-auto"
                >
                  <Trash2 className="size-4" aria-hidden />
                </Button>
              </li>
            ))}
          </ul>
          <datalist id={`${id}-apps`}>
            {appNames.map((a) => (
              <option key={a} value={a} />
            ))}
          </datalist>
          {typeof errors.connectors?.message === "string" ? (
            <p role="alert" className="mt-1 text-xs text-blocked">
              {errors.connectors.message}
            </p>
          ) : null}
          <Button
            variant="secondary"
            className="mt-2"
            disabled={rows.fields.length >= MAX_CONNECTORS}
            onClick={() => rows.append({ app: "", access: "read" })}
          >
            <Plus className="size-4" aria-hidden />
            Add a connector
          </Button>
        </fieldset>

        <Field
          label="Reason"
          htmlFor={`${id}-reason`}
          error={errors.reason?.message}
          hint="Recorded in the audit log with your email."
          className="sm:col-span-2"
        >
          <textarea
            id={`${id}-reason`}
            rows={2}
            className={cn(INPUT, "resize-y py-2")}
            aria-invalid={errors.reason ? true : undefined}
            placeholder="Partner onboarding request from the publisher"
            {...register("reason")}
          />
        </Field>

        {apiError ? (
          <p
            role="alert"
            className="rounded-md border border-blocked/30 bg-blocked-soft/60 px-3 py-2 text-sm text-blocked sm:col-span-2"
          >
            {apiError}
          </p>
        ) : null}
        <div className="flex flex-wrap justify-end gap-2 sm:col-span-2">
          <Button variant="ghost" disabled={isSubmitting} onClick={() => close(false)}>
            Cancel
          </Button>
          <Button type="submit" disabled={isSubmitting} aria-busy={isSubmitting || undefined}>
            Create pack
          </Button>
        </div>
      </form>
    </Modal>
  );
}
