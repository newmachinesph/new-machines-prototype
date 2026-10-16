import { getTranslations } from "next-intl/server";
import { NotFoundPanel } from "@/components/not-found-panel";
import { ButtonLink } from "@/components/ui";

/** A missing task inside the reviewer portal keeps its shell and leads back to the available tasks. */
export default async function NotFound() {
  const t = await getTranslations("errors.notFound");
  const work = await getTranslations("work");
  return (
    <NotFoundPanel title={t("title")} body={t("body")}>
      <ButtonLink href="/work">{work("backToTasks")}</ButtonLink>
    </NotFoundPanel>
  );
}
