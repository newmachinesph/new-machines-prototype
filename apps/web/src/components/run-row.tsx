"use client";

import { ChevronRight, Search } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { parseAsString, useQueryState } from "nuqs";
import { useMemo } from "react";
import { cn } from "@/lib/cn";
import { useNow } from "@/lib/clock";
import { duration, sumMoney } from "@/lib/format";
import { usePacks } from "@/lib/queries/catalog";
import { useFormat } from "@/lib/use-format";
import type { RunStatus, RunSummary } from "@/lib/types";
import { Segmented, Select, Tooltip } from "./base";
import { PackIcon } from "./pack-icon";
import { Skeleton } from "./skeleton";
import { Id, OutcomeRail, RunStatusPill } from "./ui";

export type RowRun = RunSummary;

// The key is the URL value and the message key under `run.list.filters`.
type FilterKey = "all" | "needs" | "active" | "done" | "failed";
const FILTERS: { key: FilterKey; statuses?: RunStatus[] }[] = [
  { key: "all" },
  { key: "needs", statuses: ["NEEDS_ATTENTION", "WAITING_FOR_EVENT", "WAITING_FOR_HUMAN"] },
  { key: "active", statuses: ["RUNNING", "VERIFYING"] },
  { key: "done", statuses: ["COMPLETED"] },
  { key: "failed", statuses: ["FAILED", "CANCELLED"] },
];

function elapsed(r: RowRun, now: string, soFar: (d: string) => string) {
  const end = r.endedAt ?? now;
  const s = Math.round((Date.parse(end) - Date.parse(r.startedAt)) / 1000);
  return r.endedAt ? duration(s) : soFar(duration(s));
}

