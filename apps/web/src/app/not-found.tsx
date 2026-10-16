import { getTranslations } from "next-intl/server";
import { Lockup } from "@/design-system/logo/Lockup";
import { NotFoundActions } from "./not-found-actions";

export default async function NotFound() {
  const t = await getTranslations("errors.notFound");
  return (
    <main id="main" className="mx-auto flex min-h-dvh max-w-xl flex-col justify-center px-6">
      <title>{`${t("title")} | New Machines`}</title>
      <Lockup trim className="h-8 w-auto text-ink" />
      <h1 className="mt-10 text-3xl font-semibold tracking-tight">{t("title")}</h1>
      <p className="mt-3 text-[15px] leading-relaxed text-grey-700">{t("body")}</p>
      <NotFoundActions />
    </main>
  );
}
