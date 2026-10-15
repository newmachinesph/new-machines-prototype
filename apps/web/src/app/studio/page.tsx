import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/components/ui";
import { StudioHome } from "./studio-home";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("nav"))("developerStudio") };
}

export default async function StudioPage() {
  const t = await getTranslations("studio");
  return (
    <>
      <PageHeader title={t("title")} lede={t("lede")} />
      <StudioHome />
    </>
  );
}
