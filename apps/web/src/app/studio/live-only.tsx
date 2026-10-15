"use client";

import { useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { ErrorPanel } from "@/components/error-panel";
import { Skeleton } from "@/components/skeleton";
import { ButtonLink, Callout, PageHeader } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import { useIsLive, useMe } from "@/lib/queries/me";

/** The Studio builds the org's own definitions, so it exists in a live workspace only. */
export function LiveOnly({ children }: { children: ReactNode }) {
  const t = useTranslations("studio");
  const tErrors = useTranslations("errors");
  const me = useMe();
  const live = useIsLive();
  if (me.isPending) return <Skeleton className="h-40" />;
  if (me.isError) {
    // A 401 is already signing out and redirecting, so a panel would only flash.
    if (me.error instanceof ApiError && me.error.status === 401) return <Skeleton className="h-40" />;
    // A failed /v1/me is not a demo workspace. The panel renders here, inside the shell, since this layout's
    // own error.tsx covers only its pages.
    return <ErrorPanel title={tErrors("pageCouldNotLoad")} error={me.error} reset={() => undefined} />;
  }
  if (!live)
    return (
      <>
        <PageHeader title={t("title")} />
        <Callout
          tone="info"
          title={t("liveOnlyTitle")}
          announce={false}
          action={
            <ButtonLink href="/app" variant="secondary">
              {t("backToWorkspace")}
            </ButtonLink>
          }
        >
          {t("liveOnlyBody")}
        </Callout>
      </>
    );
  return <>{children}</>;
}