export function RunsBrowser({ runs, linkable }: { runs: RowRun[]; linkable: string[] }) {
  const t = useTranslations("run.list");
  const { money, ago } = useFormat();
  const now = useNow();
  const [q, setQ] = useQueryState("q", parseAsString.withDefault(""));
  const [filter, setFilter] = useQueryState("status", parseAsString.withDefault("all"));
  const [pack, setPack] = useQueryState("pack", parseAsString.withDefault("all"));
  const catalog = usePacks();
  const packName = (slug: string) => catalog.data?.find((p) => p.slug === slug)?.name ?? slug;

  const packs = useMemo(() => [...new Set(runs.map((r) => r.packSlug))], [runs]);
  const inFilter = (r: RowRun, key: string) => {
    const f = FILTERS.find((x) => x.key === key);
    return !f?.statuses || f.statuses.includes(r.status);
  };
  const needle = q.trim().toLowerCase();
  const scoped = runs.filter(
    (r) =>
      (pack === "all" || r.packSlug === pack) &&
      (!needle || [r.title, r.id, r.summary, packName(r.packSlug)].some((t) => t.toLowerCase().includes(needle))),
  );
  const shown = scoped.filter((r) => inFilter(r, filter));

  if (catalog.isError) throw catalog.error;
  if (catalog.isPending) return <Skeleton className="h-[480px]" />;

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
        <label className="flex h-9 flex-1 items-center gap-2 rounded-md border border-rule bg-paper px-3 focus-within:border-grey-500">
          <Search className="size-4 text-grey-500" strokeWidth={1.75} aria-hidden />
          <span className="sr-only">{t("search")}</span>
          <input
            name="q"
            type="search"
            value={q}
            onChange={(e) => void setQ(e.target.value || null)}
            placeholder={t("searchPlaceholder")}
            className="w-full bg-transparent text-sm outline-none placeholder:text-grey-500"
          />
        </label>
        <div className="relative flex [scrollbar-width:none] gap-3 overflow-x-auto">
          <Segmented
            label={t("filterStatus")}
            value={filter}
            onValueChange={(v) => void setFilter(v === "all" ? null : v)}
            options={FILTERS.map((f) => ({
              value: f.key,
              label: t(`filters.${f.key}`),
              count: scoped.filter((r) => inFilter(r, f.key)).length,
            }))}
          />
          <Select
            label={t("filterPack")}
            value={pack}
            onValueChange={(v) => void setPack(v === "all" ? null : v)}
            items={[{ value: "all", label: t("allPacks") }, ...packs.map((s) => ({ value: s, label: packName(s) }))]}
          />
        </div>
      </div>

      <div className="panel relative overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-rule bg-stage/60 text-left text-xs text-muted">
              <th className="px-4 py-2.5 font-medium">{t("run")}</th>
              <th className="px-3 py-2.5 font-medium">{t("status")}</th>
              <th className="hidden px-3 py-2.5 font-medium md:table-cell">
                <Tooltip label={t("outcomeTooltip")}>
                  <button type="button" className="cursor-help underline decoration-dotted underline-offset-2">
                    {t("outcome")}
                  </button>
                </Tooltip>
              </th>
              <th className="hidden px-3 py-2.5 font-medium 2xl:table-cell">{t("result")}</th>
              <th className="hidden px-3 py-2.5 text-right font-medium xl:table-cell">{t("agentsAndTools")}</th>
              <th className="hidden px-3 py-2.5 text-right font-medium xl:table-cell">{t("reviewers")}</th>
              <th className="hidden px-3 py-2.5 text-right font-medium sm:table-cell">{t("total")}</th>
              <th className="hidden px-3 py-2.5 font-medium lg:table-cell">{t("started")}</th>
              <th className="w-10 px-3 py-2.5">
                <span className="sr-only">{t("open")}</span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-rule">
            {shown.map((r) => {
              const open = linkable.includes(r.id);
              return (
                <tr key={r.id} className={cn("group relative", open && "hover:bg-grey-50/70")}>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <PackIcon slug={r.packSlug} className="size-8" />
                      <div className="min-w-0">
                        {open ? (
                          <Link
                            href={`/app/runs/${r.id}`}
                            className="font-medium after:absolute after:inset-0 hover:underline"
                          >
                            {r.title}
                          </Link>
                        ) : (
                          <span className="font-medium">{r.title}</span>
                        )}
                        <div className="mt-0.5 flex items-center gap-2 text-xs text-muted">
                          <span className="truncate">{packName(r.packSlug)}</span>
                          <Id className="hidden text-[11px] xl:inline">{r.id}</Id>
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-3">
                    <RunStatusPill status={r.status} />
                  </td>
                  <td className="hidden px-3 py-3 md:table-cell">
                    <OutcomeRail compact stages={r.stages} />
                  </td>
                  <td className="hidden max-w-[44ch] px-3 py-3 text-[13px] text-grey-700 2xl:table-cell">
                    {r.summary}
                  </td>
                  <td className="tnum hidden px-3 py-3 text-right text-grey-700 xl:table-cell">
                    {money(sumMoney(r.spent.ai, r.spent.tools))}
                  </td>
                  <td className="tnum hidden px-3 py-3 text-right text-grey-700 xl:table-cell">
                    {money(r.spent.human)}
                  </td>
                  <td className="tnum hidden px-3 py-3 text-right font-medium sm:table-cell">
                    {money(sumMoney(r.spent.ai, r.spent.human, r.spent.tools))}
                  </td>
                  <td className="hidden px-3 py-3 whitespace-nowrap lg:table-cell">
                    <div>
                      {ago(r.startedAt)} <span className="text-muted">{t("by", { name: r.startedBy })}</span>
                    </div>
                    <div className="tnum text-xs text-muted">{elapsed(r, now, (d) => t("soFar", { duration: d }))}</div>
                  </td>
                  <td className="px-3 py-3">
                    {open ? <ChevronRight className="size-4 text-grey-300 group-hover:text-ink" aria-hidden /> : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {shown.length === 0 ? (
          <p className="px-4 py-10 text-center text-sm text-muted">
            {t("noMatch")}{" "}
            <button
              type="button"
              className="link"
              onClick={() => {
                void setQ(null);
                void setFilter(null);
                void setPack(null);
              }}
            >
              {t("clearFilters")}
            </button>
          </p>
        ) : null}
        <div className="border-t border-rule bg-stage/60 px-4 py-2.5 text-xs text-muted">{t("footer")}</div>
      </div>
    </div>
  );
}
