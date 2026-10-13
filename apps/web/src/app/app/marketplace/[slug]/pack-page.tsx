"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { notFound } from "next/navigation";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { ActorGlyph, ButtonLink, Id, KeyValues, MockTag, PageHeader, Pill, Section } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import { useAgentById, useAgents, usePack } from "@/lib/queries/catalog";
import { useFormat } from "@/lib/use-format";
import { SandboxTrial } from "./sandbox-trial";

export function PackPage({ slug }: { slug: string }) {
  const t = useTranslations("marketplace.pack");
  const tc = useTranslations("common");
  const { money, list } = useFormat();
  const packQuery = usePack(slug);
  const agentsQuery = useAgents();
  const agentById = useAgentById();
  if (packQuery.error instanceof ApiError && packQuery.error.status === 404) notFound();

  return (
    <QueryState query={packQuery} skeleton={<Skeleton className="h-96" />}>
      {(p) => (
        <QueryState query={agentsQuery} skeleton={<Skeleton className="h-96" />}>
          {() => {
            const passport = p.passport;
            return (
              <>
                <title>{`${p.name} | New Machines`}</title>
                <PageHeader
                  title={p.name}
                  lede={p.description}
                  actions={
                    p.installed ? (
                      <ButtonLink href="/app/runs" variant="secondary">
                        {t("seeRuns")}
                      </ButtonLink>
                    ) : (
                      <ButtonLink href={`/app/marketplace/${p.slug}/install`}>{t("reviewHire")}</ButtonLink>
                    )
                  }
                >
                  <div className="mb-2 flex flex-wrap items-center gap-2 text-sm text-muted">
                    <span>{t("publisherVersion", { publisher: p.publisher, version: p.version })}</span>
                    {p.installed ? <Pill tone="ink">{t("hired")}</Pill> : null}
                    {!p.certified ? <Pill tone="quiet">{t("notCertified")}</Pill> : null}
                  </div>
                </PageHeader>

                <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
                  <div className="space-y-6">
                    <Section title={t("whoWorks")}>
                      <ul className="divide-y divide-rule">
                        {p.agents.map((id) => {
                          const a = agentById(id);
                          if (!a) return null;
                          return (
                            <li key={id} className="px-5 py-4">
                              <div className="flex items-center gap-2 font-medium">
                                <ActorGlyph actor="machine" />
                                <Link href={`/app/agents/${encodeURIComponent(a.id)}`} className="hover:underline">
                                  {a.name}
                                </Link>{" "}
                                <span className="text-xs font-normal text-muted">
                                  {a.version}, {a.publisher}
                                </span>
                              </div>
                              <p className="mt-1 pl-5 text-sm text-grey-700">{a.summary}</p>
                              <div className="mt-2 flex flex-wrap gap-1.5 pl-5">
                                {a.capabilities.map((c) => (
                                  <Id key={c} className="rounded bg-grey-100 px-1.5 py-0.5 text-[11px]">
                                    {c}
                                  </Id>
                                ))}
                              </div>
                            </li>
                          );
                        })}
                        <li className="px-5 py-4">
                          <div className="flex items-center gap-2 font-medium">
                            <ActorGlyph actor="human" />
                            {t("humanReviewers")}
                          </div>
                          <p className="mt-1 pl-5 text-sm text-grey-700">{p.humanReview}</p>
                        </li>
                      </ul>
                    </Section>

                    {passport ? (
                      <Section title={t("passport")} aside={<Pill tone="quiet">{t("passportBadge")}</Pill>}>
                        <div className="px-5 py-4">
                          <p className="text-sm text-grey-700">
                            {t("passportIntro", {
                              date: passport.testedOn,
                              by: passport.testedBy,
                              n: passport.sampleSize,
                              cohort: passport.cohort,
                            })}
                          </p>
                          <table className="mt-4 w-full text-sm">
                            <tbody className="divide-y divide-rule">
                              {passport.results.map((r) => (
                                <tr key={r.label}>
                                  <td className="py-2.5 pr-4">{r.label}</td>
                                  <td className="w-48 py-2.5">
                                    <div className="flex items-center gap-3">
                                      <div
                                        className="h-1.5 flex-1 overflow-hidden rounded-full bg-grey-100"
                                        aria-hidden
                                      >
                                        <div
                                          className="h-full bg-ink"
                                          style={{ width: `${(r.value / passport.sampleSize) * 100}%` }}
                                        />
                                      </div>
                                      <span className="tnum w-14 text-right">
                                        {t("outOf", { value: r.value, total: passport.sampleSize })}
                                      </span>
                                    </div>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          <div className="mt-5 grid gap-5 sm:grid-cols-2">
                            <div>
                              <h3 className="label mb-1.5">{t("limitations")}</h3>
                              <ul className="list-disc space-y-1 pl-4 text-sm text-grey-700">
                                {passport.limitations.map((l) => (
                                  <li key={l}>{l}</li>
                                ))}
                              </ul>
                            </div>
                            <div>
                              <h3 className="label mb-1.5">{t("retested")}</h3>
                              <ul className="list-disc space-y-1 pl-4 text-sm text-grey-700">
                                {passport.retestTriggers.map((l) => (
                                  <li key={l}>{l}</li>
                                ))}
                              </ul>
                            </div>
                          </div>
                        </div>
                      </Section>
                    ) : (
                      <Section title={t("passport")}>
                        <p className="px-5 py-4 text-sm text-muted">
                          {p.certified ? t("refreshing") : t("uncertifiedNote")}
                        </p>
                      </Section>
                    )}

                    <SandboxTrial pack={p} />
                  </div>

                  <div className="space-y-6">
                    <Section title={t("costs")}>
                      <div className="px-5 py-2">
                        <KeyValues
                          rows={[
                            {
                              label: t("agentsTools"),
                              value: (
                                <span className="tnum">
                                  {t("perRun", { min: money(p.estimate.aiMin), max: money(p.estimate.aiMax) })}
                                </span>
                              ),
                            },
                            {
                              label: tc("reviewerPay"),
                              value: p.estimate.humanMax.amountMinor ? (
                                <span className="tnum">{t("upTo", { amount: money(p.estimate.humanMax) })}</span>
                              ) : (
                                t("noneByDefault")
                              ),
                            },
                            {
                              label: t("basis"),
                              value: t("basisValue"),
                            },
                          ]}
                        />
                      </div>
                    </Section>
                    <Section title={t("touches")}>
                      <ul className="divide-y divide-rule">
                        {p.connectors.map((k) => (
                          <li key={k.app} className="flex items-center justify-between gap-2 px-5 py-3 text-sm">
                            <span className="flex items-center gap-2">
                              {k.app}
                              {k.mocked ? <MockTag /> : null}
                            </span>
                            <span className={k.access === "read" ? "text-grey-700" : "text-human"}>
                              {t(`access.${k.access}`)}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </Section>
                    <Section title={t("dataRisk")}>
                      <div className="px-5 py-2">
                        <KeyValues
                          rows={[
                            { label: t("processedIn"), value: list(p.regions) },
                            { label: t("riskClass"), value: t(`risk.${p.riskClass}`) },
                            {
                              label: t("publisherSees"),
                              value: t("publisherSeesValue"),
                            },
                          ]}
                        />
                      </div>
                    </Section>
                  </div>
                </div>
              </>
            );
          }}
        </QueryState>
      )}
    </QueryState>
  );
}
