"use client";

import { useTranslations } from "next-intl";
import { Confirm, useToast } from "@/components/base";
import { Button } from "@/components/ui";
import { useErrorText } from "@/lib/api/use-error-text";
import { leaveFor } from "@/lib/navigate";
import { connectorKey, useConnectApp, useSyncConnection } from "@/lib/queries/workspace";
import type { Connection } from "@/lib/types";

/** The sim palette `SimTag` uses, on a secondary button. */
const SIM_BUTTON = "border-dashed border-sim/50 bg-sim-soft text-sim hover:border-sim";

/**
 * Told the app's new status when an action changed its card without leaving the page, so the parent can move
 * focus to the control that now makes sense for it (the one that was pressed is usually gone).
 */
export type OnOutcome = (status: Connection["status"]) => void;

/**
 * Connect the app's real account: the API answers with the app's sign-in page and the browser goes there. On the
 * way back (`?connected=<key>`) the connection is finished. When the real account is already connected, the API
 * answers with the row and no sign-in page; that counts as connected. Any other answer that keeps the browser
 * here (no page, or a page that is not a secure web address) is said so and not claimed as a success.
 */
export function useConnectReal() {
  const t = useTranslations("connections");
  const errorText = useErrorText();
  const toast = useToast();
  const connect = useConnectApp();
  const start = (c: Connection, onOutcome?: OnOutcome) =>
    connect.mutate(
      { path: { app_name: connectorKey(c) }, body: { mode: "live" } },
      {
        onSuccess: (started) => {
          if (started.redirectUrl && leaveFor(started.redirectUrl)) return;
          if (started.redirectUrl) toast(t("connectFailed", { app: c.app }), t("badSignInLink"), "blocked");
          else if (started.status === "connected") {
            toast(t("connectedToast", { app: c.app }), t("connectedRealBody", { app: c.app }));
          } else toast(t("pendingToast", { app: c.app }), t("pendingToastBody", { app: c.app }), "blocked");
          onOutcome?.(started.status);
        },
        onError: (e) => toast(t("connectFailed", { app: c.app }), errorText(e), "blocked"),
      },
    );
  return { start, isPending: connect.isPending };
}

/**
 * An app that is not connected: its real account (primary) or simulated data. Only an owner or admin may connect
 * the real account (the API refuses others), so `realAllowed` false leaves simulated data as the one choice.
 */
export function ConnectChoices({
  conn: c,
  onOutcome,
  realAllowed = true,
}: {
  conn: Connection;
  onOutcome: OnOutcome;
  realAllowed?: boolean;
}) {
  const t = useTranslations("connections");
  const errorText = useErrorText();
  const toast = useToast();
  const real = useConnectReal();
  const sandbox = useConnectApp();
  const busy = real.isPending || sandbox.isPending;
  const simulate = () =>
    sandbox.mutate(
      { path: { app_name: connectorKey(c) }, body: { mode: "sandbox" } },
      {
        onSuccess: (now) => {
          toast(t("connectedToast", { app: c.app }), t("connectedSandboxBody"), "sim");
          onOutcome(now.status);
        },
        onError: (e) => toast(t("connectFailed", { app: c.app }), errorText(e), "blocked"),
      },
    );
  return (
    <div className="flex flex-wrap items-center gap-2">
      {realAllowed ? (
        <Button className="h-8" data-connect={c.app} disabled={busy} onClick={() => real.start(c, onOutcome)}>
          {t("connectApp", { app: c.app })}
        </Button>
      ) : null}
      <Button
        variant="secondary"
        className={`h-8 ${SIM_BUTTON}`}
        data-connect-sim={c.app}
        aria-label={t("useSimulatedFor", { app: c.app })}
        disabled={busy}
        onClick={simulate}
      >
        {t("useSimulated")}
      </Button>
    </div>
  );
}

/**
 * A real account whose sign-in has not finished: ask the API how it went. Connected is said so; switched to
 * simulated data meanwhile is said as that, not as connected; still waiting starts a fresh sign-in, since links
 * expire (only for an owner or admin, `realAllowed`; anyone else is told it is still pending); anything else is
 * a sign-in that did not finish, never a success.
 */
export function FinishConnecting({
  conn: c,
  onOutcome,
  realAllowed = true,
}: {
  conn: Connection;
  onOutcome: OnOutcome;
  realAllowed?: boolean;
}) {
  const t = useTranslations("connections");
  const errorText = useErrorText();
  const toast = useToast();
  const sync = useSyncConnection();
  const real = useConnectReal();
  const finish = () =>
    sync.mutate(
      { path: { app_name: connectorKey(c) } },
      {
        onSuccess: (now) => {
          if (now.status === "pending" && realAllowed) return real.start(c, onOutcome);
          if (now.status === "pending") {
            toast(t("pendingToast", { app: c.app }), t("pendingToastBody", { app: c.app }), "blocked");
          } else if (now.status === "connected") {
            toast(t("connectedToast", { app: c.app }), t("connectedRealBody", { app: c.app }));
          } else if (now.status === "sandbox") {
            toast(t("simulatedToast", { app: c.app }), t("simulatedToastBody"), "sim");
          } else toast(t("connectFailed", { app: c.app }), t("signInFailedBody"), "blocked");
          onOutcome(now.status);
        },
        onError: (e) => toast(t("connectFailed", { app: c.app }), errorText(e), "blocked"),
      },
    );
  return (
    <Button
      className="h-8"
      data-finish={c.app}
      aria-label={t("finishConnectingFor", { app: c.app })}
      disabled={sync.isPending || real.isPending}
      onClick={finish}
    >
      {t("finishConnecting")}
    </Button>
  );
}

/**
 * A link-style action that signs in to the app's real account (switch from simulated data, or sign in again).
 * With `confirm`, it asks first and the dialog's confirm button repeats `label`.
 */
export function RealAccountButton({
  conn: c,
  label,
  ariaLabel,
  onOutcome,
  confirm,
}: {
  conn: Connection;
  label: string;
  ariaLabel?: string;
  onOutcome?: OnOutcome;
  confirm?: { title: string; description: string };
}) {
  const real = useConnectReal();
  const go = () => real.start(c, onOutcome);
  const button = (
    <button
      type="button"
      data-real={c.app}
      aria-label={ariaLabel}
      className="link text-xs"
      disabled={real.isPending}
      onClick={confirm ? undefined : go}
    >
      {label}
    </button>
  );
  return confirm ? (
    <Confirm
      trigger={button}
      title={confirm.title}
      description={confirm.description}
      confirmLabel={label}
      onConfirm={go}
    />
  ) : (
    button
  );
}
