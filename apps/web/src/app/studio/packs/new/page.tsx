import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/components/ui";
import { PackEditor } from "../editor/pack-editor";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("studioPacks"))("newTitle") };
}

export default async function NewPackPage() {
  const t = await getTranslations("studioPacks");
  return (
    <>
      <PageHeader title={t("newTitle")} lede={t("newLede")} />
      <PackEditor />
    </>
  );
}
