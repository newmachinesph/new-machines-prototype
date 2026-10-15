"use client";

import { Check, Search } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { parseAsString, useQueryState } from "nuqs";
import { PackIcon } from "@/components/pack-icon";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { ActorGlyph, ButtonLink, MockTag, Pill } from "@/components/ui";
import { cn } from "@/lib/cn";
import { useAgentById, useAgents, usePacks, useTaxonomy } from "@/lib/queries/catalog";
import { useIsLive } from "@/lib/queries/me";
import { useFormat } from "@/lib/use-format";
import { useCanBuild } from "@/app/studio/can-build";
import { usePerRunPrice } from "./per-run";

// Sentinel values double as the `category` URL parameter, so they stay English; the labels shown are translated.
const ALL = "All packs";
const HIRED = "Added";
const TEAM = "Built by your team";
const ALL_INDUSTRIES = "";

type Filter = { label: string; text: string; n: number };

/** One group of the filter nav: a small heading and its toggles, each with the number of packs it shows. */
function FilterGroup({
  title,
  filters,
  active,
  onPick,
}: {
  title: string;
  filters: Filter[];
  active: string;
  onPick: (label: string) => void;
}) {
  return (
    <div role="group" aria-label={title}>
      <span className="label mb-1 block">{title}</span>
      {/* One scrolling row on small screens; a column beside the packs from xl, where long names wrap. */}
      <div className="flex [scrollbar-width:none] gap-1 overflow-x-auto xl:flex-col xl:overflow-visible">
        {filters.map((f) => (
          <button
            key={f.label}
            type="button"
            aria-pressed={active === f.label}
            onClick={() => onPick(f.label)}
            className={cn(
              "flex min-h-9 shrink-0 items-center justify-between gap-3 rounded-md px-3 text-left text-sm whitespace-nowrap xl:py-1.5 xl:whitespace-normal",
              active === f.label ? "bg-grey-100 font-medium text-ink" : "text-grey-700 hover:bg-grey-50 hover:text-ink",
            )}
          >
            <span className="min-w-0">{f.text}</span>
            <span className="tnum shrink-0 text-xs text-muted">{f.n}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

export function PackGrid() {
  const t = useTranslations("marketplace.grid");
  const { list } = useFormat();
  const perRun = usePerRunPrice();
  const packsQuery = usePacks();
  const agentsQuery = useAgents();
  const agentById = useAgentById();
  const [cat, setCat] = useQueryState("category", parseAsString.withDefault(ALL));
  const taxonomy = useTaxonomy();
  const industries = taxonomy.data?.industries ?? [];
  const [industry, setIndustry] = useQueryState("industry", parseAsString.withDefault(ALL_INDUSTRIES));
  const [q, setQ] = useQueryState("q", parseAsString.withDefault(""));
  // Owners and admins of a live workspace can build what the marketplace lacks (the Studio is live only).
  const live = useIsLive();
  const canBuild = useCanBuild();

  return (
    <QueryState query={packsQuery} skeleton={<PackGridSkeleton />}>
      {(PACKS) => (
        <QueryState query={agentsQuery} skeleton={<PackGridSkeleton />}>
          {() => {
            const categories = [...new Set(PACKS.map((p) => p.category))];
            const teamCount = PACKS.filter((p) => p.builtByTeam).length;
            // A ?category= kept from when the org still had a team pack names a view that is no longer offered.
            const view = cat === TEAM && teamCount === 0 ? ALL : cat;
            // Views (All packs, Added, and Built by your team when the org has built one) above the line.
            const views: Filter[] = [
              { label: ALL, text: t("all"), n: PACKS.length },
              { label: HIRED, text: t("hired"), n: PACKS.filter((p) => p.installed).length },
              ...(teamCount > 0 ? [{ label: TEAM, text: t("team"), n: teamCount }] : []),
            ];
            const functions: Filter[] = categories.map((c) => ({
              label: c,
              text: c,
              n: PACKS.filter((p) => p.category === c).length,
            }));
            // Every industry the taxonomy knows, so that an empty one still shows as 0 rather than vanishing.
            const industryFilters: Filter[] = [
              { label: ALL_INDUSTRIES, text: t("allIndustries"), n: PACKS.length },
              ...industries.map((i) => ({
                label: i.id,
                text: i.name,
                n: PACKS.filter((p) => (p.industries ?? []).includes(i.id)).length,
              })),
            ];
            const inView = (p: (typeof PACKS)[number]) =>
              view === ALL || (view === HIRED ? p.installed : view === TEAM ? !!p.builtByTeam : p.category === view);
            const needle = q.trim().toLowerCase();
            const shown = PACKS.filter(
              (p) =>
                (industry === ALL_INDUSTRIES || (p.industries ?? []).includes(industry)) &&
                inView(p) &&
                (!needle ||
                  [p.name, p.outcome, p.publisher, p.category].some((field) => field.toLowerCase().includes(needle))),
            );

            return (
              <div className="grid grid-cols-1 items-start gap-8 xl:grid-cols-[220px_minmax(0,1fr)]">
                <aside className="space-y-5 xl:sticky xl:top-20">
                  <p className="text-sm leading-relaxed text-grey-700">{t("intro")}</p>
                  {/* One filter bar: what to show, then the pack's function and industry (the taxonomy). */}
                  <nav aria-label={t("filterLabel")} className="space-y-4 xl:space-y-5">
                    <FilterGroup
                      title={t("viewsLabel")}
                      filters={views}
                      active={view}
                      onPick={(label) => setCat(label === ALL ? null : label)}
                    />
                    {functions.length > 0 ? (
                      <FilterGroup
                        title={t("functionLabel")}
                        filters={functions}
                        active={view}
                        onPick={(label) => setCat(label)}
                      />
                    ) : null}
                    {industries.length > 0 ? (
                      <FilterGroup
                        title={t("industryLabel")}
                        filters={industryFilters}
                        active={industry}
                        onPick={(label) => setIndustry(label === ALL_INDUSTRIES ? null : label)}
                      />
                    ) : null}
                  </nav>
                  {live && canBuild ? (
                    <div className="space-y-2 border-t border-rule pt-4">
                      <p className="text-sm leading-relaxed text-grey-700">{t("buildOwn")}</p>
                      <ButtonLink href="/studio/packs/new" variant="secondary" className="h-8">
                        {t("buildOwnCta")}
                      </ButtonLink>
                    </div>
                  ) : null}
                  <p className="hidden border-t border-rule pt-4 text-xs leading-relaxed text-muted xl:block">
                    {t("priceNote")}
                  </p>
                </aside>

                <div className="space-y-4">
                  <label className="flex h-9 items-center gap-2 rounded-md border border-rule bg-paper px-3 focus-within:border-grey-500">
                    <Search className="size-4 text-grey-500" strokeWidth={1.75} aria-hidden />
                    <span className="sr-only">{t("search")}</span>
                    <input
                      name="q"
                      type="search"
                      value={q}
                      onChange={(e) => setQ(e.target.value)}
                      placeholder={t("searchPlaceholder")}
                      className="w-full bg-transparent text-sm outline-none placeholder:text-grey-500"
                    />
                  </label>
                  {shown.length === 0 ? (
                    <p className="panel px-5 py-10 text-center text-sm text-muted">
                      {t("noMatch")}{" "}
                      <button
                        type="button"
                        className="link"
                        onClick={() => {
                          setQ(null);
                          setCat(null);
                          setIndustry(null);
                        }}
                      >
                        {t("showAll")}
                      </button>
                    </p>
                  ) : (
                    <ul className="grid [grid-template-columns:repeat(auto-fill,minmax(min(100%,360px),1fr))] gap-4">
                      {shown.map((p) => {
                        // Every app a sandbox mock: say so once for the card, not once per app.
                        const allMocked = p.connectors.length > 0 && p.connectors.every((k) => k.mocked);
                        const price = perRun(p.estimate);
                        return (
                          <li key={p.slug}>
                            <Link
                              href={`/app/marketplace/${p.slug}`}
                              className="panel flex h-full flex-col p-5 transition-colors hover:border-grey-300"
                            >
                              <div className="flex items-start gap-3">
                                <PackIcon slug={p.slug} />
                                <div className="min-w-0 flex-1">
                                  <div className="text-[15px] font-semibold">{p.name}</div>
                                  <div className="mt-0.5 text-xs text-muted">
                                    {t("publisherVersion", { publisher: p.publisher, version: p.version })}
                                  </div>
                                </div>
                                {/* The corner exists only with a badge in it: empty, it would still take its gap. */}
                                {p.builtByTeam || p.installed || !p.certified ? (
                                  <span data-testid="pack-badges" className="flex shrink-0 flex-col items-end gap-1">
                                    {p.builtByTeam ? <Pill tone="machine">{t("team")}</Pill> : null}
                                    {p.installed ? (
                                      <span className="flex items-center gap-1 text-xs font-medium">
                                        <Check className="size-3.5" strokeWidth={2.25} aria-hidden />
                                        {t("hired")}
                                      </span>
                                    ) : p.certified || p.builtByTeam ? null : (
                                      <Pill tone="quiet">{t("notCertified")}</Pill>
                                    )}
                                  </span>
                                ) : null}
                              </div>
                              <p className="mt-3 text-sm leading-relaxed text-grey-700">{p.outcome}</p>
                              <div className="mt-4 mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted">
                                <span className="flex items-center gap-1.5">
                                  <ActorGlyph actor="machine" className="size-2.5" />
                                  {list(p.agents.map((a) => agentById(a)?.name ?? a))}
                                </span>
                                {p.estimate.humanMax.amountMinor > 0 ? (
                                  <span className="flex items-center gap-1.5">
                                    <ActorGlyph actor="human" className="size-2.5" />
                                    {t("reviewerWhenNeeded")}
                                  </span>
                                ) : null}
                              </div>
                              <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t border-rule pt-3 text-xs">
                                <span className="flex flex-wrap items-center gap-1.5">
                                  {p.connectors.map((k) => (
                                    <span
                                      key={k.app}
                                      className="inline-flex items-center gap-1 rounded bg-grey-100 px-1.5 py-0.5 text-grey-700"
                                    >
                                      {k.app}
                                      {k.mocked && !allMocked ? <MockTag className="ml-1 border-0 px-0 py-0" /> : null}
                                    </span>
                                  ))}
                                  {allMocked ? <MockTag /> : null}
                                </span>
                                <span className="tnum ml-auto whitespace-nowrap text-grey-700">
                                  {price === null ? t("perRunUnset") : t("perRun", { price })}
                                </span>
                              </div>
                            </Link>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              </div>
            );
          }}
        </QueryState>
      )}
    </QueryState>
  );
}

export function PackGridSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-8 xl:grid-cols-[220px_minmax(0,1fr)]">
      <Skeleton className="h-64" />
      <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,360px),1fr))] gap-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-56" />
        ))}
      </div>
    </div>
  );
}
