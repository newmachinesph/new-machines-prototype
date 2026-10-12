import { getTranslations } from "next-intl/server";
import { ButtonLink } from "@/components/ui";
import { Lockup } from "@/design-system/logo/Lockup";

export default async function NotFound() {
  const t = await getTranslations("errors.notFound");
  return (
    <main id="main" className="mx-auto flex min-h-dvh max-w-xl flex-col justify-center px-6">
      <Lockup trim className="h-8 w-auto text-ink" />
      <h1 className="mt-10 text-3xl font-semibold tracking-tight">{t("title")}</h1>
      <p className="mt-3 text-[15px] leading-relaxed text-grey-700">{t("body")}</p>
      <div className="mt-6 flex gap-2">
        <ButtonLink href="/app">{t("overview")}</ButtonLink>
        <ButtonLink href="/app/runs" variant="secondary">
          {t("allRuns")}
        </ButtonLink>
      </div>
    </main>
  );
}
