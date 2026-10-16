"use client";

import { useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { ButtonLink, Callout, PageHeader } from "@/components/ui";
import { useCanBuild } from "../can-build";

/** Publishing (listings and earnings) is for owners and admins only; the API refuses members, so a member who
 * opens a Publisher link sees why instead of a failed read. Inside `LiveOnly`, so /v1/me has answered. */
export function ManagersOnly({ children }: { children: ReactNode }) {
  const t = useTranslations("studioPublisher");
  if (useCanBuild()) return <>{children}</>;
  return (
    <>
      <PageHeader title={t("title")} />
      <Callout
        tone="info"
        title={t("managersOnlyTitle")}
        announce={false}
        action={
          <ButtonLink href="/studio" variant="secondary">
            {t("backToStudio")}
          </ButtonLink>
        }
      >
        {t("managersOnlyBody")}
      </Callout>
    </>
  );
}
