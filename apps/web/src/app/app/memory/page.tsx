import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/components/ui";
import { MemoryBoard } from "./memory-items";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("nav"))("memory") };
}

export default async function MemoryPage() {
  const t = await getTranslations("memory");
  return (
    <>
      <PageHeader title={t("title")} lede={t("lede")} />
      <MemoryBoard />
    </>
  );
}
