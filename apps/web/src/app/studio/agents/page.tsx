import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/components/ui";
import { AgentsList } from "./agents-list";
import { NewAgentLink } from "./new-agent-link";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("nav"))("studioAgents") };
}

export default async function StudioAgentsPage() {
  const t = await getTranslations("studioAgents");
  return (
    <>
      <PageHeader title={t("title")} lede={t("lede")} actions={<NewAgentLink />} />
      <AgentsList />
    </>
  );
}
