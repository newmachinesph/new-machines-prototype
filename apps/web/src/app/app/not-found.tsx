import { getTranslations } from "next-intl/server";
import { NotFoundPanel } from "@/components/not-found-panel";
import { ButtonLink } from "@/components/ui";

/** A missing pack, agent or run inside the business workspace keeps its shell and leads back into it. */
export default async function NotFound() {
  const t = await getTranslations("errors.notFound");
  return (
    <NotFoundPanel title={t("title")} body={t("body")}>
      <ButtonLink href="/app">{t("overview")}</ButtonLink>
      <ButtonLink href="/app/runs" variant="secondary">
        {t("allRuns")}
      </ButtonLink>
    </NotFoundPanel>
  );
}
