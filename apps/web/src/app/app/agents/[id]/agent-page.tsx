"use client";

import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { notFound } from "next/navigation";
import { PackIcon } from "@/components/pack-icon";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Id, KeyValues, PageHeader, Pill, Section, SimTag } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import { useAgent } from "@/lib/queries/catalog";
import { useFormat } from "@/lib/use-format";
import type { Agent } from "@/lib/types";

export function AgentPage({ id }: { id: string }) {
  const agent = useAgent(id);
  if (agent.error instanceof ApiError && agent.error.status === 404) notFound();
  return (
    <QueryState query={agent} skeleton={<AgentSkeleton />}>
      {(a) => <AgentDetail agent={a} />}
    </QueryState>
  );
}

function AgentDetail({ agent: a }: { agent: Agent }) {
  const t = useTranslations("agents.detail");
  const { list } = useFormat();
  const muted = (text: string) => <span className="text-muted">{text}</span>;

  return (
    <>
      <title>{`${a.name} | New Machines`}</title>
      <PageHeader title={a.name} lede={a.summary}>
        <div className="mb-2 flex flex-wrap items-center gap-2 text-sm text-muted">
          <span>{t("publisherVersion", { publisher: a.publisher, version: a.version })}</span>
          {a.source === "sample" ? <SimTag>{t("sample")}</SimTag> : null}
          {a.source !== "sample" && a.certified ? <Pill tone="ink">{t("certified")}</Pill> : null}
        </div>
      </PageHeader>

      {a.source === "sample" ? <p className="mb-6 text-sm text-muted">{t("sampleNote")}</p> : null}

      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-6">
          <Section title={t("capabilities")}>
            <div className="px-5 py-4">
              <div className="flex flex-wrap gap-1.5">
                {a.capabilities.map((c) => (
                  <Id key={c} className="rounded bg-grey-100 px-1.5 py-0.5 text-[11px]">
                    {c}
                  </Id>
                ))}
              </div>
              <p className="mt-2 text-sm text-muted">{t("capabilitiesNote")}</p>
            </div>
          </Section>

          <Section title={t("skills")}>
            {a.skills.length ? (
              <ul className="divide-y divide-rule">
                {a.skills.map((s) => (
                  <li key={s.key} className="px-5 py-3 text-sm">
                    {s.title}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-5 py-4 text-sm text-muted">{t("noSkills")}</p>
            )}
          </Section>

          <Section title={t("usedIn")}>
            {a.usedBy.length ? (
              <ul className="grid gap-3 p-4 sm:grid-cols-2">
                {a.usedBy.map((p) => (
                  <li key={p.slug}>
                    <Link
                      href={`/app/marketplace/${encodeURIComponent(p.slug)}`}
                      className="flex items-center gap-3 rounded-md border border-rule p-3 transition-colors hover:border-grey-300"
                    >
                      <PackIcon slug={p.slug} />
                      <span className="min-w-0 flex-1 text-sm font-medium">{p.name}</span>
                      <ChevronRight className="size-4 shrink-0 text-grey-500" aria-hidden />
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-5 py-4 text-sm text-muted">{t("notUsed")}</p>
            )}
          </Section>
        </div>

        <div className="space-y-6">
          <Section title={t("details")}>
            <div className="px-5 py-2">
              <KeyValues
                rows={[
                  { label: t("model"), value: a.modelProfile ? t(`profile.${a.modelProfile}`) : muted(t("noProfile")) },
                  {
                    label: t("tools"),
                    value: a.tools.length ? (
                      <span className="flex flex-wrap gap-1.5">
                        {a.tools.map((tool) => (
                          <Id key={tool}>{tool}</Id>
                        ))}
                      </span>
                    ) : (
                      muted(t("noTools"))
                    ),
                  },
                  { label: t("regions"), value: list(a.regions) },
                ]}
              />
            </div>
          </Section>
        </div>
      </div>
    </>
  );
}

function AgentSkeleton() {
  return (
    <div className="space-y-5">
      <Skeleton className="h-16 w-2/3" />
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Skeleton className="h-80" />
        <Skeleton className="h-48" />
      </div>
    </div>
  );
}
