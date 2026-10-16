"use client";

import { useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState } from "react";
import { Modal, ModalClose } from "@/components/base";
import { Skeleton } from "@/components/skeleton";
import { Button, ButtonLink, Callout, Pill, SimTag } from "@/components/ui";
import { toApiError } from "@/lib/api/errors";
import type { InputField, ListingCheck, StudioListingDetail } from "@/lib/api/gen/types.gen";
import { useErrorText } from "@/lib/api/use-error-text";
import { usd } from "@/lib/format";
import { useOrgId } from "@/lib/queries/me";
import { usePublisher } from "@/lib/queries/publisher";
import { useStudioListing, useStudioListings } from "@/lib/queries/publishing";
import { useSubmitListing } from "@/lib/queries/submissions";
import { useFormat } from "@/lib/use-format";
import { useCanBuild } from "./can-build";
import { FIELD_CLASS } from "./packs/editor/cel-field";
import { CheckWaitingNote, useCheckDetail } from "./publisher/listing-parts";

const CENTS = 100;
/** The publisher's share of a price, in percent. New Machines keeps the rest. */
const PUBLISHER_SHARE = 80;
const MAX_PRICE_MINOR = 100_000_00;
const MAX_BUDGET = 100_000 / CENTS;

/** The publisher's part of a price in minor units, rounded down. */
const publisherShare = (priceMinor: number) => Math.floor((priceMinor * PUBLISHER_SHARE) / 100);

const STATE_TONE = { passed: "machine", failed: "blocked", running: "human" } as const;

/** What the API refused with: its own words, its code, plus the located issues of an invalid definition. */
type Refusal = { text: string; code: string; issues: string[] };

function CheckRow({ check }: { check: ListingCheck }) {
  const t = useTranslations("studioSubmit");
  const detail = useCheckDetail();
  return (
    <li className="flex items-start gap-3 py-2 text-sm">
      <Pill tone={STATE_TONE[check.state]}>{t(`state.${check.state}`)}</Pill>
      <div className="min-w-0">
        <div className="font-medium">{t(`checks.${check.name}`)}</div>
        <div className="text-xs text-muted">{detail(check)}</div>
      </div>
    </li>
  );
}

/** Where a submitted version stands, in words for the dialog's one status region; empty while nothing to say. */
function resultStatus(listing: StudioListingDetail | undefined): "" | "waitingSandbox" | "sent" | "checksFailed" {
  if (!listing) return "";
  if (listing.latest.status === "checks_failed") return "checksFailed";
  if (listing.latest.status === "in_review") return "sent";
  return listing.latest.checks.some((c) => c.name === "sandbox" && c.state === "running") ? "waitingSandbox" : "";
}

/** The checks of the submitted version, as last read. The heading takes focus, since the form it replaces had it. */
function Result({ listing }: { listing: StudioListingDetail }) {
  const t = useTranslations("studioSubmit");
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), []);
  const checks = listing.latest.checks;
  const runId = checks.find((c) => c.name === "sandbox")?.runId;
  return (
    <div className="mt-4 space-y-3">
      <h3 ref={heading} tabIndex={-1} className="text-sm font-semibold outline-none">
        {t("resultTitle")}
      </h3>
      <ul className="divide-border divide-y">
        {checks.map((c) => (
          <CheckRow key={c.name} check={c} />
        ))}
      </ul>
      <CheckWaitingNote version={listing.latest} link={false} />
      {runId ? (
        <ButtonLink href={`/app/runs/${runId}`} variant="secondary">
          {t("openRun")}
        </ButtonLink>
      ) : null}
      <div className="flex justify-end gap-2">
        <ModalClose render={<Button variant="ghost" />}>{t("close")}</ModalClose>
        <ButtonLink href={`/studio/publisher/${listing.id}`}>{t("openListing")}</ButtonLink>
      </div>
    </div>
  );
}

