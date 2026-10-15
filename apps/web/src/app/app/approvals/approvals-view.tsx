"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { ButtonLink, EmptyState, PageHeader, Section } from "@/components/ui";
import { useRuns } from "@/lib/queries/runs";
import { useApprovals } from "@/lib/queries/workspace";
import { useFormat } from "@/lib/use-format";
import type { Approval } from "@/lib/types";
import { ApprovalCard } from "./approval-card";

/** Past approvals in the order they came, grouped under the run they belong to. */
function byRun(past: Approval[]) {
  const groups = new Map<string, Approval[]>();
  for (const a of past) groups.set(a.runId, [...(groups.get(a.runId) ?? []), a]);
  return [...groups].map(([runId, items]) => ({ runId, items }));
}

export function ApprovalsView() {
  const t = useTranslations("approvals");
  const { date, dateTime } = useFormat();
  const approvals = useApprovals();
  // Titles only; no need to poll the whole list for them.
  const runs = useRuns(true, false);
  // Runs of one pack share a title, so each group also carries a date: the run's start, else its first approval.
  const runLabel = (g: { runId: string; items: Approval[] }) => {
    const run = runs.data?.find((r) => r.id === g.runId);
    return t("runLabel", { title: run?.title ?? t("openRun"), when: date(run?.startedAt ?? g.items[0].requestedAt) });
  };
  // A card you just decided stays on screen with its outcome instead of jumping to "Earlier".
  const [decided, setDecided] = useState<string[]>([]);

  return (
    <>
      <PageHeader title={t("title")} lede={t("lede")} />
      <QueryState query={approvals} skeleton={<Skeleton className="h-96" />}>
        {(all) => {
          const cards = all.filter((a) => a.status === "PENDING" || decided.includes(a.id));
          const past = all.filter((a) => !cards.includes(a));
          return (
            <div className="grid grid-cols-1 items-start gap-6 2xl:grid-cols-[minmax(0,1fr)_420px]">
              <div className="space-y-6">
                {cards.length === 0 ? (
                  <div className="panel">
                    <EmptyState
                      action={
                        <ButtonLink href="/app/runs" variant="secondary" className="h-8">
                          {t("seeRuns")}
                        </ButtonLink>
                      }
                    >
                      {t("empty")}
                    </EmptyState>
                  </div>
                ) : null}
                {cards.map((a) => (
                  <ApprovalCard
                    key={a.id}
                    approval={a}
                    onDecide={() => setDecided((ids) => (ids.includes(a.id) ? ids : [...ids, a.id]))}
                  />
                ))}
              </div>
              {past.length ? (
                <Section title={t("earlier")}>
                  <ul className="divide-y divide-rule">
                    {byRun(past).map((g) => (
                      <li key={g.runId} className="px-5 py-3 text-sm">
                        <Link href={`/app/runs/${g.runId}`} className="link inline-block py-1 font-medium">
                          {runLabel(g)}
                        </Link>
                        <ul className="mt-1 space-y-1">
                          {g.items.map((a) => (
                            <li key={a.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-0.5">
                              <span>{a.title}</span>
                              <span className="text-muted">
                                {t("pastLine", { status: t(`past.${a.status}`), when: dateTime(a.requestedAt) })}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </li>
                    ))}
                  </ul>
                </Section>
              ) : null}
            </div>
          );
        }}
      </QueryState>
    </>
  );
}
