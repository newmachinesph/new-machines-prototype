import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { PageHeader } from "@/components/ui";
import { AgentList, AgentListSkeleton } from "./agent-list";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("nav"))("agents") };
}

export default async function AgentsPage() {
  const nav = await getTranslations("nav");
  const t = await getTranslations("agents.list");
  return (
    <>
      <PageHeader title={nav("agents")} lede={t("lede")} />
      <Suspense fallback={<AgentListSkeleton />}>
        <AgentList />
      </Suspense>
    </>
  );
}
