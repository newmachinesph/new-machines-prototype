"use client";

import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";
import { useToast } from "@/components/base";
import { useErrorText } from "@/lib/api/use-error-text";
import { useIsDemo } from "@/lib/queries/me";
import { useConnections } from "@/lib/queries/org";
import { findConnection, useSyncConnection } from "@/lib/queries/workspace";
import type { Connection } from "@/lib/types";

/**
 * Back from an app's sign-in page (`?connected=<connector key>`): ask the API how the sign-in went, say so, tell
 * the card the app's status so focus lands on the control that now makes sense, and drop the query from the
 * address (including what the sign-in service added) without reloading. Renders nothing.
 *
 * Only a listed real account (`mode` composio: pending, or signing in again) is asked about; a key the workspace
 * does not list, or one connected to simulated data (a stale or bookmarked return), only has its query dropped.
 * The demo workspace has no sign-in pages, so nothing happens there.
 *
 * The API is asked once per key: the `handled` ref survives strict mode's second effect run and the renders
 * the refetched list and fresh toast closures cause.
 */
export function ConnectReturn({ onOutcome }: { onOutcome: (app: string, status: Connection["status"]) => void }) {
  const t = useTranslations("connections");
  const demo = useIsDemo();
  const key = useSearchParams().get("connected");
  const router = useRouter();
  const pathname = usePathname();
  const toast = useToast();
  const errorText = useErrorText();
  const conns = useConnections().data;
  const { mutate } = useSyncConnection();
  const handled = useRef<string | null>(null);

  useEffect(() => {
    if (demo || !key || !conns || handled.current === key) return;
    handled.current = key;
    const dropQuery = () => router.replace(pathname, { scroll: false });
    const conn = findConnection(conns, key);
    if (conn?.mode !== "composio") {
      dropQuery();
      return;
    }
    mutate(
      { path: { app_name: key } },
      {
        onSuccess: (now) => {
          if (now.status === "connected") {
            toast(t("connectedToast", { app: now.app }), t("connectedRealBody", { app: now.app }));
          } else if (now.status === "pending") {
            toast(t("pendingToast", { app: now.app }), t("pendingToastBody", { app: now.app }), "blocked");
          } else if (now.status !== "sandbox") {
            // Not connected, or the account needs signing in again: the sign-in did not finish.
            toast(t("connectFailed", { app: now.app }), t("signInFailedBody"), "blocked");
          }
          // `sandbox`: the app was switched to simulated data meanwhile. The refetched card says so; no claim here.
          onOutcome(now.app, now.status);
        },
        // Nothing is known about the row, so focus stays where it is.
        onError: (e) => toast(t("connectFailed", { app: conn.app }), errorText(e), "blocked"),
        onSettled: dropQuery,
      },
    );
  }, [demo, key, conns, mutate, onOutcome, pathname, router, t, toast, errorText]);

  return null;
}
