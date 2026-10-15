"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { ButtonLink, Callout, EmptyState, Section } from "@/components/ui";
import type { StudioAgentSummary, StudioPackSummary } from "@/lib/api/gen/types.gen";
import { useStudioAgents, useStudioPacks } from "@/lib/queries/studio";
import { useCanBuild } from "./can-build";

const RECENT = 3;

/** The latest few, newest first; the lists are already loaded for the counts. */
const recent = <T extends { publishedAt: string }>(list: T[]) =>
  [...list].sort((a, b) => b.publishedAt.localeCompare(a.publishedAt)).slice(0, RECENT);

/** The one thing to do next, from what the org has built so far; nothing once every pack is added. */
function nextStep(agents: StudioAgentSummary[] | undefined, packs: StudioPackSummary[] | undefined) {
  if (!agents || !packs) return null;
  if (agents.length === 0) return "nextAgent";
  if (packs.length === 0) return "nextPack";
  return packs.some((p) => !p.added) ? "nextAdd" : null;
}

export function StudioHome() {
  const t = useTranslations("studio");
  const agents = useStudioAgents();
  const packs = useStudioPacks();
  const canBuild = useCanBuild();
  const next = canBuild ? nextStep(agents.data, packs.data) : null;
  return (
    <div className="space-y-6">
      <Callout tone="info" title={t("privateTitle")} announce={false}>
        {t("privateBody")}
      </Callout>
      {canBuild ? null : <p className="text-sm text-muted">{t("buildersOnly")}</p>}
      {next ? <p className="text-sm">{t(next)}</p> : null}
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
                <RecentList
                  items={recent(list).map((a) => ({
                    key: a.key,
                    href: `/studio/agents/${a.key}`,
                    name: a.name,
                    detail: a.summary,
                    version: a.version,
                  }))}
                  allHref="/studio/agents"
                  allLabel={t("allAgents", { n: list.length })}
                />
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
                <RecentList
                  items={recent(list).map((p) => ({
                    key: p.key,
                    href: `/studio/packs/${p.key}`,
                    name: p.name,
                    detail: p.outcome,
                    version: p.version,
                  }))}
                  allHref="/studio/packs"
                  allLabel={t("allPacks", { n: list.length })}
                />
              )
            }
          </QueryState>
        </Section>
      </div>
    </div>
  );
}

/** The newest items as full-width row links, then a link to the whole list: every part of the card is a target. */
function RecentList({
  items,
  allHref,
  allLabel,
}: {
  items: { key: string; href: string; name: string; detail: string; version: number }[];
  allHref: string;
  allLabel: string;
}) {
  const t = useTranslations("studio");
  return (
    <>
      <ul className="divide-y divide-rule">
        {items.map((i) => (
          <li key={i.key}>
            <Link
              href={i.href}
              className="flex min-h-11 items-center justify-between gap-3 px-5 py-2.5 text-sm hover:bg-grey-50/70"
            >
              <span className="min-w-0">
                <span className="block truncate font-medium">{i.name}</span>
                {i.detail ? <span className="block truncate text-xs text-muted">{i.detail}</span> : null}
              </span>
              <span className="tnum shrink-0 text-xs text-muted">{t("version", { n: i.version })}</span>
            </Link>
          </li>
        ))}
      </ul>
      <Link
        href={allHref}
        className="block min-h-11 border-t border-rule px-5 py-3 text-sm font-medium hover:bg-grey-50/70"
      >
        {allLabel}
      </Link>
    </>
  );
}
