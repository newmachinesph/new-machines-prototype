"use client";

import { Check, Search } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { parseAsString, useQueryState } from "nuqs";
import { Fragment } from "react";
import { PackIcon } from "@/components/pack-icon";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { ActorGlyph, MockTag, Pill } from "@/components/ui";
import { cn } from "@/lib/cn";
import { useAgentById, useAgents, usePacks } from "@/lib/queries/catalog";
import { useFormat } from "@/lib/use-format";

// Sentinel values double as the `category` URL parameter, so they stay English; the labels shown are translated.
const ALL = "All packs";
const HIRED = "Hired";

export function PackGrid() {
  const t = useTranslations("marketplace.grid");
  const { money, list } = useFormat();
  const packsQuery = usePacks();
  const agentsQuery = useAgents();
  const agentById = useAgentById();
  const [cat, setCat] = useQueryState("category", parseAsString.withDefault(ALL));
  const [q, setQ] = useQueryState("q", parseAsString.withDefault(""));

  return (
    <QueryState query={packsQuery} skeleton={<PackGridSkeleton />}>
      {(PACKS) => (
        <QueryState query={agentsQuery} skeleton={<PackGridSkeleton />}>
          {() => {
            const categories = [...new Set(PACKS.map((p) => p.category))];
            const filters = [
              { label: ALL, text: t("all"), n: PACKS.length },
              { label: HIRED, text: t("hired"), n: PACKS.filter((p) => p.installed).length },
              ...categories.map((c) => ({ label: c, text: c, n: PACKS.filter((p) => p.category === c).length })),
            ];
            const needle = q.trim().toLowerCase();
            const shown = PACKS.filter(
              (p) =>
                (cat === ALL || (cat === HIRED ? p.installed : p.category === cat)) &&
                (!needle ||
                  [p.name, p.outcome, p.publisher, p.category].some((field) => field.toLowerCase().includes(needle))),
            );

            return (
              <div className="grid grid-cols-1 items-start gap-8 xl:grid-cols-[220px_minmax(0,1fr)]">
                <aside className="space-y-5 xl:sticky xl:top-20">
                  <p className="text-sm leading-relaxed text-grey-700">{t("intro")}</p>
                  <nav
                    aria-label={t("filterLabel")}
                    className="flex [scrollbar-width:none] gap-1 overflow-x-auto xl:flex-col xl:gap-0.5"
                  >
                    {filters.map((f, i) => (
                      <Fragment key={f.label}>
                        {/* Views (All packs, Hired) above the line, categories below it. */}
                        {i === 2 ? (
                          <span
                            aria-hidden
                            className="mx-1 my-1.5 w-px shrink-0 bg-rule xl:mx-2.5 xl:my-2 xl:h-px xl:w-auto"
                          />
                        ) : null}
                        <button
                          type="button"
                          aria-pressed={cat === f.label}
                          onClick={() => setCat(f.label === ALL ? null : f.label)}
                          className={cn(
                            "flex h-8 shrink-0 items-center justify-between gap-3 rounded-md px-2.5 text-sm whitespace-nowrap",
                            cat === f.label
                              ? "bg-grey-100 font-medium text-ink"
                              : "text-grey-700 hover:bg-grey-50 hover:text-ink",
                          )}
                        >
                          {f.text}
                          <span className="tnum text-xs text-muted">{f.n}</span>
                        </button>
                      </Fragment>
                    ))}
                  </nav>
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
                        }}
                      >
                        {t("showAll")}
                      </button>
                    </p>
                  ) : (
                    <ul className="grid [grid-template-columns:repeat(auto-fill,minmax(min(100%,360px),1fr))] gap-4">
                      {shown.map((p) => (
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
                              {p.installed ? (
                                <span className="flex shrink-0 items-center gap-1 text-xs font-medium">
                                  <Check className="size-3.5" strokeWidth={2.25} aria-hidden />
                                  {t("hired")}
                                </span>
                              ) : p.certified ? null : (
                                <Pill tone="quiet">{t("notCertified")}</Pill>
                              )}
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
                              <span className="flex flex-wrap gap-1.5">
                                {p.connectors.map((k) => (
                                  <span
                                    key={k.app}
                                    className="inline-flex items-center gap-1 rounded bg-grey-100 px-1.5 py-0.5 text-grey-700"
                                  >
                                    {k.app}
                                    {k.mocked ? <MockTag className="ml-1 border-0 px-0 py-0" /> : null}
                                  </span>
                                ))}
                              </span>
                              <span className="tnum ml-auto whitespace-nowrap text-grey-700">
                                {t("perRun", { min: money(p.estimate.aiMin), max: money(p.estimate.aiMax) })}
                              </span>
                            </div>
                          </Link>
                        </li>
                      ))}
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
