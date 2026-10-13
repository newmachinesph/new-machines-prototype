"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";
import { cn } from "@/lib/cn";
import { sumMoney } from "@/lib/format";
import type { Run } from "@/lib/types";
import { useFormat } from "@/lib/use-format";
import { NodeInspector } from "./node-inspector";
import { RunCanvas } from "./run-canvas";
import { WorkReceipt } from "./work-receipt";
import { ActorGlyph, ActorLabel, ButtonLink, Callout, Id, KeyValues, OutcomeRail, Section, SimTag } from "./ui";

function defaultNode(run: Run) {
  return (
    run.nodes.find((n) => n.status === "WAITING") ??
    run.nodes.find((n) => n.status === "BLOCKED" || n.status === "TIMED_OUT" || n.status === "FAILED") ??
    run.nodes.find((n) => n.decision) ??
    run.nodes[0]
  ).id;
}

export function RunView({ run }: { run: Run }) {
  const t = useTranslations("run.view");
  const { money, dateTime, timeSec } = useFormat();
  const [selected, setSelected] = useState(() => defaultNode(run));
  const node = run.nodes.find((n) => n.id === selected) ?? run.nodes[0];
  const total = sumMoney(run.spent.ai, run.spent.human, run.spent.tools);

  return (
    <div className="space-y-5">
      {run.attention ? (
        <Callout
          tone={run.attention.tone}
          title={run.attention.title}
          action={
            run.attention.href ? (
              <ButtonLink href={run.attention.href} variant="secondary" className="h-8">
                {run.attention.cta}
              </ButtonLink>
            ) : undefined
          }
        >
          {run.attention.body}
        </Callout>
      ) : null}
      {run.recovered ? (
        <Callout tone="info" title={t("recovered")}>
          {run.recovered}
        </Callout>
      ) : null}

      <OutcomeRail stages={run.stages} notes={run.stageNotes} />

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_400px] 2xl:grid-cols-[minmax(0,1fr)_460px]">
        <section className="panel overflow-hidden xl:col-span-2 2xl:col-span-1" aria-label={t("workflow")}>
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-rule px-5 py-3">
            <h2 className="h-section">{t("steps")}</h2>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
              <span className="flex items-center gap-1.5">
                <ActorGlyph actor="machine" className="size-2.5" />
                <ActorLabel actor="machine" />
              </span>
              <span className="flex items-center gap-1.5">
                <ActorGlyph actor="human" className="size-2.5" />
                {t("reviewer")}
              </span>
              <span className="flex items-center gap-1.5">
                <ActorGlyph actor="policy" className="size-2.5" />
                <ActorLabel actor="policy" />
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-0 w-4 border-t-2 border-dashed border-human" />
                {t("revisionLoop")}
              </span>
            </div>
          </div>
          <div className="h-[400px] bg-stage/60 2xl:h-[480px]">
            <RunCanvas run={run} selectedId={selected} onSelect={setSelected} />
          </div>
          <div className="border-t border-rule px-5 py-2.5 text-xs text-muted">{t("canvasHelp")}</div>
        </section>

        <Section
          className="order-3 self-start xl:order-none"
          title={t("timeline")}
          aside={<span className="text-xs text-muted">{t("pacificTime")}</span>}
        >
          <ol className="relative px-5 py-4">
            {run.timeline.map((e, i) => (
              <li key={i} className="relative grid grid-cols-[72px_16px_1fr] gap-x-3 pb-4 last:pb-0">
                <time className="tnum pt-px text-right text-xs text-muted" dateTime={e.at}>
                  {timeSec(e.at)}
                </time>
                <span className="relative flex justify-center pt-[3px]">
                  <ActorGlyph actor={e.actor} className="relative z-10 size-3" />
                  {i < run.timeline.length - 1 ? (
                    <span className="absolute top-4 bottom-[-14px] w-px bg-rule" aria-hidden />
                  ) : null}
                </span>
                <div className="min-w-0">
                  <button
                    type="button"
                    disabled={!e.nodeId}
                    onClick={() => e.nodeId && setSelected(e.nodeId)}
                    className={cn(
                      "text-left text-sm font-medium enabled:hover:underline",
                      e.tone === "blocked" && "text-blocked",
                    )}
                  >
                    {e.title}
                  </button>
                  <div className="text-xs text-muted">
                    {e.who}
                    {e.ref ? (
                      <>
                        {" "}
                        <Id className="ml-1 text-[11px]">{e.ref}</Id>
                      </>
                    ) : null}
                  </div>
                  {e.detail ? (
                    <p className="mt-1 max-w-[70ch] text-[13px] leading-snug text-grey-700">{e.detail}</p>
                  ) : null}
                </div>
              </li>
            ))}
          </ol>
        </Section>

        <div className="order-2 space-y-5 self-start xl:order-none 2xl:sticky 2xl:top-20 2xl:col-start-2 2xl:row-span-2 2xl:row-start-1 2xl:max-h-[calc(100dvh-6rem)] 2xl:[scrollbar-width:thin] 2xl:[scrollbar-color:var(--color-grey-200)_transparent] 2xl:overflow-y-auto">
          <section className="panel" aria-label={t("selectedStep")}>
            <div className="border-b border-rule px-5 py-3">
              <h2 className="h-section">{t("selectedStep")}</h2>
            </div>
            <div className="px-5 py-4">
              <NodeInspector node={node} />
            </div>
          </section>
          <Section title={t("cost")} aside={<SimTag />}>
            <div className="px-5 py-2">
              <KeyValues
                rows={[
                  { label: t("agentsAndModels"), value: <span className="tnum">{money(run.spent.ai)}</span> },
                  { label: t("tools"), value: <span className="tnum">{money(run.spent.tools)}</span> },
                  { label: t("reviewerPay"), value: <span className="tnum">{money(run.spent.human)}</span> },
                  { label: t("totalSoFar"), value: <span className="tnum font-semibold">{money(total)}</span> },
                  {
                    label: t("budget"),
                    value: <span className="tnum">{t("upTo", { amount: money(run.budget) })}</span>,
                  },
                ]}
              />
            </div>
          </Section>
          <Section title={t("runDetails")}>
            <div className="px-5 py-2">
              <KeyValues
                rows={[
                  { label: t("run"), value: <Id>{run.id}</Id> },
                  {
                    label: t("started"),
                    value: t("startedBy", { when: dateTime(run.startedAt), name: run.startedBy }),
                  },
                  { label: t("input"), value: run.input },
                  { label: t("workflowRef"), value: <Id>{run.workflowRef}</Id> },
                  { label: t("contract"), value: <Id>{run.contractRef}</Id> },
                ]}
              />
            </div>
          </Section>
          <WorkReceipt runId={run.id} status={run.status} />
          {run.deliverable ? (
            <ButtonLink href={`/app/runs/${run.id}/evidence`} className="w-full">
              {t("openDeliverable")}
            </ButtonLink>
          ) : (
            <p className="px-1 text-xs leading-relaxed text-muted">
              {t.rich("deliverablePending", {
                example: (chunks) => (
                  <Link className="link" href="/app/runs/run_1042/evidence">
                    {chunks}
                  </Link>
                ),
              })}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
