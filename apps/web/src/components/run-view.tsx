"use client";

import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useRef, useState } from "react";
import { DEFAULT_LOCALE, resolveLocale } from "@/i18n/locales";
import { cn } from "@/lib/cn";
import { sumMoney } from "@/lib/format";
import { useIsDemo } from "@/lib/queries/me";
import { useReceipt } from "@/lib/queries/runs";
import { isFinishedRun, type NodeType, type Run } from "@/lib/types";
import { useFormat } from "@/lib/use-format";
import { Checkbox } from "./base";
import { NodeInspector } from "./node-inspector";
import { RunCanvas } from "./run-canvas";
import { useCodes, useWho } from "./run-codes";
import { isSettled, useAutoTour } from "./tour/use-auto-tour";
import { CollapsibleSection, TechnicalDetails } from "./run-disclosures";
import { WorkReceipt } from "./work-receipt";
import {
  ActorGlyph,
  ActorLabel,
  ButtonLink,
  Callout,
  Id,
  KeyValues,
  NodeStatusPill,
  OutcomeRail,
  Section,
  SimTag,
} from "./ui";

/** Below `md` (the phone layout), where the step list and the inspector are far apart. */
const PHONE_QUERY = "(max-width: 767px)";

/** Where the page's parts are, for the jump links a phone needs (an id on the panel, or on its heading). */
const ANCHORS = { steps: "run-steps", timeline: "run-timeline", cost: "run-cost", details: "run-details" } as const;

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
  const tCanvas = useTranslations("run.canvas");
  const tt = useTranslations("run.technical");
  const { money, dateTime, timeSec } = useFormat();
  const { line } = useCodes();
  const who = useWho();
  // The run record is written in English (the API's words) and shown as recorded: another language says so.
  const recordedLanguage = resolveLocale(useLocale()) !== DEFAULT_LOCALE;
  const [selected, setSelected] = useState(() => defaultNode(run));
  const inspector = useRef<HTMLElement>(null);
  // On a phone the chosen step's details are far below the list or timeline: bring them into view.
  const choose = (id: string) => {
    setSelected(id);
    if (window.matchMedia?.(PHONE_QUERY).matches) {
      requestAnimationFrame(() => inspector.current?.scrollIntoView?.({ block: "start", behavior: "auto" }));
    }
  };
  const [hideSystem, setHideSystem] = useState(false);
  const [technical, setTechnical] = useState(false);
  const node = run.nodes.find((n) => n.id === selected) ?? run.nodes[0];
  // Publisher fees are on the receipt (WorkReceipt reads the same cached query), not in `run.spent`.
  const receipt = useReceipt(run.id, run.status);
  const fees = receipt.data?.fees ?? [];
  const feeTotal = sumMoney(...fees.map((f) => f.amount));
  const total = sumMoney(run.spent.ai, run.spent.human, run.spent.tools, feeTotal);
  const events = hideSystem ? run.timeline.filter((e) => e.actor !== "system") : run.timeline;
  // The run has loaded by the time this renders; the tour waits for the receipt too, or its step would be dropped.
  // A receipt that fails or is not fetched at all counts as settled.
  useAutoTour("run", isSettled(receipt));

  // The finished example is a demo fixture: a live workspace has no such run, so it is not offered there.
  const demo = useIsDemo();
  const deliverable = run.deliverable ? (
    <ButtonLink href={`/app/runs/${run.id}/evidence`} className="w-full">
      {t("openDeliverable")}
    </ButtonLink>
  ) : (
    <p className="px-1 text-xs leading-relaxed text-muted">
      {demo
        ? t.rich("deliverablePending", {
            example: (chunks) => (
              <Link className="link" href="/app/runs/run_1042/evidence">
                {chunks}
              </Link>
            ),
          })
        : t("deliverablePendingLive")}
    </p>
  );

  return (
    <div className="space-y-5">
      {run.attention ? (
        <div data-tour="run-attention">
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
            {line(run.attention.body)}
          </Callout>
        </div>
      ) : null}
      {run.recovered ? (
        <Callout tone="info" title={t("recovered")}>
          {run.recovered}
        </Callout>
      ) : null}

      <OutcomeRail stages={run.stages} notes={run.stageNotes} />

      {/* A phone reads the page top to bottom: the deliverable and the way around come first. */}
      <div className="space-y-3 md:hidden">
        {deliverable}
        <nav aria-label={t("jumpTo")} className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          <span className="text-muted">{t("jumpTo")}</span>
          <a className="link py-2" href={`#${ANCHORS.steps}`}>
            {t("steps")}
          </a>
          <a className="link py-2" href={`#${ANCHORS.timeline}`}>
            {t("timeline")}
          </a>
          <a className="link py-2" href={`#${ANCHORS.cost}`}>
            {t("cost")}
          </a>
          <a className="link py-2" href={`#${ANCHORS.details}`}>
            {t("runDetails")}
          </a>
        </nav>
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_400px] 2xl:grid-cols-[minmax(0,1fr)_460px]">
        <section
          id={ANCHORS.steps}
          data-tour="run-steps"
          className="panel scroll-mt-24 overflow-hidden lg:scroll-mt-20 xl:col-span-2 2xl:col-span-1"
          aria-label={t("workflow")}
        >
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-rule px-5 py-3">
            <h2 className="h-section">{t("steps")}</h2>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
              <span className="flex items-center gap-1.5">
                <ActorGlyph actor="machine" className="size-2.5" />
                {t("legendAgent")}
              </span>
              <span className="flex items-center gap-1.5">
                <ActorGlyph actor="machine" className="size-2.5" />
                {t("legendApp")}
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
          {/* The canvas needs room to read; a phone gets the same steps as a list, in workflow order. */}
          <ol className="divide-y divide-rule md:hidden" aria-label={t("steps")}>
            {run.nodes.map((n) => (
              <li key={n.id}>
                <button
                  type="button"
                  aria-current={n.id === selected ? "true" : undefined}
                  onClick={() => choose(n.id)}
                  className={cn(
                    "flex min-h-12 w-full items-center gap-3 px-5 py-2.5 text-left",
                    n.id === selected && "bg-stage/60",
                  )}
                >
                  <ActorGlyph actor={n.actor} className="size-3" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium">{n.label}</span>
                    <span className="block text-xs text-muted">{tCanvas(`nodeType.${n.type satisfies NodeType}`)}</span>
                  </span>
                  <NodeStatusPill status={n.status} />
                </button>
              </li>
            ))}
          </ol>
          <div className="hidden h-[400px] bg-stage/60 md:block 2xl:h-[480px]">
            <RunCanvas run={run} selectedId={selected} onSelect={setSelected} />
          </div>
          <div className="hidden border-t border-rule px-5 py-2.5 text-xs text-muted md:block">{t("canvasHelp")}</div>
        </section>

        <Section
          data-tour="run-timeline"
          className="order-3 self-start xl:order-none"
          title={
            <span id={ANCHORS.timeline} className="scroll-mt-24 lg:scroll-mt-20">
              {t("timeline")}
            </span>
          }
          aside={<span className="text-xs text-muted">{t("pacificTime")}</span>}
        >
          <div className="flex flex-wrap gap-x-6 border-b border-rule px-5 py-1 sm:gap-y-2 sm:py-3">
            <Checkbox checked={hideSystem} onCheckedChange={setHideSystem} className="py-2.5 sm:py-0">
              {t("hideSystem")}
            </Checkbox>
            <Checkbox checked={technical} onCheckedChange={setTechnical} className="py-2.5 sm:py-0">
              {t("showTechnical")}
            </Checkbox>
          </div>
          {recordedLanguage ? (
            <p className="border-b border-rule px-5 py-2 text-xs leading-relaxed text-muted">{t("timelineNote")}</p>
          ) : null}
          <ol className="relative px-5 py-4">
            {events.map((e, i) => (
              <li key={i} className="relative grid grid-cols-[72px_16px_1fr] gap-x-3 pb-4 last:pb-0">
                <time className="tnum pt-px text-right text-xs text-muted" dateTime={e.at}>
                  {timeSec(e.at)}
                </time>
                <span className="relative flex justify-center pt-[3px]">
                  <ActorGlyph actor={e.actor} className="relative z-10 size-3" />
                  {i < events.length - 1 ? (
                    <span className="absolute top-4 bottom-[-14px] w-px bg-rule" aria-hidden />
                  ) : null}
                </span>
                <div className="min-w-0">
                  <button
                    type="button"
                    disabled={!e.nodeId}
                    onClick={() => e.nodeId && choose(e.nodeId)}
                    className={cn(
                      "text-left text-sm font-medium enabled:hover:underline",
                      e.tone === "blocked" && "text-blocked",
                    )}
                  >
                    {line(e.title)}
                  </button>
                  <div className="text-xs text-muted">
                    {who(e.who, e.actor)}
                    {technical && e.ref ? (
                      <>
                        {" "}
                        <Id className="ml-1 text-[11px]">{e.ref}</Id>
                      </>
                    ) : null}
                  </div>
                  {e.detail ? (
                    <p className="mt-1 max-w-[70ch] text-[13px] leading-snug text-grey-700">{line(e.detail)}</p>
                  ) : null}
                </div>
              </li>
            ))}
          </ol>
        </Section>

        <div className="order-2 space-y-5 self-start xl:order-none 2xl:sticky 2xl:top-20 2xl:col-start-2 2xl:row-span-2 2xl:row-start-1 2xl:max-h-[calc(100dvh-6rem)] 2xl:[scrollbar-width:thin] 2xl:[scrollbar-color:var(--color-grey-200)_transparent] 2xl:overflow-y-auto">
          <section
            ref={inspector}
            data-tour="run-step"
            className="panel scroll-mt-24 lg:scroll-mt-20"
            aria-label={t("selectedStep")}
          >
            <div className="border-b border-rule px-5 py-3">
              <h2 className="h-section">{t("selectedStep")}</h2>
            </div>
            <div className="px-5 py-4">
              <NodeInspector node={node} />
            </div>
          </section>
          <Section
            data-tour="run-cost"
            title={
              <span id={ANCHORS.cost} className="scroll-mt-24 lg:scroll-mt-20">
                {t("cost")}
              </span>
            }
            aside={<SimTag />}
          >
            <div className="px-5 py-2">
              <KeyValues
                rows={[
                  { label: t("agentsAndModels"), value: <span className="tnum">{money(run.spent.ai)}</span> },
                  { label: t("tools"), value: <span className="tnum">{money(run.spent.tools)}</span> },
                  { label: t("reviewerPay"), value: <span className="tnum">{money(run.spent.human)}</span> },
                  ...(fees.length
                    ? [{ label: t("publisherFees"), value: <span className="tnum">{money(feeTotal)}</span> }]
                    : []),
                  {
                    // A finished run's spend is its total; one still going shows what it has spent so far.
                    label: isFinishedRun(run.status) ? t("total") : t("totalSoFar"),
                    value: <span className="tnum font-semibold">{money(total)}</span>,
                  },
                  {
                    label: t("budget"),
                    value: <span className="tnum">{t("upTo", { amount: money(run.budget) })}</span>,
                  },
                ]}
              />
            </div>
          </Section>
          <CollapsibleSection id={ANCHORS.details} className="scroll-mt-24 lg:scroll-mt-20" title={t("runDetails")}>
            <div className="px-5 py-2">
              <KeyValues
                rows={[
                  {
                    label: t("started"),
                    value: t("startedBy", { when: dateTime(run.startedAt), name: who(run.startedBy, "buyer") }),
                  },
                  { label: t("input"), value: run.input },
                ]}
              />
              <TechnicalDetails
                className="my-3"
                rows={[
                  { label: tt("runId"), value: run.id },
                  { label: tt("workflow"), value: run.workflowRef },
                  { label: tt("contract"), value: run.contractRef },
                ]}
              />
            </div>
          </CollapsibleSection>
          <WorkReceipt runId={run.id} status={run.status} />
          <div className="hidden md:block">{deliverable}</div>
        </div>
      </div>
    </div>
  );
}
