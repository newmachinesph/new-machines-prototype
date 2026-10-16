import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/components/ui";
import { PublisherView } from "./publisher-view";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("nav"))("studioPublisher") };
}

export default async function StudioPublisherPage() {
  const t = await getTranslations("studioPublisher");
  return (
    <>
      <PageHeader title={t("title")} lede={t("intro")} />
      <PublisherView />
    </>
  );
}
