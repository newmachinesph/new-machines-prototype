"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { ButtonLink, Callout, EmptyState, Section } from "@/components/ui";
import { useStudioAgents, useStudioPacks } from "@/lib/queries/studio";
import { useCanBuild } from "./can-build";

export function StudioHome() {
  const t = useTranslations("studio");
  const agents = useStudioAgents();
  const packs = useStudioPacks();
  const canBuild = useCanBuild();
  return (
    <div className="space-y-6">
      <Callout tone="info" title={t("privateTitle")} announce={false}>
        {t("privateBody")}
      </Callout>
      {canBuild ? null : <p className="text-sm text-muted">{t("buildersOnly")}</p>}
      <div className="grid gap-4 md:grid-cols-2">
        <Section
          title={t("agentsTitle")}
          aside={
            canBuild ? (
              <ButtonLink href="/studio/agents/new" variant="secondary" className="h-8">
                {t("newAgent")}
              </ButtonLink>
            ) : null
          }
        >
          <QueryState query={agents} skeleton={<Skeleton className="m-5 h-10" />}>
            {(list) =>
              list.length === 0 ? (
                <EmptyState>{t("noAgents")}</EmptyState>
              ) : (
                <p className="px-5 py-4 text-sm">
                  <Link href="/studio/agents" className="font-medium hover:underline">
                    {t("agentCount", { n: list.length })}
                  </Link>
                </p>
              )
            }
          </QueryState>
        </Section>
        <Section
          title={t("packsTitle")}
          aside={
            canBuild ? (
              <ButtonLink href="/studio/packs/new" variant="secondary" className="h-8">
                {t("newPack")}
              </ButtonLink>
            ) : null
          }
        >
          <QueryState query={packs} skeleton={<Skeleton className="m-5 h-10" />}>
            {(list) =>
              list.length === 0 ? (
                <EmptyState>{t("noPacks")}</EmptyState>
              ) : (
                <p className="px-5 py-4 text-sm">
                  <Link href="/studio/packs" className="font-medium hover:underline">
                    {t("packCount", { n: list.length })}
                  </Link>
                </p>
              )
            }
          </QueryState>
        </Section>
      </div>
    </div>
  );
}
