import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/components/ui";
import { PackEditor } from "../editor/pack-editor";

type Props = { searchParams: Promise<{ from?: string | string[] }> };

/** The pack to copy: a single non-empty `from`, else none (a repeated or empty one opens a blank pack). */
async function sourceOf(searchParams: Props["searchParams"]): Promise<string | undefined> {
  const { from: raw } = await searchParams;
  return typeof raw === "string" && raw ? raw : undefined;
}

export async function generateMetadata({ searchParams }: Props): Promise<Metadata> {
  const t = await getTranslations("studioPacks");
  const from = await sourceOf(searchParams);
  return { title: from ? t("copyTitle") : t("newTitle") };
}

export default async function NewPackPage({ searchParams }: Props) {
  const t = await getTranslations("studioPacks");
  const from = await sourceOf(searchParams);
  return (
    <>
      <PageHeader title={from ? t("copyTitle") : t("newTitle")} lede={from ? t("copyLede") : t("newLede")} />
      <PackEditor from={from} />
    </>
  );
}
