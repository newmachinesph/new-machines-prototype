"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { Modal, ModalClose } from "@/components/base";
import { Button, ButtonLink, Callout, SimTag } from "@/components/ui";
import { type ApiError, type ApiIssue, toApiError } from "@/lib/api/errors";
import type { InputField } from "@/lib/api/gen/types.gen";
import { useErrorText } from "@/lib/api/use-error-text";
import { useOrgId } from "@/lib/queries/me";
import { useTestStudioPack } from "@/lib/queries/studio";
import { FIELD_CLASS } from "./cel-field";

const CENTS = 100;
/** The most the API takes for a test run's budget (`budget_minor` ≤ 100,000), in the dollars the field uses. */
const MAX_BUDGET = 100_000 / CENTS;

/** Why the API refused to start the test: our words for the codes it documents, its own for the rest. */
type Refusal = { text: string; issues?: string[]; usage?: boolean };

/**
 * Runs the saved version of the pack on sandbox data, then opens the run. The run list and the run page label
 * it a sandbox test. Unsaved changes are not in the saved version, so the button waits until they are saved.
 * Agent spend on a test run counts toward the workspace's monthly cap, and the dialog says so.
 */
export function TestDialog({
  packKey,
  dirty,
  inputFields,
}: {
  packKey?: string;
  dirty: boolean;
  inputFields: InputField[];
}) {
  const t = useTranslations("studioTest");
  const tc = useTranslations("common");
  const router = useRouter();
  const orgId = useOrgId();
  const errorText = useErrorText();
  const test = useTestStudioPack();
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const [budget, setBudget] = useState("");
  const [refusal, setRefusal] = useState<Refusal | null>(null);
  const budgetId = useId();
  const hintId = useId();
  const ready = !!packKey && !dirty;
  // A refusal belongs to the attempt it answered: opening the dialog again starts clean.
  const show = (o: boolean) => {
    if (o) setRefusal(null);
    setOpen(o);
  };

  const refusalFor = (err: ApiError): Refusal => {
    switch (err.code) {
      case "BUDGET_REQUIRED":
        return { text: t("budgetRequired") };
      case "BUDGET_TOO_HIGH":
        // The API's detail names the exact limit.
        return { text: `${t("budgetTooHigh")} ${err.detail}` };
      case "INVALID_INPUT": {
        // The API's detail repeats the first field error, so the list alone shows each error once. The API names
        // the field only in that detail: each error here is named as the form labels it, unless it already is.
        if (!err.issues.length) return { text: err.detail };
        const named = (i: ApiIssue) => {
          const label = inputFields.find((f) => f.name === i.path)?.label;
          if (!label) return i.message;
          // Already named ("As of must be…", "As of: must be…", in any case): not named twice.
          const head = i.message.slice(0, label.length);
          const next = i.message.charAt(label.length);
          const isNamed = head.toLowerCase() === label.toLowerCase() && (next === " " || next === ":");
          return isNamed ? i.message : `${label}: ${i.message}`;
        };
        return { text: t("invalidInput", { n: err.issues.length }), issues: err.issues.map(named) };
      }
      case "SANDBOX_UNAVAILABLE":
        return { text: t("sandboxUnavailable") };
      case "SPEND_CAP":
        return { text: t("spendCap"), usage: true };
      default:
        return { text: errorText(err) };
    }
  };

  const submit = () => {
    if (!orgId || !packKey) return;
    const input = Object.fromEntries(
      inputFields
        .filter((f) => (values[f.name] ?? "") !== "")
        .map((f) => [f.name, f.type === "number" ? Number(values[f.name]) : values[f.name]]),
    );
    const budgetMinor = budget ? Math.round(Number(budget) * CENTS) : undefined;
    setRefusal(null);
    test.mutate(
      { path: { org_id: orgId, key: packKey }, body: { input, ...(budgetMinor ? { budgetMinor } : {}) } },
      {
        onSuccess: (run) => {
          setOpen(false);
          router.push(`/app/runs/${run.id}`);
        },
        onError: (e) => setRefusal(refusalFor(toApiError(e))),
      },
    );
  };

  return (
    <div className="flex items-center gap-2">
      {ready ? null : (
        <span id={hintId} className="text-xs text-muted">
          {packKey ? t("saveChangesFirst") : t("saveFirst")}
        </span>
      )}
      <Modal
        open={open}
        onOpenChange={show}
        trigger={
          <Button variant="secondary" disabled={!ready} aria-describedby={ready ? undefined : hintId}>
            {t("open")}
          </Button>
        }
        title={t("title")}
        description={
          <>
            {t("lede")} <SimTag>{t("sandbox")}</SimTag>
          </>
        }
      >
        <form
          className="mt-4 space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          {inputFields.map((f) => (
            <label key={f.name} className="block text-sm font-medium">
              {f.label}
              <input
                type={f.type === "date" ? "date" : f.type === "number" ? "number" : "text"}
                required={f.required ?? true}
                className={`${FIELD_CLASS} h-10`}
                value={values[f.name] ?? ""}
                onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))}
              />
            </label>
          ))}
          <div>
            <label htmlFor={budgetId} className="block text-sm font-medium">
              {t("budget")}
            </label>
            <input
              id={budgetId}
              type="number"
              min={1}
              max={MAX_BUDGET}
              step={0.01}
              aria-describedby={`${budgetId}-help`}
              className={`${FIELD_CLASS} h-10 max-w-40`}
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
            />
            <p id={`${budgetId}-help`} className="mt-1 text-xs text-muted">
              {t("budgetHelp")}
            </p>
          </div>
          {refusal ? (
            <Callout
              tone="blocked"
              title={t("failed")}
              action={
                refusal.usage ? (
                  <ButtonLink href="/app/usage" variant="secondary" className="h-8 shrink-0">
                    {t("seeUsage")}
                  </ButtonLink>
                ) : null
              }
            >
              {refusal.text}
              {refusal.issues?.length ? (
                <ul className="mt-1 list-disc space-y-0.5 pl-5">
                  {refusal.issues.map((m, n) => (
                    <li key={n}>{m}</li>
                  ))}
                </ul>
              ) : null}
            </Callout>
          ) : null}
          <div className="flex justify-end gap-2">
            <ModalClose render={<Button variant="ghost" />}>{tc("cancel")}</ModalClose>
            <Button type="submit" disabled={test.isPending}>
              {t("start")}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
