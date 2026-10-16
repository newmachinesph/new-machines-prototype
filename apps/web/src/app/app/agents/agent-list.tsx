"use client";

import { Search } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { parseAsString, useQueryState } from "nuqs";
import { INTL_TAGS, resolveLocale } from "@/i18n/locales";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { ActorGlyph, Pill, SimTag } from "@/components/ui";
import { useFeeLabel } from "@/lib/listing-fee";
import { useAgents } from "@/lib/queries/catalog";
import { shownVersion } from "@/lib/shown-version";
import type { Agent } from "@/lib/types";
import { useCapabilityLabel } from "./capability-label";

const matches = (a: Agent, needle: string, label: (id: string) => string) =>
  !needle ||
  [a.name, a.publisher, a.summary, ...a.capabilities, ...a.capabilities.map(label)].some((field) =>
    field.toLowerCase().includes(needle),
  );

export function AgentList() {
  const t = useTranslations("agents.list");
  const agents = useAgents();
  const label = useCapabilityLabel();
  const [q, setQ] = useQueryState("q", parseAsString.withDefault(""));

  return (
    <QueryState query={agents} skeleton={<AgentListSkeleton />}>
      {(all) => {
        if (all.length === 0) return <p className="panel px-5 py-10 text-center text-sm text-muted">{t("empty")}</p>;
        const needle = q.trim().toLowerCase();
        const shown = all.filter((a) => matches(a, needle, label));
        return (
          <div className="space-y-4">
            <label className="flex h-9 max-w-xl items-center gap-2 rounded-md border border-rule bg-paper px-3 focus-within:border-grey-500">
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
            {shown.length === 0 ? (
              <p className="panel px-5 py-10 text-center text-sm text-muted">
                {t("noMatch")}{" "}
                <button type="button" className="link" onClick={() => void setQ(null)}>
                  {t("showAll")}
                </button>
              </p>
            ) : (
              <ul className="grid [grid-template-columns:repeat(auto-fill,minmax(min(100%,340px),1fr))] gap-4">
                {shown.map((a) => (
                  <AgentCard key={a.id} agent={a} />
                ))}
              </ul>
            )}
          </div>
        );
      }}
    </QueryState>
  );
}

/**
 * The name is the link and stretches over the whole card, so the packs that use the agent can be links of
 * their own (an anchor inside an anchor is not allowed).
 */
function AgentCard({ agent: a }: { agent: Agent }) {
  const t = useTranslations("agents.list");
  const tl = useTranslations("listedMarket");
  const fee = useFeeLabel();
  const label = useCapabilityLabel();
  const locale = resolveLocale(useLocale());
  return (
    <li className="panel relative flex h-full flex-col p-5 transition-colors hover:border-grey-300">
      <div className="flex items-start gap-2">
        <ActorGlyph actor="machine" className="mt-1.5 size-2.5" />
        <div className="min-w-0 flex-1">
          <Link
            href={`/app/agents/${encodeURIComponent(a.id)}`}
            className="text-[15px] font-semibold after:absolute after:inset-0 after:rounded-[inherit]"
          >
            {a.name}
          </Link>
          <div className="mt-0.5 text-xs text-muted">
            {/* A listed agent's publisher is on the "By" line below, beside its fee. */}
            {a.listing
              ? tl("version", { version: shownVersion(a) })
              : t("publisherVersion", { publisher: a.publisher, version: shownVersion(a) })}
          </div>
          {a.listing ? (
            <div className="mt-0.5 text-xs text-muted">
              {tl("by", { publisher: a.listing.publisher })}
              {" · "}
              <span className="tnum">{fee(a.listing)}</span>
            </div>
          ) : null}
        </div>
        {a.builtByTeam ? (
          <Pill tone="machine" className="shrink-0">
            {t("team")}
          </Pill>
        ) : a.source === "sample" ? (
          <SimTag className="shrink-0">{t("sample")}</SimTag>
        ) : null}
      </div>
      <p className="mt-3 text-sm leading-relaxed text-grey-700">{a.summary}</p>
      {a.capabilities.length ? (
        <ul className="mt-3 flex flex-wrap gap-1.5">
          {a.capabilities.map((c) => (
            <li key={c} className="rounded bg-grey-100 px-1.5 py-0.5 text-[11px] text-grey-700">
              {label(c)}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="mt-auto pt-4">
        <div className="border-t border-rule pt-3 text-xs text-grey-700">
          {t("usedIn", { n: a.usedBy.length })}
          {/* The full-width colon of the Japanese sentence already carries its own space. */}
          {a.usedBy.length && locale !== "ja" ? " " : null}
          {new Intl.ListFormat(INTL_TAGS[locale], { type: "conjunction" })
            .formatToParts(a.usedBy.map((p) => p.slug))
            .map((part, i) => {
              if (part.type === "literal") return part.value;
              const p = a.usedBy.find((u) => u.slug === part.value)!;
              return (
                <Link
                  key={i}
                  href={`/app/marketplace/${encodeURIComponent(p.slug)}`}
                  className="link relative z-10 inline-block py-1 text-ink"
                >
                  {p.name}
                </Link>
              );
            })}
        </div>
      </div>
    </li>
  );
}

export function AgentListSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-9 max-w-xl" />
      <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,340px),1fr))] gap-4">
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="h-48" />
        ))}
      </div>
    </div>
  );
}
