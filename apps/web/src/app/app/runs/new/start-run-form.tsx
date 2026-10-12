"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { z } from "zod";
import { Choices, Select, useToast } from "@/components/base";
import { Button } from "@/components/ui";
import { toApiError } from "@/lib/api/errors";
import { useErrorText } from "@/lib/api/use-error-text";
import { useStartRun } from "@/lib/queries/runs";
import { useFormat } from "@/lib/use-format";
import { createIdempotencyKeys, isDefiniteRejection } from "./idempotency";

const BUDGETS = [2000, 5000, 10000] as const;

/** Translates a validation message. Pass `useTranslations("forms.startRun")` (or any function with these keys). */
export type ValidationText = (key: "choosePack" | "needInput" | "noteTooLong") => string;

export const makeStartRunSchema = (t: ValidationText) =>
  z.object({
    packSlug: z.string().min(1, t("choosePack")),
    input: z.string().min(1, t("needInput")),
    budgetMinor: z.number().int().positive(),
    note: z.string().max(500, t("noteTooLong")),
  });
export type StartRunValues = z.infer<ReturnType<typeof makeStartRunSchema>>;
export type StartablePack = { slug: string; name: string; inputs: string[] };

export function StartRunFields({
  packs,
  defaultPack,
  onSubmit,
  pending,
}: {
  packs: StartablePack[];
  defaultPack?: string;
  onSubmit: (v: StartRunValues) => void;
  pending: boolean;
}) {
  const t = useTranslations("runs.new");
  const validation = useTranslations("forms.startRun");
  const { money } = useFormat();
  const first = packs.find((p) => p.slug === defaultPack) ?? packs[0];
  const form = useForm<StartRunValues>({
    resolver: zodResolver(makeStartRunSchema(validation)),
    shouldFocusError: true,
    defaultValues: { packSlug: first?.slug ?? "", input: first?.inputs[0] ?? "", budgetMinor: 5000, note: "" },
  });
  const selectedSlug = useWatch({ control: form.control, name: "packSlug" });
  const pack = packs.find((p) => p.slug === selectedSlug);
  const { errors, isSubmitted } = form.formState;

  return (
    <form onSubmit={form.handleSubmit((v) => onSubmit(v))} className="space-y-6" noValidate>
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
                form.setValue("input", packs.find((p) => p.slug === v)?.inputs[0] ?? "", {
                  shouldValidate: isSubmitted,
                });
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
      <Controller
        control={form.control}
        name="budgetMinor"
        render={({ field }) => (
          <fieldset>
            <legend className="mb-1.5 text-sm font-medium">{t("budget")}</legend>
            <Choices
              label={t("budget")}
              layout="row"
              value={String(field.value)}
              onValueChange={(v) => field.onChange(Number(v))}
              options={BUDGETS.map((b) => ({ value: String(b), label: money(b) }))}
            />
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
      <Button type="submit" className="h-10" disabled={pending}>
        {pending ? t("starting") : t("start")}
      </Button>
    </form>
  );
}

export function StartRunForm({ packs, defaultPack }: { packs: StartablePack[]; defaultPack?: string }) {
  const t = useTranslations("runs.new");
  const errorText = useErrorText();
  const router = useRouter();
  const toast = useToast();
  const start = useStartRun();
  const keys = useRef(createIdempotencyKeys());

  return (
    <StartRunFields
      packs={packs}
      defaultPack={defaultPack}
      pending={start.isPending}
      onSubmit={(v) => {
        const body = { ...v, note: v.note || undefined };
        start.mutate(
          { body, headers: { "Idempotency-Key": keys.current.keyFor(body) } },
          {
            onSuccess: (run) => router.push(`/app/runs/${run.id}`),
            onError: (e) => {
              const err = toApiError(e);
              if (isDefiniteRejection(err.status)) keys.current.reset();
              toast(t("failed"), errorText(err), "blocked");
            },
          },
        );
      }}
    />
  );
}
