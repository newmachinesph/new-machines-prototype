import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/components/ui";
import { AgentEditor } from "../agent-form";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("studioAgents"))("newTitle") };
}

export default async function NewAgentPage() {
  const t = await getTranslations("studioAgents");
  return (
    <>
      <PageHeader title={t("newTitle")} lede={t("newLede")} />
      <AgentEditor />
    </>
  );
}
