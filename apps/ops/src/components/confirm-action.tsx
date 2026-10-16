"use client";

import { AlertDialog } from "@base-ui/react/alert-dialog";
import { zodResolver } from "@hookform/resolvers/zod";
import { type ReactElement, type ReactNode, useId, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { errorText } from "@/lib/api/error-text";
import { cn } from "@/lib/cn";
import { BACKDROP, MODAL } from "./base";
import { Button } from "./ui";

/** The API's limit for the reason every ops mutation carries. */
export const REASON_MAX = 500;

export const reasonSchema = z.object({
  reason: z
    .string()
    .trim()
    .min(1, "Give a reason. It is recorded in the audit log.")
    .max(REASON_MAX, `Keep the reason to ${REASON_MAX} characters or fewer.`),
});
type ReasonValues = z.infer<typeof reasonSchema>;

export type ConfirmActionProps = {
  /** The control that opens the dialog. Omit it and pass `open`/`onOpenChange` to open from elsewhere (e.g. `?action=`). */
  trigger?: ReactElement;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** A question naming the action and its target: "Suspend Harbor & Pine Supply Co.?" */
  title: string;
  /** What will happen, in plain words: who loses what, what stops, how to undo it. */
  consequence: ReactNode;
  /** The confirm button's label: the action itself ("Suspend tenant"), never "Confirm" or "Submit". */
  confirmLabel: string;
  /** Uses the blocked colour for the confirm button. Use for suspend, kill switch, deprecate, disable and reject. */
  destructive?: boolean;
  /**
   * Runs the action with the trimmed reason. Resolve to close the dialog; reject (e.g. `mutateAsync` failing)
   * to keep it open with the API's error shown inline.
   */
  onConfirm: (reason: string) => Promise<unknown> | void;
  /** Extra fields for the action (a plan picker, a spend cap), shown above the reason. The caller owns their state. */
  children?: ReactNode;
  /** Blocks the confirm button, e.g. while an extra field is invalid. */
  confirmDisabled?: boolean;
  /** Placeholder for the reason, e.g. "Chargeback dispute opened by the card issuer". */
  reasonPlaceholder?: string;
  /** Label for the reason field when "Reason" does not fit, e.g. "Note for the publisher". */
  reasonLabel?: string;
};

/**
 * The confirm dialog for every ops mutation: a title, the consequence, a required reason (1 to 500
 * characters, trimmed) and a confirm button named after the action. The reason goes to the API, which
 * writes it to the audit log.
 */
export function ConfirmAction({
  trigger,
  open: openProp,
  onOpenChange,
  title,
  consequence,
  confirmLabel,
  destructive,
  onConfirm,
  children,
  confirmDisabled,
  reasonPlaceholder,
  reasonLabel = "Reason",
}: ConfirmActionProps) {
  const id = useId();
  const [openState, setOpenState] = useState(false);
  const open = openProp ?? openState;
  const [apiError, setApiError] = useState<string | null>(null);
  const schema = useMemo(
    () =>
      reasonLabel === "Reason"
        ? reasonSchema
        : reasonSchema.extend({
            reason: z
              .string()
              .trim()
              .min(1, `Add a ${reasonLabel.toLowerCase()}. It is recorded in the audit log.`)
              .max(REASON_MAX, `Keep the ${reasonLabel.toLowerCase()} to ${REASON_MAX} characters or fewer.`),
          }),
    [reasonLabel],
  );
  const form = useForm<ReasonValues>({
    resolver: zodResolver(schema),
    defaultValues: { reason: "" },
    shouldFocusError: true,
  });
  const { errors, isSubmitting } = form.formState;

  const commitOpen = (next: boolean) => {
    setOpenState(next);
    onOpenChange?.(next);
  };
  // Escape, Cancel and the trigger. A running action finishes before the dialog can close, so its outcome is never lost.
  const requestOpen = (next: boolean) => {
    if (!next && form.formState.isSubmitting) return;
    commitOpen(next);
  };

  const submit = form.handleSubmit(async ({ reason }) => {
    setApiError(null);
    try {
      await onConfirm(reason);
      commitOpen(false);
    } catch (e) {
      setApiError(errorText(e));
    }
  });

  const reasonId = `${id}-reason`;
  const hintId = `${id}-hint`;
  const fieldErrorId = `${id}-error`;

  return (
    <AlertDialog.Root
      open={open}
      onOpenChange={requestOpen}
      onOpenChangeComplete={(isOpen) => {
        // Reset once the close animation is over, so the content does not flicker while it fades.
        if (isOpen) return;
        form.reset();
        setApiError(null);
      }}
    >
      {trigger ? <AlertDialog.Trigger render={trigger} /> : null}
      <AlertDialog.Portal>
        <AlertDialog.Backdrop className={BACKDROP} />
        <AlertDialog.Popup className={cn(MODAL, "max-h-[calc(100dvh-2rem)] overflow-y-auto")}>
          <AlertDialog.Title className="text-base font-semibold">{title}</AlertDialog.Title>
          <AlertDialog.Description className="mt-1.5 text-sm leading-relaxed text-grey-700">
            {consequence}
          </AlertDialog.Description>
          <form onSubmit={submit} noValidate className="mt-4 space-y-4">
            {children}
            <div className="text-sm">
              <label htmlFor={reasonId} className="font-medium">
                {reasonLabel}
              </label>
              <textarea
                id={reasonId}
                rows={3}
                placeholder={reasonPlaceholder}
                aria-invalid={errors.reason ? true : undefined}
                aria-describedby={errors.reason ? `${fieldErrorId} ${hintId}` : hintId}
                className="mt-1.5 block w-full resize-y rounded-md border border-grey-300 bg-paper px-3 py-2 text-sm outline-none focus:border-ink aria-[invalid]:border-blocked"
                {...form.register("reason")}
              />
              {errors.reason ? (
                <p id={fieldErrorId} role="alert" className="mt-1 text-xs text-blocked">
                  {errors.reason.message}
                </p>
              ) : null}
              <p id={hintId} className="mt-1 text-xs text-muted">
                Recorded in the audit log with your email.
              </p>
            </div>
            {apiError ? (
              <p
                role="alert"
                className="rounded-md border border-blocked/30 bg-blocked-soft/60 px-3 py-2 text-sm text-blocked"
              >
                {apiError}
              </p>
            ) : null}
            <div className="flex flex-wrap justify-end gap-2">
              <AlertDialog.Close render={<Button variant="ghost" disabled={isSubmitting} />}>Cancel</AlertDialog.Close>
              <Button
                type="submit"
                variant={destructive ? "destructive" : "primary"}
                disabled={isSubmitting || confirmDisabled}
                aria-busy={isSubmitting || undefined}
              >
                {confirmLabel}
              </Button>
            </div>
          </form>
        </AlertDialog.Popup>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
