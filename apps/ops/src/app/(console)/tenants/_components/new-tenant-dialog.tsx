"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { type ReactNode, useEffect, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";
import { Modal, Select, useToast } from "@/components/base";
import { REASON_MAX } from "@/components/confirm-action";
import { Button } from "@/components/ui";
import { errorText } from "@/lib/api/error-text";
import { cn } from "@/lib/cn";
import { DOLLARS_HINT, parseDollarsToMinor } from "@/lib/money";
import { useCreateTenant } from "@/lib/queries/tenants";

const PLANS = ["Starter", "Pro", "Enterprise"] as const;

/** Mirrors the API's bounds: country is two capitals, trial 1 to 90 days, the cap is entered in dollars. */
export const newTenantSchema = z.object({
  name: z.string().trim().min(1, "Enter the company name.").max(120, "Keep the name to 120 characters or fewer."),
  short: z.string().trim().min(1, "Enter a short name.").max(40, "Keep the short name to 40 characters or fewer."),
  plan: z.enum(PLANS),
  region: z.string().trim().min(1, "Enter a region, for example us-central1."),
  country: z.string().regex(/^[A-Z]{2}$/, "Use a two-letter country code in capitals, for example US."),
  ownerEmail: z.email("Enter a valid email address for the owner."),
  monthlyCapDollars: z.string().refine((v) => parseDollarsToMinor(v) !== null, DOLLARS_HINT),
  trialDays: z
    .string()
    .trim()
    .refine((v) => /^\d+$/.test(v) && Number(v) >= 1 && Number(v) <= 90, "Trial length is 1 to 90 days."),
  reason: z
    .string()
    .trim()
    .min(1, "Give a reason. It is recorded in the audit log.")
    .max(REASON_MAX, `Keep the reason to ${REASON_MAX} characters or fewer.`),
});
export type NewTenantValues = z.infer<typeof newTenantSchema>;

const DEFAULTS: NewTenantValues = {
  name: "",
  short: "",
  plan: "Starter",
  region: "us-central1",
  country: "US",
  ownerEmail: "",
  monthlyCapDollars: "500",
  trialDays: "14",
  reason: "",
};

/** Fields that render a hint line when valid. Keep in step with the `hint` props below. */
const HINTED = new Set<keyof NewTenantValues>(["short", "monthlyCapDollars", "country", "trialDays"]);

const INPUT =
  "h-9 w-full rounded-md border border-rule bg-paper px-3 text-sm text-ink placeholder:text-grey-500 hover:border-grey-300 focus:border-grey-500 aria-[invalid=true]:border-blocked";

