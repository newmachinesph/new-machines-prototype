"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Amount, PageHeader, Pill, SimTag } from "@/components/ui";
import { sumMoney, utc, WORKER_TZ } from "@/lib/format";
import { useEarnings, useEligibleTasks } from "@/lib/queries/tasks";
import { useFormat } from "@/lib/use-format";

function TasksSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="grid [grid-template-columns:repeat(auto-fill,minmax(min(100%,560px),1fr))] gap-3">
        <Skeleton className="h-60" />
        <Skeleton className="h-60" />
        <Skeleton className="h-60" />
      </div>
    </div>
  );
}

export function WorkView() {
  const t = useTranslations("work");
  const nav = useTranslations("nav");
  const { money, dateTime, until } = useFormat();
  const tasks = useEligibleTasks();
  const earnings = useEarnings();
  return (
    <>
      <PageHeader
        title={nav("availableTasks")}
        lede={t("lede")}
        actions={<SimTag className="px-2 py-1 text-xs">{t("simulatedPay")}</SimTag>}
      />
      <QueryState query={tasks} skeleton={<TasksSkeleton />}>
        {(openTasks) => (
          <QueryState query={earnings} skeleton={<TasksSkeleton />}>
            {(paidWork) => (
              <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
                <ul className="grid [grid-template-columns:repeat(auto-fill,minmax(min(100%,560px),1fr))] gap-3">
                  {openTasks.map((task) => (
                    <li key={task.id} className="min-w-0">
                      <Link
                        href={`/work/tasks/${task.id}`}
                        className="group panel flex h-full flex-col p-5 transition-colors hover:border-grey-300"
                      >
                        <div className="flex items-start justify-between gap-4">
                          <div className="min-w-0">
                            <div className="text-[15px] font-semibold break-words">{task.title}</div>
                            <div className="mt-1 text-sm break-words text-muted">
                              {t("byline", { buyer: task.buyer, pack: task.packName, skill: task.skill })}
                            </div>
                          </div>
                          <Amount value={task.pay} className="shrink-0 text-2xl font-semibold tracking-tight" />
                        </div>
                        <dl className="mt-4 mb-4 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-sm">
                          <dt className="text-muted">{t("fields.type")}</dt>
                          <dd>
                            <Pill tone="human">{t(`mode.${task.mode}`)}</Pill>
                          </dd>
                          <dt className="text-muted">{t("fields.time")}</dt>
                          <dd className="text-grey-700">{t("aboutMin", { n: task.estMinutes })}</dd>
                          <dt className="text-muted">{t("fields.due")}</dt>
                          <dd className="text-grey-700">
                            {t("due", {
                              when: dateTime(task.deadline, WORKER_TZ),
                              utc: utc(task.deadline),
                              until: until(task.deadline),
                            })}
                          </dd>
                          <dt className="text-muted">{t("fields.data")}</dt>
                          <dd className="text-grey-700">
                            {task.dataClass === "CONFIDENTIAL" ? t("dataConfidential") : t("dataNone")}
                          </dd>
                        </dl>
                        <div className="mt-auto flex items-center justify-between gap-3 border-t border-rule pt-3 text-xs text-muted">
                          {t("paidOnAccept")}
                          <span className="shrink-0 font-medium text-ink underline decoration-grey-300 underline-offset-[3px] group-hover:decoration-current">
                            {t("readTask")}
                          </span>
                        </div>
                      </Link>
                    </li>
                  ))}
                </ul>
                <aside className="space-y-4 xl:sticky xl:top-20">
                  <section className="panel overflow-hidden">
                    <div className="border-b border-rule px-4 py-3 text-sm font-medium">{t("yourWork")}</div>
                    <dl className="divide-y divide-rule px-4 text-sm">
                      {[
                        [t("openOffers"), String(openTasks.length)],
                        [t("worth"), money(sumMoney(...openTasks.map((o) => o.pay)))],
                        [
                          t("notYetPaid"),
                          money(
                            sumMoney(...paidWork.filter((e) => e.status !== "PAID_SIMULATED").map((e) => e.amount)),
                          ),
                        ],
                        [t("acceptedSubmissions"), String(paidWork.length)],
                      ].map(([k, v]) => (
                        <div key={k} className="flex justify-between gap-3 py-2.5">
                          <dt className="text-grey-700">{k}</dt>
                          <dd className="tnum font-medium">{v}</dd>
                        </div>
                      ))}
                    </dl>
                    <Link
                      href="/work/earnings"
                      className="block border-t border-rule bg-stage/60 px-4 py-2.5 text-xs text-muted hover:text-ink"
                    >
                      {t("seeEarnings")}
                    </Link>
                  </section>
                  <section className="panel px-4 py-3.5 text-[13px] leading-relaxed text-grey-700">
                    <div className="mb-1 text-sm font-medium text-ink">{t("how.title")}</div>
                    {t("how.body")}
                  </section>
                </aside>
              </div>
            )}
          </QueryState>
        )}
      </QueryState>
    </>
  );
}
