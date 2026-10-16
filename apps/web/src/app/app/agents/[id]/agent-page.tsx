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
import { useFeeLabel } from "@/lib/listing-fee";
import { useAgent } from "@/lib/queries/catalog";
import { shownVersion } from "@/lib/shown-version";
import { useFormat } from "@/lib/use-format";
import type { Agent } from "@/lib/types";
import { useCapabilityLabel } from "../capability-label";

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
  const tl = useTranslations("listedMarket");
  const fee = useFeeLabel();
  const { list } = useFormat();
  const label = useCapabilityLabel();
  const muted = (text: string) => <span className="text-muted">{text}</span>;

  return (
    <>
      <title>{`${a.name} | New Machines`}</title>
      <PageHeader title={a.name} lede={a.summary}>
        <div className="mb-2 flex flex-wrap items-center gap-2 text-sm text-muted">
          {/* A listed agent's publisher is on the "By" line beside its fee. */}
          <span>
            {a.listing
              ? tl("version", { version: shownVersion(a) })
              : t("publisherVersion", { publisher: a.publisher, version: shownVersion(a) })}
          </span>
          {a.listing ? (
            <span>
              {tl("by", { publisher: a.listing.publisher })}
              {" · "}
              <span className="tnum">{fee(a.listing)}</span>
            </span>
          ) : null}
          {a.source === "sample" ? <SimTag>{t("sample")}</SimTag> : null}
          {a.source !== "sample" && a.certified ? <Pill tone="ink">{t("certified")}</Pill> : null}
        </div>
      </PageHeader>

      {a.source === "sample" ? <p className="mb-6 text-sm text-muted">{t("sampleNote")}</p> : null}

      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-6">
          <Section title={t("capabilities")}>
            <div className="px-5 py-4">
              <ul className="flex flex-wrap gap-1.5">
                {a.capabilities.map((c) => (
                  <li key={c} className="rounded bg-grey-100 px-2 py-1 text-sm text-grey-700">
                    {label(c)}
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-sm text-muted">{t("capabilitiesNote")}</p>
              {/* The ids a policy or a definition file names; of no use in the main view. */}
              {a.capabilities.length ? (
                <details className="mt-3 text-sm">
                  <summary className="cursor-pointer text-muted hover:text-ink">{t("technical")}</summary>
                  <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
                    <dt className="text-muted">{t("capabilityIds")}</dt>
                    <dd className="flex flex-wrap gap-x-3 gap-y-1">
                      {a.capabilities.map((c) => (
                        <Id key={c}>{c}</Id>
                      ))}
                    </dd>
                  </dl>
                </details>
              ) : null}
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