function Field({
  id,
  label,
  error,
  hint,
  className,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  hint?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={className}>
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <div className="mt-1">{children}</div>
      {hint && !error ? (
        <p id={`${id}-hint`} className="mt-1 text-xs text-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={`${id}-error`} role="alert" className="mt-1 text-xs text-blocked">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function NewTenantDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const toast = useToast();
  const create = useCreateTenant();
  const [apiError, setApiError] = useState<string | null>(null);
  const form = useForm<NewTenantValues>({
    resolver: zodResolver(newTenantSchema),
    defaultValues: DEFAULTS,
  });
  const { register, control, handleSubmit, reset, formState } = form;
  const { errors, isSubmitting } = formState;

  // Start every opening from a clean form, so nothing resets while the close animation plays.
  useEffect(() => {
    if (open) {
      reset(DEFAULTS);
    }
  }, [open, reset]);

  const close = (next: boolean) => {
    if (isSubmitting) return;
    onOpenChange(next);
    if (!next) setApiError(null);
  };

  const submit = handleSubmit(async (v) => {
    setApiError(null);
    try {
      const t = await create.mutateAsync({
        body: {
          name: v.name,
          short: v.short,
          plan: v.plan,
          region: v.region,
          country: v.country,
          ownerEmail: v.ownerEmail,
          monthlyCapMinor: parseDollarsToMinor(v.monthlyCapDollars) ?? 0,
          trialDays: Number(v.trialDays),
          reason: v.reason,
        },
      });
      toast("Tenant created", `${t.name} is on a ${v.trialDays}-day trial.`);
      close(false);
    } catch (e) {
      setApiError(errorText(e));
    }
  });

  // Only name a hint when that field renders one, so aria-describedby never points at a missing id.
  const inv = (k: keyof NewTenantValues) => {
    const describedBy = errors[k] ? `nt-${k}-error` : HINTED.has(k) ? `nt-${k}-hint` : undefined;
    return { "aria-invalid": errors[k] ? (true as const) : undefined, "aria-describedby": describedBy };
  };

  return (
    <Modal
      open={open}
      onOpenChange={close}
      title="New tenant"
      description="Creates a workspace on a trial and adds the owner as a pending member."
      className="max-h-[calc(100dvh-2rem)] w-[min(640px,calc(100vw-2rem))] overflow-y-auto"
    >
      <form onSubmit={submit} noValidate className="mt-4 grid grid-cols-1 gap-x-4 gap-y-3.5 sm:grid-cols-2">
        <Field id="nt-name" label="Company name" error={errors.name?.message}>
          <input id="nt-name" className={INPUT} autoComplete="off" {...register("name")} {...inv("name")} />
        </Field>
        <Field id="nt-short" label="Short name" error={errors.short?.message} hint="Shown in tight spaces.">
          <input id="nt-short" className={INPUT} autoComplete="off" {...register("short")} {...inv("short")} />
        </Field>
        <Field id="nt-ownerEmail" label="Owner email" error={errors.ownerEmail?.message} className="sm:col-span-2">
          <input
            id="nt-ownerEmail"
            type="email"
            className={INPUT}
            autoComplete="off"
            {...register("ownerEmail")}
            {...inv("ownerEmail")}
          />
        </Field>
        <Field id="nt-plan" label="Plan">
          <Controller
            control={control}
            name="plan"
            render={({ field }) => (
              <Select
                id="nt-plan"
                label="Plan"
                className="w-full"
                value={field.value}
                onValueChange={field.onChange}
                items={PLANS.map((p) => ({ value: p, label: p }))}
              />
            )}
          />
        </Field>
        <Field
          id="nt-monthlyCapDollars"
          label="Monthly spend cap (USD)"
          error={errors.monthlyCapDollars?.message}
          hint="Runs stop at the cap."
        >
          <input
            id="nt-monthlyCapDollars"
            inputMode="decimal"
            className={cn(INPUT, "tnum")}
            {...register("monthlyCapDollars")}
            {...inv("monthlyCapDollars")}
          />
        </Field>
        <Field id="nt-region" label="Region" error={errors.region?.message}>
          <input id="nt-region" className={INPUT} {...register("region")} {...inv("region")} />
        </Field>
        <Field id="nt-country" label="Country" error={errors.country?.message} hint="Two-letter code, such as US.">
          <input
            id="nt-country"
            maxLength={2}
            className={cn(INPUT, "uppercase")}
            {...register("country", { setValueAs: (v: string) => v.trim().toUpperCase() })}
            {...inv("country")}
          />
        </Field>
        <Field id="nt-trialDays" label="Trial length (days)" error={errors.trialDays?.message} hint="1 to 90 days.">
          <input
            id="nt-trialDays"
            inputMode="numeric"
            className={cn(INPUT, "tnum")}
            {...register("trialDays")}
            {...inv("trialDays")}
          />
        </Field>
        <Field id="nt-reason" label="Reason" error={errors.reason?.message} className="sm:col-span-2">
          <textarea
            id="nt-reason"
            rows={2}
            placeholder="Signed order form from the sales team, ticket 4821"
            className={cn(INPUT, "h-auto py-2")}
            {...register("reason")}
            {...inv("reason")}
          />
        </Field>
        {apiError ? (
          <p role="alert" className="text-sm text-blocked sm:col-span-2">
            {apiError}
          </p>
        ) : null}
        <div className="flex justify-end gap-2 pt-1 sm:col-span-2">
          <Button variant="ghost" disabled={isSubmitting} onClick={() => close(false)}>
            Cancel
          </Button>
          <Button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Creating tenant…" : "Create tenant"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
