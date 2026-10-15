"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { useEffect, useRef } from "react";
import { focusAfterClose } from "@/components/base";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Amount, ButtonLink, EmptyState, PageHeader, Pill, SimTag } from "@/components/ui";
import { sumMoney, utc, WORKER_TZ } from "@/lib/format";
import { useIsDemo, useIsLive } from "@/lib/queries/me";
import { useEarnings, useEligibleTasks, useReviewerProfile } from "@/lib/queries/tasks";
import { useFormat } from "@/lib/use-format";
import { NetworkProfilePanel } from "./network-profile";

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
  const demo = useIsDemo();
  const live = useIsLive();
  const tasks = useEligibleTasks();
  const earnings = useEarnings();
  const profile = useReviewerProfile(live).data;
  // With nothing to do and network reviewing off, the switch is the way to get tasks: it moves into the
  // empty state, and the aside does not repeat it.
  const promptNetwork = live && tasks.data?.length === 0 && profile !== undefined && !profile.enabled;
  const aside = useRef<HTMLElement>(null);
  const wasPrompting = useRef(false);
  useEffect(() => {
    // Turning reviewing on moves the switch to the aside and unmounts the one that was focused: follow it.
    // A task arriving on the poll ends the prompt too; then focus is wherever the user left it, so leave it.
    if (wasPrompting.current && !promptNetwork)
      focusAfterClose(() =>
        document.activeElement === null || document.activeElement === document.body
          ? aside.current?.querySelector<HTMLElement>('[role="checkbox"]')
          : null,
      );
    wasPrompting.current = promptNetwork;
  }, [promptNetwork]);
  return (
    <>
      <PageHeader
        title={nav("availableTasks")}
        lede={
          <>
            {t("lede")} <SimTag className="align-baseline">{t(demo ? "simulatedPay" : "simulatedPayLive")}</SimTag>
          </>
        }
      />
      <QueryState query={tasks} skeleton={<TasksSkeleton />}>
        {(openTasks) => {
          return (
            <QueryState query={earnings} skeleton={<TasksSkeleton />}>
              {(paidWork) => (
                <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
                  {openTasks.length === 0 ? (
                    <div className="panel">
                      {promptNetwork ? (
                        <EmptyState
                          action={
                            <>
                              <NetworkProfilePanel className="w-full max-w-[400px] text-left" />
                              <Link href="/work/earnings" className="link inline-flex min-h-10 items-center text-xs">
                                {t("seeEarnings")}
                              </Link>
                            </>
                          }
                        >
                          {t("emptyNetwork")}
                        </EmptyState>
                      ) : (
                        <EmptyState
                          action={
                            <ButtonLink href="/work/earnings" variant="secondary" className="h-10 sm:h-8">
                              {t("seeEarnings")}
                            </ButtonLink>
                          }
                        >
                          {t("empty")}
                        </EmptyState>
                      )}
                    </div>
                  ) : (
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
                              {task.via === "team" ? (
                                <span className="shrink-0 text-sm text-muted">{t("teamUnpaid")}</span>
                              ) : (
                                <Amount value={task.pay} className="shrink-0 text-2xl font-semibold tracking-tight" />
                              )}
                            </div>
                            <dl className="mt-4 mb-4 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-sm">
                              <dt className="text-muted">{t("fields.type")}</dt>
                              <dd className="flex flex-wrap gap-1.5">
                                <Pill tone="human">{t(`mode.${task.mode}`)}</Pill>
                                {task.via === "network" ? <Pill tone="quiet">{t("network")}</Pill> : null}
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
                              {/* A team task already says "unpaid" where the pay would be. */}
                              {task.via === "team" ? null : (
                                <span>{task.via === "network" ? t("simulatedOnAccept") : t("paidOnAccept")}</span>
                              )}
                              <span className="ml-auto shrink-0 font-medium text-ink underline decoration-grey-300 underline-offset-[3px] group-hover:decoration-current">
                                {t("readTask")}
                              </span>
                            </div>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                  <aside ref={aside} className="space-y-4 xl:sticky xl:top-20">
                    {live && !promptNetwork ? <NetworkProfilePanel /> : null}
                    <section className="panel overflow-hidden">
                      <div className="border-b border-rule px-4 py-3 text-sm font-medium">{t("yourWork")}</div>
                      <dl className="divide-y divide-rule px-4 text-sm">
                        {[
                          [t("openOffers"), String(openTasks.length)],
                          [t("worth"), money(sumMoney(...openTasks.map((o) => o.pay)))],
                          [
                            t("owed"),
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
          );
        }}
      </QueryState>
    </>
  );
}
