"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { ButtonLink, EmptyState, PageHeader, Section } from "@/components/ui";
import { useApprovals } from "@/lib/queries/workspace";
import { useFormat } from "@/lib/use-format";
import { ApprovalCard } from "./approval-card";

export function ApprovalsView() {
  const t = useTranslations("approvals");
  const { dateTime } = useFormat();
  const approvals = useApprovals();
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
                    {past.map((a) => (
                      <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 text-sm">
                        <span>{a.title}</span>
                        <span className="text-muted">
                          {t("pastLine", { status: t(`past.${a.status}`), when: dateTime(a.requestedAt) })}
                        </span>
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
