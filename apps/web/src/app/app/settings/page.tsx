import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/components/ui";
import { MembersSection, TokensSection } from "./access";
import { PoliciesSection, WorkspaceSection } from "./workspace";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("nav"))("settings") };
}

export default async function SettingsPage() {
  const t = await getTranslations("settings");
  return (
    <>
      <PageHeader title={t("title")} lede={t("lede")} />
      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-2">
        <PoliciesSection />

        <div className="space-y-6">
          <MembersSection />
          <TokensSection />
          <WorkspaceSection />
        </div>
      </div>
    </>
  );
}
