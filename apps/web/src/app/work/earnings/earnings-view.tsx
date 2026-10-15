"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Amount, ButtonLink, EmptyState, PageHeader, Pill, Section, SimTag } from "@/components/ui";
import { cn } from "@/lib/cn";
import type { ReactNode } from "react";
import { sumMoney } from "@/lib/format";
import { useIsDemo } from "@/lib/queries/me";
import { useEarnings } from "@/lib/queries/tasks";
import type { Earning } from "@/lib/types";
import { useWorkerDateTime } from "../worker-time";

const STATUS_TONE: Record<Earning["status"], "human" | "machine" | "ink" | "quiet"> = {
  OWED: "human",
  ELIGIBLE: "machine",
  PAID_SIMULATED: "ink",
  IN_REVIEW: "quiet",
};

// Task, verdict and payment. On a phone the three stack, each payment and verdict with its own label.
const COLUMNS = "sm:grid-cols-[minmax(0,1fr)_11rem_12rem]";

const ROW = "grid gap-x-6 gap-y-1.5 px-5 py-3.5 sm:items-center";

/** The demo's earnings are fixtures with no task page behind them, so only a live row links to its task. */
function RowShell({ taskId, linked, children }: { taskId: string; linked: boolean; children: ReactNode }) {
  if (!linked) return <div className={cn(ROW, COLUMNS)}>{children}</div>;
  return (
    <Link href={`/work/tasks/${taskId}`} className={cn(ROW, COLUMNS, "hover:bg-grey-50/70")}>
      {children}
    </Link>
  );
}

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
  const work = useTranslations("work");
  const nav = useTranslations("nav");
  const dateTime = useWorkerDateTime();
  const demo = useIsDemo();
  const earnings = useEarnings();
  return (
    <>
      <PageHeader
        title={nav("earnings")}
        lede={
          <>
            {t(demo ? "lede" : "ledeLive")}{" "}
            <SimTag className="align-baseline">{t(demo ? "simulated" : "simulatedLive")}</SimTag>
          </>
        }
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
                {rows.length === 0 ? (
                  <EmptyState
                    action={
                      <ButtonLink href="/work" variant="secondary" className="h-10 sm:h-8">
                        {t("seeTasks")}
                      </ButtonLink>
                    }
                  >
                    {t("empty")}
                  </EmptyState>
                ) : (
                  <>
                    <div className={cn("label hidden gap-x-6 border-b border-rule px-5 py-2 sm:grid", COLUMNS)}>
                      <span>{t("columns.task")}</span>
                      <span>{t("columns.verdict")}</span>
                      <span className="sm:text-right">{t("columns.payment")}</span>
                    </div>
                    <ul className="divide-y divide-rule">
                      {rows.map((e) => (
                        <li key={e.taskId}>
                          <RowShell taskId={e.taskId} linked={!demo}>
                            <div className="min-w-0">
                              <div className="text-sm font-medium break-words">{e.title}</div>
                              <div className="mt-0.5 text-xs text-muted">{dateTime(e.at)}</div>
                              {e.taskId === "ht_010" ? (
                                <p className="mt-1 text-xs text-grey-700">{t("failedCheck")}</p>
                              ) : null}
                            </div>
                            <div className="text-sm text-grey-700">
                              <span className="label sm:hidden">{t("columns.verdict")}: </span>
                              {t(`verdict.${e.verdict}`)}
                            </div>
                            <div className="flex flex-wrap items-center gap-2 text-sm sm:justify-end">
                              <span className="label sm:hidden">{t("columns.payment")}: </span>
                              {e.via === "team" ? (
                                <span className="text-muted">{work("teamUnpaid")}</span>
                              ) : (
                                <>
                                  <Pill tone={STATUS_TONE[e.status]}>{t(`status.${e.status}`)}</Pill>
                                  <Amount value={e.amount} className="font-medium sm:w-16 sm:text-right" />
                                </>
                              )}
                            </div>
                          </RowShell>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </Section>
            </div>
          );
        }}
      </QueryState>
    </>
  );
}
