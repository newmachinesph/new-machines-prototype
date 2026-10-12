"use client";

import { useTranslations } from "next-intl";
import { useQueryState } from "nuqs";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { ButtonLink, Callout, PageHeader } from "@/components/ui";
import { usePacks } from "@/lib/queries/catalog";
import { useConnections } from "@/lib/queries/org";
import { StartRunForm } from "./start-run-form";

// Demo inputs per connected app. The dynamic backend lists real sheets and files from Composio.
const INPUTS: Record<string, string[]> = {
  "Google Sheets": ["Google Sheets: Orders Oct 11", "Google Sheets: Stripe payouts, October"],
  Gmail: ["Gmail: Accounts receivable inbox"],
  "Google Drive": ["Google Drive: Reorder lists"],
  Shopify: ["Shopify: Refund requests (sandbox)"],
};

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
              {(conns) => {
                const connected = new Set(conns.filter((c) => c.status === "connected").map((c) => c.app));
                const startable = list
                  .filter((p) => p.installed)
                  .map((p) => ({
                    slug: p.slug,
                    name: p.name,
                    inputs: p.connectors.filter((c) => connected.has(c.app)).flatMap((c) => INPUTS[c.app] ?? []),
                  }));
                // A `?pack=` that can't be started (not hired, or unknown) is explained, never silently swapped.
                const blocked = pack && !startable.some((p) => p.slug === pack) ? pack : null;
                return (
                  <>
                    {blocked ? (
                      <UnstartablePack slug={blocked} name={list.find((p) => p.slug === blocked)?.name} />
                    ) : null}
                    <StartRunForm packs={startable} defaultPack={blocked ? undefined : (pack ?? undefined)} />
                  </>
                );
              }}
            </QueryState>
          )}
        </QueryState>
      </div>
    </>
  );
}

/** Shown above the form when the link asked for a pack that can't start a run. */
function UnstartablePack({ slug, name }: { slug: string; name?: string }) {
  const t = useTranslations("runs.new");
  return (
    <div className="mb-6">
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
