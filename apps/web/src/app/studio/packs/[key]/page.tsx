import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { RoleHeader } from "../../role-header";
import { PackEditor } from "../editor/pack-editor";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("studioPacks"))("editTitle") };
}

export default async function EditPackPage({ params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  const t = await getTranslations("studioPacks");
  return (
    <>
      <RoleHeader
        edit={{ title: t("editTitle"), lede: t("editLede") }}
        view={{ title: t("viewTitle"), lede: t("viewLede") }}
      />
      <PackEditor packKey={key} />
    </>
  );
}
