"use client";

import { useTranslations } from "next-intl";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Amount, Id, PageHeader, Pill, Section, SimTag } from "@/components/ui";
import { sumMoney, WORKER_TZ } from "@/lib/format";
import { useEarnings } from "@/lib/queries/tasks";
import { useFormat } from "@/lib/use-format";
import type { Earning } from "@/lib/types";

const STATUS_TONE: Record<Earning["status"], "human" | "machine" | "ink" | "quiet"> = {
  OWED: "human",
  ELIGIBLE: "machine",
  PAID_SIMULATED: "ink",
  IN_REVIEW: "quiet",
};

function EarningsSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-20" />
      <Skeleton className="h-60" />
    </div>
  );
}

export function EarningsView() {
  const t = useTranslations("work.earnings");
  const nav = useTranslations("nav");
  const { dateTime } = useFormat();
  const earnings = useEarnings();
  return (
    <>
      <PageHeader
        title={nav("earnings")}
        lede={t("lede")}
        actions={<SimTag className="px-2 py-1 text-xs">{t("simulated")}</SimTag>}
      />
      <QueryState query={earnings} skeleton={<EarningsSkeleton />}>
        {(rows) => {
          const unpaid = sumMoney(...rows.filter((e) => e.status !== "PAID_SIMULATED").map((e) => e.amount));
          const paid = sumMoney(...rows.filter((e) => e.status === "PAID_SIMULATED").map((e) => e.amount));
          return (
            <div className="space-y-6">
              <div className="grid gap-px overflow-hidden rounded-[12px] border border-rule bg-rule sm:grid-cols-2">
                <div className="bg-paper px-5 py-4">
                  <div className="label">{t("owed")}</div>
                  <Amount value={unpaid} className="mt-1 block text-2xl font-semibold tracking-tight" />
                </div>
                <div className="bg-paper px-5 py-4">
                  <div className="label">{t("paid")}</div>
                  <Amount value={paid} className="mt-1 block text-2xl font-semibold tracking-tight" />
                </div>
              </div>
              <Section title={t("tasks")}>
                <ul className="divide-y divide-rule">
                  {rows.map((e) => (
                    <li
                      key={e.taskId}
                      className="grid gap-2 px-5 py-3.5 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center sm:gap-6"
                    >
                      <div className="min-w-0">
                        <div className="text-sm font-medium break-words">{e.title}</div>
                        <div className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-muted">
                          <Id className="text-[11px]">{e.taskId}</Id>
                          <span>{t(`verdict.${e.verdict}`)}</span>
                          <span>{dateTime(e.at, WORKER_TZ)}</span>
                        </div>
                        {e.taskId === "ht_010" ? (
                          <p className="mt-1 text-xs text-grey-700">{t("failedCheck")}</p>
                        ) : null}
                      </div>
                      <Pill tone={STATUS_TONE[e.status]}>{t(`status.${e.status}`)}</Pill>
                      <Amount value={e.amount} className="text-sm font-medium sm:w-16 sm:text-right" />
                    </li>
                  ))}
                </ul>
              </Section>
            </div>
          );
        }}
      </QueryState>
    </>
  );
}
