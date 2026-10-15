"use client";

import { Check, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { PackIcon } from "@/components/pack-icon";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import {
  ActorGlyph,
  ActorLabel,
  Amount,
  ButtonLink,
  EmptyState,
  OutcomeRail,
  RunStatusPill,
  SimTag,
} from "@/components/ui";
import { cn } from "@/lib/cn";
import { useNow } from "@/lib/clock";
import { sumMoney } from "@/lib/format";
import { usePacks } from "@/lib/queries/catalog";
import { missingApps, useAttention, useConnections } from "@/lib/queries/org";
import { useRuns } from "@/lib/queries/runs";
import { useUsage } from "@/lib/queries/workspace";
import { daysLeftInMonth, monthOf, spendSplit } from "@/lib/spend";
import type { Connection, Pack, RunSummary, Usage } from "@/lib/types";
import { useFormat } from "@/lib/use-format";
import { AskBox } from "./ask-box";
import { InvitationNotices } from "./invitation-notice";

type Step = { key: "hire" | "connect" | "run"; done: boolean; href: string };

/** The getting-started steps, each ticked from real data: hired packs, their apps' connections, and runs. */
export function gettingStartedSteps(packs: Pack[], conns: Connection[], runs: RunSummary[]): Step[] {
  const hired = packs.filter((p) => p.installed);
  const missing = missingApps(
    hired.flatMap((p) => p.connectors.map((c) => c.app)),
    conns,
  );
  return [
    { key: "hire", done: hired.length > 0, href: "/app/marketplace" },
    { key: "connect", done: hired.length > 0 && missing.length === 0, href: "/app/connections" },
    { key: "run", done: runs.length > 0, href: hired[0] ? `/app/runs/new?pack=${hired[0].slug}` : "/app/runs/new" },
  ];
}

/** When a pack last started a run, from the runs the page already lists; undefined when it never has. */
export function lastRunOf(slug: string, runs: RunSummary[]): string | undefined {
  return runs
    .filter((r) => r.packSlug === slug)
    .map((r) => r.startedAt)
    .sort()
    .at(-1);
}

function Card({ title, aside, children }: { title: string; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section>
      <div className="mb-2.5 flex items-center justify-between gap-3 px-1">
        <h2 className="text-sm font-medium">{title}</h2>
        {aside}
      </div>
      <div className="panel overflow-hidden">{children}</div>
    </section>
  );
}

/** Shown until the workspace has a hired pack and a run: hire, connect, start. */
function GettingStarted() {
  const t = useTranslations("overview.start");
  const packs = usePacks();
  const conns = useConnections();
  const runs = useRuns();
  if (!packs.data || !conns.data || !runs.data) return null;
  if (packs.data.some((p) => p.installed) && runs.data.length > 0) return null;
  const steps = gettingStartedSteps(packs.data, conns.data, runs.data);
  return (
    <Card title={t("title")} aside={<span className="text-xs text-muted">{t("lede")}</span>}>
      <ol className="divide-y divide-rule">
        {steps.map((s, i) => (
          <li key={s.key}>
            <Link href={s.href} className="flex items-start gap-3 px-4 py-3 hover:bg-grey-50/70">
              <span
                className={cn(
                  "mt-0.5 grid size-5 shrink-0 place-items-center rounded-full text-[11px] font-semibold",
                  s.done ? "bg-ink text-paper" : "border border-grey-300 text-grey-700",
                )}
              >
                {s.done ? <Check className="size-3" strokeWidth={2.5} aria-label={t("done")} /> : i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className={cn("text-sm font-medium", s.done && "text-muted")}>{t(`${s.key}.title`)}</div>
                <div className="mt-0.5 text-[13px] text-muted">{t(`${s.key}.detail`)}</div>
              </div>
              <ChevronRight className="mt-0.5 size-4 text-grey-300" aria-hidden />
            </Link>
          </li>
        ))}
      </ol>
      <p className="border-t border-rule bg-stage/60 px-4 py-2.5 text-xs text-muted">
        {t("reviewerPrompt")}{" "}
        <Link href="/work" className="link">
          {t("reviewerLink")}
        </Link>
      </p>
    </Card>
  );
}

/** The month's spend against the cap, split into plan, agents and tools, and reviewer pay. */
function Budget({ usage: { org, ledger } }: { usage: Usage }) {
  const t = useTranslations("overview");
  const tc = useTranslations("common");
  const { monthName } = useFormat();
  const now = new Date(useNow());
  const split = spendSplit(org, ledger, monthOf(now));
  const cap = org.monthlyCap.amountMinor;
  const pct = (m: number) => `${cap > 0 ? Math.min(100, (m / cap) * 100) : 0}%`;
  return (
    <>
      <div className="flex items-center justify-between px-4 pt-3.5">
        <span className="text-sm font-medium">{t("daysLeft", { n: daysLeftInMonth(now), month: monthName(now) })}</span>
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
          <Amount value={org.monthSpent} />
          <Amount value={org.monthlyCap} />
        </div>
        <div
          className="mt-2 flex h-1.5 overflow-hidden rounded-full bg-grey-200"
          role="img"
          aria-label={t("shareLabel")}
        >
          <div className="h-full bg-ink" style={{ width: pct(split.plan.amountMinor) }} />
          <div className="h-full bg-machine" style={{ width: pct(split.agents.amountMinor) }} />
          <div className="h-full bg-human" style={{ width: pct(split.reviewers.amountMinor) }} />
        </div>
      </div>
      <dl className="divide-y divide-rule px-4 pb-1 text-sm">
        {[
          { k: t("plan", { plan: org.plan }), v: split.plan, c: "bg-ink" },
          { k: tc("agentsModelsTools"), v: split.agents, c: "bg-machine" },
          { k: tc("reviewerPay"), v: split.reviewers, c: "bg-human" },
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
}

/** No runs yet: start one of the hired packs, or hire one first. */
function NoRuns({ packs }: { packs: Pack[] }) {
  const t = useTranslations("overview");
  const hired = packs.find((p) => p.installed);
  return (
    <EmptyState
      action={
        <ButtonLink
          href={hired ? `/app/runs/new?pack=${hired.slug}` : "/app/marketplace"}
          variant="secondary"
          className="h-8"
        >
          {hired ? t("startFirstRun") : t("browseMarketplace")}
        </ButtonLink>
      }
    >
      {hired ? t("noRuns") : t("noRunsNoPacks")}
    </EmptyState>
  );
}

export function Overview() {
  const t = useTranslations("overview");
  const { ago, money } = useFormat();
  const usage = useUsage();
  const runs = useRuns();
  const attention = useAttention();
  const packs = usePacks();

  return (
    <div className="space-y-6">
      <InvitationNotices />
      <AskBox />
      <GettingStarted />

      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(340px,400px)_1fr]">
        <div className="space-y-6">
          <Card title={t("budget")}>
            <QueryState query={usage} skeleton={<Skeleton className="h-72 rounded-none" />}>
              {(u) => <Budget usage={u} />}
            </QueryState>
          </Card>

          <Card
            title={t("needsYou")}
            aside={attention.data?.length ? <span className="text-xs text-muted">{attention.data.length}</span> : null}
          >
            <QueryState query={attention} skeleton={<Skeleton className="h-40 rounded-none" />}>
              {(items) =>
                items.length === 0 ? (
                  // Nothing waiting is the usual state: one quiet line, not an empty box.
                  <p className="px-4 py-3 text-[13px] leading-relaxed text-muted">{t("nothingNeedsYou")}</p>
                ) : (
                  <ul className="divide-y divide-rule">
                    {items.map((item) => (
                      <li key={`${item.href}-${item.title}`}>
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
                )
              }
            </QueryState>
          </Card>
        </div>

        <div className="space-y-6">
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
                  {(allPacks) =>
                    rows.length === 0 ? (
                      <NoRuns packs={allPacks} />
                    ) : (
                      <ul className="divide-y divide-rule">
                        {rows.map((r) => {
                          // The pack is named once: under the title only when the run is called something else.
                          const packName = allPacks.find((p) => p.slug === r.packSlug)?.name;
                          const sub = packName && packName !== r.title ? packName : undefined;
                          const when = ago(r.startedAt);
                          const body = (
                            <>
                              <PackIcon slug={r.packSlug} />
                              <div className="min-w-0">
                                <div className="line-clamp-2 text-sm font-medium break-words">{r.title}</div>
                                {/* Below md the summary column is gone, so the time and status sit under the title. */}
                                <div className="truncate text-[13px] text-muted">
                                  <span className="hidden md:inline">{sub}</span>
                                  <span className="md:hidden">{[sub, when].filter(Boolean).join(" · ")}</span>
                                </div>
                                <div className="mt-1.5 lg:hidden">
                                  <RunStatusPill status={r.status} />
                                </div>
                              </div>
                              <div className="hidden min-w-0 md:block">
                                <div className="line-clamp-2 text-[13px] break-words">{r.summary}</div>
                                <div className="text-[13px] text-muted">{when}</div>
                              </div>
                              <div className="hidden justify-self-start lg:block">
                                <RunStatusPill status={r.status} />
                              </div>
                              <div className="hidden 2xl:block">
                                <OutcomeRail compact stages={r.stages} />
                              </div>
                              <span className="tnum text-right text-sm">
                                {money(sumMoney(r.spent.ai, r.spent.human, r.spent.tools))}
                              </span>
                              <ChevronRight className="size-4 text-grey-300" aria-hidden />
                            </>
                          );
                          // The status column is as wide as its widest pill, so the title and summary share the rest.
                          const cls =
                            "grid grid-cols-[36px_minmax(0,1fr)_auto_16px] items-center gap-x-3 px-4 py-3.5 sm:gap-x-4 md:grid-cols-[36px_minmax(0,1.2fr)_minmax(0,1fr)_auto_16px] lg:grid-cols-[36px_minmax(0,1.2fr)_minmax(0,1fr)_auto_64px_16px] 2xl:grid-cols-[36px_minmax(0,1.2fr)_minmax(0,1fr)_auto_96px_64px_16px]";
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
                    )
                  }
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

          <Card
            title={t("hiredPacks")}
            aside={
              <Link href="/app/marketplace" className="text-xs text-muted hover:text-ink">
                {t("findMore")}
              </Link>
            }
          >
            <QueryState query={packs} skeleton={<Skeleton className="h-40 rounded-none" />}>
              {(list) =>
                list.some((p) => p.installed) ? (
                  <ul className="divide-y divide-rule">
                    {list
                      .filter((p) => p.installed)
                      .map((p) => {
                        // Read from the runs list on this page, so it agrees with the Runs card beside it.
                        const last = runs.data && lastRunOf(p.slug, runs.data);
                        return (
                          <li key={p.slug}>
                            <Link
                              href={`/app/marketplace/${p.slug}`}
                              className="flex items-center gap-3 px-4 py-2.5 hover:bg-grey-50/70"
                            >
                              <PackIcon slug={p.slug} className="size-7" />
                              <div className="min-w-0 flex-1">
                                <div className="truncate text-sm">{p.name}</div>
                                {runs.data ? (
                                  <div className="text-xs text-muted">
                                    {last ? t("lastRun", { when: ago(last) }) : t("noRunsYet")}
                                  </div>
                                ) : null}
                              </div>
                            </Link>
                          </li>
                        );
                      })}
                  </ul>
                ) : (
                  <EmptyState
                    action={
                      <ButtonLink href="/app/marketplace" variant="secondary" className="h-8">
                        {t("browseMarketplace")}
                      </ButtonLink>
                    }
                  >
                    {t("noPacks")}
                  </EmptyState>
                )
              }
            </QueryState>
          </Card>
        </div>
      </div>
    </div>
  );
}
