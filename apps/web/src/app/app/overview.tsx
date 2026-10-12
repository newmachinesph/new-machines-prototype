"use client";

import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { PackIcon } from "@/components/pack-icon";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { ActorGlyph, ActorLabel, Amount, OutcomeRail, RunStatusPill, SimTag } from "@/components/ui";
import { sumMoney, usd } from "@/lib/format";
import { usePacks } from "@/lib/queries/catalog";
import { useAttention, useOrg } from "@/lib/queries/org";
import { useRuns } from "@/lib/queries/runs";
import { useFormat } from "@/lib/use-format";
import { AskBox } from "./ask-box";

// Buyer-side split for October, matching the simulated ledger. The $4.00 reviewer pay on the
// failed run_1036 was absorbed by the platform, so it is not part of the buyer's spend.
const SPLIT = { reviewers: usd(750), plan: usd(4900) };

function Card({ title, aside, children }: { title: string; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section>
      <div className="mb-2.5 flex items-center justify-between px-1">
        <h2 className="text-sm font-medium">{title}</h2>
        {aside}
      </div>
      <div className="panel overflow-hidden">{children}</div>
    </section>
  );
}

export function Overview() {
  const t = useTranslations("overview");
  const tc = useTranslations("common");
  const { ago, money } = useFormat();
  const org = useOrg();
  const runs = useRuns();
  const attention = useAttention();
  const packs = usePacks();

  return (
    <div className="space-y-6">
      <AskBox />

      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(340px,400px)_1fr]">
        <div className="space-y-6">
          <Card title={t("budget")}>
            <QueryState query={org} skeleton={<Skeleton className="h-72 rounded-none" />}>
              {(ORG) => {
                const pct = (m: number) => `${(m / ORG.monthlyCap.amountMinor) * 100}%`;
                const agentsAndTools = usd(
                  ORG.monthSpent.amountMinor - SPLIT.plan.amountMinor - SPLIT.reviewers.amountMinor,
                );
                return (
                  <>
                    <div className="flex items-center justify-between px-4 pt-3.5">
                      <span className="text-sm font-medium">{t("daysLeft", { n: 19 })}</span>
                      <Link
                        href="/app/usage"
                        className="rounded-md border border-rule px-2.5 py-1 text-xs font-medium hover:border-grey-300"
                      >
                        {t("billing")}
                      </Link>
                    </div>
                    <div className="m-3 rounded-md bg-stage px-3 py-2.5">
                      <div className="flex justify-between text-xs text-muted">
                        <span>{t("spent")}</span>
                        <span>{t("cap")}</span>
                      </div>
                      <div className="mt-0.5 flex justify-between text-sm font-medium">
                        <Amount value={ORG.monthSpent} />
                        <Amount value={ORG.monthlyCap} />
                      </div>
                      <div
                        className="mt-2 flex h-1.5 overflow-hidden rounded-full bg-grey-200"
                        role="img"
                        aria-label={t("shareLabel")}
                      >
                        <div className="h-full bg-ink" style={{ width: pct(SPLIT.plan.amountMinor) }} />
                        <div className="h-full bg-machine" style={{ width: pct(agentsAndTools.amountMinor) }} />
                        <div className="h-full bg-human" style={{ width: pct(SPLIT.reviewers.amountMinor) }} />
                      </div>
                    </div>
                    <dl className="divide-y divide-rule px-4 pb-1 text-sm">
                      {[
                        { k: t("plan"), v: SPLIT.plan, c: "bg-ink" },
                        { k: tc("agentsModelsTools"), v: agentsAndTools, c: "bg-machine" },
                        { k: tc("reviewerPay"), v: SPLIT.reviewers, c: "bg-human" },
                      ].map((r) => (
                        <div key={r.k} className="flex items-center justify-between py-2.5">
                          <dt className="flex items-center gap-2 text-grey-700">
                            <span className={`size-2 rounded-full ${r.c}`} aria-hidden />
                            {r.k}
                          </dt>
                          <dd>
                            <Amount value={r.v} />
                          </dd>
                        </div>
                      ))}
                    </dl>
                    <div className="flex items-center justify-between border-t border-rule bg-stage/60 px-4 py-2.5 text-xs text-muted">
                      {t("capNote")}
                      <SimTag />
                    </div>
                  </>
                );
              }}
            </QueryState>
          </Card>

          <Card title={t("needsYou")} aside={<span className="text-xs text-muted">{attention.data?.length}</span>}>
            <QueryState query={attention} skeleton={<Skeleton className="h-40 rounded-none" />}>
              {(items) => (
                <ul className="divide-y divide-rule">
                  {items.map((item) => (
                    <li key={item.title}>
                      <Link href={item.href} className="group flex items-start gap-3 px-4 py-3 hover:bg-grey-50/70">
                        <ActorGlyph actor={item.actor} className="mt-1 size-3" />
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium">{item.title}</div>
                          <div className="mt-0.5 truncate text-[13px] text-muted">{item.detail}</div>
                        </div>
                        <span className="shrink-0 pt-0.5 text-xs text-muted">{ago(item.when)}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </QueryState>
          </Card>

          <Card
            title={t("hiredPacks")}
            aside={
              <Link href="/app/marketplace" className="text-xs text-muted hover:text-ink">
                {t("findMore")}
              </Link>
            }
          >
            <QueryState query={packs} skeleton={<Skeleton className="h-40 rounded-none" />}>
              {(list) => (
                <ul className="divide-y divide-rule">
                  {list
                    .filter((p) => p.installed)
                    .map((p) => (
                      <li key={p.slug}>
                        <Link
                          href={`/app/marketplace/${p.slug}`}
                          className="flex items-center gap-3 px-4 py-2.5 hover:bg-grey-50/70"
                        >
                          <PackIcon slug={p.slug} className="size-7" />
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-sm">{p.name}</div>
                            <div className="text-xs text-muted">
                              {t("packMeta", { version: p.version, n: p.runs30d ?? 0 })}
                            </div>
                          </div>
                        </Link>
                      </li>
                    ))}
                </ul>
              )}
            </QueryState>
          </Card>
        </div>

        <Card
          title={t("runs")}
          aside={
            <Link href="/app/runs" className="text-xs text-muted hover:text-ink">
              {t("viewAll")}
            </Link>
          }
        >
          <QueryState query={runs} skeleton={<Skeleton className="h-96 rounded-none" />}>
            {(rows) => (
              <QueryState query={packs} skeleton={<Skeleton className="h-96 rounded-none" />}>
                {(allPacks) => (
                  <ul className="divide-y divide-rule">
                    {rows.map((r) => {
                      const body = (
                        <>
                          <PackIcon slug={r.packSlug} />
                          <div className="min-w-0">
                            <div className="truncate text-sm font-medium">{r.title}</div>
                            <div className="truncate text-[13px] text-muted">
                              {allPacks.find((p) => p.slug === r.packSlug)?.name}
                            </div>
                          </div>
                          <div className="hidden min-w-0 md:block">
                            <div className="flex items-center gap-2 truncate text-[13px]">
                              <span className="truncate">{r.summary}</span>
                            </div>
                            <div className="text-[13px] text-muted">{ago(r.startedAt)}</div>
                          </div>
                          <div className="hidden justify-self-start lg:block">
                            <RunStatusPill status={r.status} />
                          </div>
                          <div className="hidden 2xl:block">
                            <OutcomeRail compact stages={r.stages} />
                          </div>
                          <span className="tnum hidden w-16 text-right text-sm sm:block">
                            {money(sumMoney(r.spent.ai, r.spent.human, r.spent.tools))}
                          </span>
                          <ChevronRight className="size-4 text-grey-300" aria-hidden />
                        </>
                      );
                      const cls =
                        "grid grid-cols-[36px_1fr_16px] items-center gap-x-4 px-4 py-3.5 sm:grid-cols-[36px_1fr_64px_16px] md:grid-cols-[36px_minmax(0,1fr)_minmax(0,1.1fr)_64px_16px] lg:grid-cols-[36px_minmax(0,1fr)_minmax(0,1.1fr)_190px_64px_16px] 2xl:grid-cols-[36px_minmax(0,1fr)_minmax(0,1.2fr)_190px_96px_64px_16px]";
                      return (
                        <li key={r.id}>
                          {r.hasDetail ? (
                            <Link href={`/app/runs/${r.id}`} className={`${cls} hover:bg-grey-50/70`}>
                              {body}
                            </Link>
                          ) : (
                            <div className={cls}>{body}</div>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </QueryState>
            )}
          </QueryState>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-rule bg-stage/60 px-4 py-2.5 text-xs text-muted">
            <span className="flex items-center gap-1.5">
              <ActorGlyph actor="machine" className="size-2.5" />
              <ActorLabel actor="machine" />
            </span>
            <span className="flex items-center gap-1.5">
              <ActorGlyph actor="human" className="size-2.5" />
              <ActorLabel actor="human" />
            </span>
            <span className="flex items-center gap-1.5">
              <ActorGlyph actor="policy" className="size-2.5" />
              <ActorLabel actor="policy" />
            </span>
            <span className="flex items-center gap-1.5">
              <ActorGlyph actor="buyer" className="size-2.5" />
              <ActorLabel actor="buyer" />
            </span>
            <span className="hidden 2xl:inline">{t("outcomeMarks")}</span>
          </div>
        </Card>
      </div>
    </div>
  );
}