/**
 * Asks for the price (and, for a pack, the sandbox test's input and budget), submits the saved version for
 * marketplace review, then shows the automatic checks. The sandbox check may still be running: the listing is
 * read again until it settles, so the dialog moves on to "Sent for review" or the failed check by itself.
 */
export function SubmitDialog({
  kind,
  keyName,
  name,
  inputFields = [],
  open,
  onClose,
}: {
  kind: "agent" | "pack";
  keyName: string;
  name: string;
  /** A pack's input fields, filled in as someone starting a real run would. */
  inputFields?: InputField[];
  open: boolean;
  onClose: () => void;
}) {
  const t = useTranslations("studioSubmit");
  const tc = useTranslations("common");
  const { money } = useFormat();
  const orgId = useOrgId();
  const errorText = useErrorText();
  const publisher = usePublisher();
  const submit = useSubmitListing(kind);
  const listings = useStudioListings();
  const priceId = useId();
  const budgetId = useId();
  const [price, setPrice] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [budget, setBudget] = useState("");
  const [refusal, setRefusal] = useState<Refusal | null>(null);
  const [submitted, setSubmitted] = useState<StudioListingDetail | null>(null);
  // The listing as last read (polled while its checks run), else as the submission answered.
  const read = useStudioListing(submitted?.id);
  // A cached read of an earlier version would show its old checks until the refetch arrives: use it only for this one.
  const fresh = read.data?.latest.id === submitted?.latest.id ? read.data : undefined;
  const listing = submitted ? (fresh ?? submitted) : undefined;
  const status = submit.isPending ? "checking" : resultStatus(listing);
  // SUBMISSION_OPEN: the version already waiting is on the listing of this definition.
  const openListing =
    refusal?.code === "SUBMISSION_OPEN" ? listings.data?.find((l) => l.key === keyName)?.id : undefined;

  const priceMinor = price === "" ? undefined : Math.round(Number(price) * CENTS);
  const validPrice =
    priceMinor !== undefined && Number.isFinite(priceMinor) && priceMinor >= 0 && priceMinor <= MAX_PRICE_MINOR;

  const send = () => {
    if (!orgId || !validPrice) return;
    const body: { priceMinor: number; input?: Record<string, unknown>; budgetMinor?: number } = { priceMinor };
    if (kind === "pack") {
      body.input = Object.fromEntries(
        inputFields
          .filter((f) => (values[f.name] ?? "") !== "")
          .map((f) => [f.name, f.type === "number" ? Number(values[f.name]) : values[f.name]]),
      );
      if (budget) body.budgetMinor = Math.round(Number(budget) * CENTS);
    }
    setRefusal(null);
    submit.mutate(
      { path: { org_id: orgId, key: keyName }, body },
      {
        onSuccess: setSubmitted,
        onError: (e) => {
          const err = toApiError(e);
          setRefusal({
            text: errorText(err),
            code: err.code,
            issues: err.code === "INVALID_DEFINITION" ? err.issues.map((i) => `${i.key || i.path}: ${i.message}`) : [],
          });
        },
      },
    );
  };

  let content;
  if (listing) {
    content = <Result listing={listing} />;
  } else if (publisher.isPending) {
    content = <Skeleton className="mt-4 h-24" />;
  } else if (publisher.isError) {
    content = (
      <div className="mt-4">
        <Callout tone="blocked" title={t("failed")}>
          {errorText(publisher.error)}
        </Callout>
      </div>
    );
  } else if (!publisher.data.enabled) {
    content = (
      <div className="mt-4 space-y-4">
        <p className="text-sm">{t("needsProfile")}</p>
        <div className="flex justify-end">
          <ButtonLink href="/app/settings#publishing">{t("openSettings")}</ButtonLink>
        </div>
      </div>
    );
  } else {
    content = (
      <form
        className="mt-4 space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          // A portal's events reach the form this dialog is opened from: it must not save the definition.
          e.stopPropagation();
          send();
        }}
      >
        <div>
          <label htmlFor={priceId} className="block text-sm font-medium">
            {kind === "pack" ? t("pricePerRun") : t("pricePerCall")}
          </label>
          <input
            id={priceId}
            type="number"
            min={0}
            max={MAX_PRICE_MINOR / CENTS}
            step={0.01}
            required
            aria-describedby={`${priceId}-help`}
            className={`${FIELD_CLASS} h-10 max-w-40`}
            value={price}
            onChange={(e) => setPrice(e.target.value)}
          />
          <p id={`${priceId}-help`} className="mt-1 text-xs text-muted">
            {t("priceHelp")}
          </p>
          {validPrice ? (
            <p className="mt-1 text-sm" aria-live="polite">
              {priceMinor === 0 ? (
                t("noFee")
              ) : (
                <>
                  {t("split")}{" "}
                  <span className="text-muted">{t("youGet", { amount: money(usd(publisherShare(priceMinor))) })}</span>{" "}
                  <SimTag />
                </>
              )}
            </p>
          ) : null}
        </div>
        {kind === "pack" ? (
          <>
            <p className="text-xs text-muted">{t("sandboxNote")}</p>
            {inputFields.length > 0 ? (
              <fieldset className="space-y-4">
                <legend className="mb-2 text-sm font-medium">{t("input")}</legend>
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
              </fieldset>
            ) : null}
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
          </>
        ) : null}
        {refusal ? (
          <Callout
            tone="blocked"
            title={t("failed")}
            action={
              openListing ? (
                <ButtonLink href={`/studio/publisher/${openListing}`} variant="secondary">
                  {t("openListing")}
                </ButtonLink>
              ) : null
            }
          >
            {refusal.issues.length ? (
              <ul className="list-disc space-y-0.5 pl-5">
                {refusal.issues.map((m, n) => (
                  <li key={n}>{m}</li>
                ))}
              </ul>
            ) : (
              refusal.text
            )}
          </Callout>
        ) : null}
        <div className="flex justify-end gap-2">
          <ModalClose render={<Button variant="ghost" />}>{tc("cancel")}</ModalClose>
          <Button type="submit" disabled={submit.isPending || !validPrice}>
            {t("submit")}
          </Button>
        </div>
      </form>
    );
  }

  return (
    <Modal open={open} onOpenChange={(o) => (o ? undefined : onClose())} title={t("title", { name })}>
      {content}
      {/* One region for every status, mounted from the start, so screen readers announce each change of text. */}
      <p role="status" className={status ? "mt-3 text-sm font-medium" : "sr-only"}>
        {status ? t(status) : ""}
      </p>
    </Modal>
  );
}

/**
 * The "Submit for review" button of a saved agent or pack. Only builders see it, and it waits for unsaved
 * changes to be saved, because the review is of the saved version. The dialog mounts only once opened.
 */
export function SubmitButton({
  kind,
  keyName,
  name,
  dirty,
  inputFields,
}: {
  kind: "agent" | "pack";
  keyName: string;
  name: string;
  dirty: boolean;
  inputFields?: InputField[];
}) {
  const t = useTranslations("studioSubmit");
  const canBuild = useCanBuild();
  const [open, setOpen] = useState(false);
  const hintId = useId();
  if (!canBuild) return null;
  return (
    <>
      {dirty ? (
        <span id={hintId} className="text-xs text-muted">
          {t("saveFirst")}
        </span>
      ) : null}
      <Button
        type="button"
        variant="secondary"
        disabled={dirty}
        aria-describedby={dirty ? hintId : undefined}
        onClick={() => setOpen(true)}
      >
        {t("button")}
      </Button>
      {open ? (
        <SubmitDialog
          kind={kind}
          keyName={keyName}
          name={name}
          inputFields={inputFields}
          open
          onClose={() => setOpen(false)}
        />
      ) : null}
    </>
  );
}
