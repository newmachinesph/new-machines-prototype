import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { RoleHeader } from "../../role-header";
import { AgentEditor } from "../agent-form";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("studioAgents"))("editTitle") };
}

export default async function EditAgentPage({ params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  const t = await getTranslations("studioAgents");
  return (
    <>
      <RoleHeader
        edit={{ title: t("editTitle"), lede: t("editLede") }}
        view={{ title: t("viewTitle"), lede: t("viewLede") }}
      />
      <AgentEditor agentKey={key} />
    </>
  );
}
