import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/components/ui";
import { ReviewersView } from "./reviewers-view";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("nav"))("reviewers") };
}

export default async function ReviewersPage() {
  const t = await getTranslations("reviewers");
  return (
    <>
      <PageHeader title={t("title")} lede={t("lede")} />
      <ReviewersView />
    </>
  );
}
