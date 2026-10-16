import { getTranslations } from "next-intl/server";
import { NotFoundPanel } from "@/components/not-found-panel";
import { ButtonLink } from "@/components/ui";

/** A missing Studio page keeps the Studio's shell and leads back to its home. */
export default async function NotFound() {
  const t = await getTranslations("errors.notFound");
  return (
    <NotFoundPanel title={t("title")} body={t("body")}>
      <ButtonLink href="/studio">{t("backToStudio")}</ButtonLink>
    </NotFoundPanel>
  );
}
