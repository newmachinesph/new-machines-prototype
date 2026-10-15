"use client";

import { Search } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { parseAsString, useQueryState } from "nuqs";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { ActorGlyph, Id, Pill, SimTag } from "@/components/ui";
import { useAgents } from "@/lib/queries/catalog";
import type { Agent } from "@/lib/types";

const matches = (a: Agent, needle: string) =>
  !needle || [a.name, a.publisher, a.summary, ...a.capabilities].some((field) => field.toLowerCase().includes(needle));

export function AgentList() {
  const t = useTranslations("agents.list");
  const agents = useAgents();
  const [q, setQ] = useQueryState("q", parseAsString.withDefault(""));

  return (
    <QueryState query={agents} skeleton={<AgentListSkeleton />}>
      {(all) => {
        if (all.length === 0) return <p className="panel px-5 py-10 text-center text-sm text-muted">{t("empty")}</p>;
        const needle = q.trim().toLowerCase();
        const shown = all.filter((a) => matches(a, needle));
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
                  <li key={a.id}>
                    <AgentCard agent={a} />
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      }}
    </QueryState>
  );
}

function AgentCard({ agent: a }: { agent: Agent }) {
  const t = useTranslations("agents.list");
  return (
    <Link
      href={`/app/agents/${encodeURIComponent(a.id)}`}
      className="panel flex h-full flex-col p-5 transition-colors hover:border-grey-300"
    >
      <div className="flex items-start gap-2">
        <ActorGlyph actor="machine" className="mt-1.5 size-2.5" />
        <div className="min-w-0 flex-1">
          <div className="text-[15px] font-semibold">{a.name}</div>
          <div className="mt-0.5 text-xs text-muted">
            {t("publisherVersion", { publisher: a.publisher, version: a.version })}
          </div>
        </div>
        {a.builtByTeam ? (
          <span className="shrink-0">
            <Pill tone="machine">{t("team")}</Pill>
          </span>
        ) : a.source === "sample" ? (
          <SimTag className="shrink-0">{t("sample")}</SimTag>
        ) : null}
      </div>
      <p className="mt-3 text-sm leading-relaxed text-grey-700">{a.summary}</p>
      {a.capabilities.length ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {a.capabilities.map((c) => (
            <Id key={c} className="rounded bg-grey-100 px-1.5 py-0.5 text-[11px]">
              {c}
            </Id>
          ))}
        </div>
      ) : null}
      <div className="mt-auto pt-4">
        <div className="border-t border-rule pt-3 text-xs text-grey-700">{t("usedIn", { n: a.usedBy.length })}</div>
      </div>
    </Link>
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
