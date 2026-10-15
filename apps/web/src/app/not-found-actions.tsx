"use client";

import { useTranslations } from "next-intl";
import { ButtonLink } from "@/components/ui";
import { useSession } from "@/lib/auth/session";

/** Only the client knows whether anyone is signed in: a visitor gets sign-in, a member their workspace. */
export function NotFoundActions() {
  const t = useTranslations("errors.notFound");
  const { status } = useSession();
  return (
    <div className="mt-6 flex min-h-9 gap-2">
      {status === "signed-in" ? (
        <>
          <ButtonLink href="/app">{t("overview")}</ButtonLink>
          <ButtonLink href="/app/runs" variant="secondary">
            {t("allRuns")}
          </ButtonLink>
        </>
      ) : null}
      {status === "signed-out" ? <ButtonLink href="/">{t("signIn")}</ButtonLink> : null}
    </div>
  );
}
