"use client";

import { useTranslations } from "next-intl";
import { useQueryState } from "nuqs";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { ButtonLink, Callout, PageHeader } from "@/components/ui";
import { usePacks } from "@/lib/queries/catalog";
import { isUsable, missingApps, useConnections, useOrg } from "@/lib/queries/org";
import { packRunFee } from "@/lib/run-budget";
import type { Connection, Organization, Pack } from "@/lib/types";
import { useFormat } from "@/lib/use-format";
import { type Refusal, StartRunForm } from "./start-run-form";

// Free-text inputs per connected app, for packs without an input schema (the demo workspace's packs).
const INPUTS: Record<string, string[]> = {
  "Google Sheets": ["Google Sheets: Orders Oct 11", "Google Sheets: Stripe payouts, October"],
  Gmail: ["Gmail: Accounts receivable inbox"],
  "Google Drive": ["Google Drive: Reorder lists"],
  Shopify: ["Shopify: Refund requests (sandbox)"],
};

/** Why each hired pack can't start a run right now (apps not connected, the monthly cap reached), by slug. */
function useBlocked(hired: Pack[], conns: Connection[], org: Organization | undefined) {
  const t = useTranslations("runs.new");
  const { list, money } = useFormat();
  const capReached = org !== undefined && org.monthSpent.amountMinor >= org.monthlyCap.amountMinor;
  const blocked: Record<string, Refusal | undefined> = {};
  for (const p of hired) {
    const missing = missingApps(
      p.connectors.map((c) => c.app),
      conns,
    );
    if (missing.length)
      blocked[p.slug] = {
        text: t("appsMissing", { apps: list(missing), name: p.name }),
        href: "/app/connections",
        action: t("goConnections"),
      };
    else if (capReached)
      blocked[p.slug] = {
        text: t("capReached", { cap: money(org.monthlyCap) }),
        href: "/app/usage",
        action: t("seeUsage"),
      };
  }
  return blocked;
}

function StartRunBody({ list, conns, pack }: { list: Pack[]; conns: Connection[]; pack: string | null }) {
  const t = useTranslations("runs.new");
  const org = useOrg();
  const hired = list.filter((p) => p.installed);
  const blocked = useBlocked(hired, conns, org.data);
  // Connected or sandbox: the API's start gate has the final say on which apps count.
  const connected = new Set(conns.filter(isUsable).map((c) => c.app));
  const startable = hired.map((p) => ({
    slug: p.slug,
    name: p.name,
    inputs: p.connectors.filter((c) => connected.has(c.app)).flatMap((c) => INPUTS[c.app] ?? []),
    perRunCap: p.perRunCap,
    maxBudget: p.maxBudget,
    packFee: packRunFee(p),
    runBudgetLimit: p.runBudgetLimit,
  }));
  // A `?pack=` that can't be started (not hired, or unknown) is explained, and the form waits: another pack is
  // never chosen in its place.
  const unstartable = pack && !startable.some((p) => p.slug === pack) ? pack : null;
  if (unstartable) return <UnstartablePack slug={unstartable} name={list.find((p) => p.slug === unstartable)?.name} />;
  return (
    <>
      {startable.length ? (
        <StartRunForm packs={startable} defaultPack={pack ?? undefined} blocked={blocked} />
      ) : (
        <Callout
          tone="warn"
          title={t("noHiredPacks")}
          action={
            <ButtonLink href="/app/marketplace" variant="secondary" className="h-8 shrink-0">
              {t("seeAllPacks")}
            </ButtonLink>
          }
        />
      )}
    </>
  );
}

export function StartRunPage() {
  const t = useTranslations("runs.new");
  const [pack] = useQueryState("pack");
  const packs = usePacks();
  const connections = useConnections();

  return (
    <>
      <title>{`${t("title")} | New Machines`}</title>
      <PageHeader title={t("title")} lede={t("lede")} />
      <div className="panel max-w-2xl p-6">
        <QueryState query={packs} skeleton={<Skeleton className="h-72" />}>
          {(list) => (
            <QueryState query={connections} skeleton={<Skeleton className="h-72" />}>
              {(conns) => <StartRunBody list={list} conns={conns} pack={pack} />}
            </QueryState>
          )}
        </QueryState>
      </div>
    </>
  );
}

/** Shown instead of the form when the link asked for a pack that can't start a run: add it first. */
function UnstartablePack({ slug, name }: { slug: string; name?: string }) {
  const t = useTranslations("runs.new");
  return (
    <div>
      <Callout
        tone="warn"
        title={name ? t("notHired", { name }) : t("unknownPack", { slug })}
        action={
          <ButtonLink
            href={name ? `/app/marketplace/${slug}` : "/app/marketplace"}
            variant="secondary"
            className="h-8 shrink-0"
          >
            {name ? t("hireThis") : t("seeAllPacks")}
          </ButtonLink>
        }
      />
    </div>
  );
}
