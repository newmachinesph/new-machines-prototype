import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/components/ui";
import { NewPackLink } from "./new-pack-link";
import { PacksList } from "./packs-list";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("nav"))("studioPacks") };
}

export default async function StudioPacksPage() {
  const t = await getTranslations("studioPacks");
  return (
    <>
      <PageHeader title={t("title")} lede={t("lede")} actions={<NewPackLink />} />
      <PacksList />
    </>
  );
}
