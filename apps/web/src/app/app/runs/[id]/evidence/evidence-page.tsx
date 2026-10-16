"use client";

import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { notFound } from "next/navigation";
import { QueryState } from "@/components/query-state";
import { useCodes, useWho } from "@/components/run-codes";
import { TechnicalDetails } from "@/components/run-disclosures";
import { Skeleton } from "@/components/skeleton";
import {
  ActorGlyph,
  ActorLabel,
  ButtonLink,
  EmptyState,
  KeyValues,
  OutcomeRail,
  PageHeader,
  Section,
  SimTag,
} from "@/components/ui";
import { INTL_TAGS, resolveLocale } from "@/i18n/locales";
import { ApiError } from "@/lib/api/errors";
import { sumMoney } from "@/lib/format";
import { useReceipt, useRun } from "@/lib/queries/runs";
import type { Run } from "@/lib/types";
import { useFormat } from "@/lib/use-format";
import { RECONCILIATION_PACK, changed, moneyText, toolKey, toolUse } from "./run-facts";

export function EvidencePage({ id }: { id: string }) {
  const run = useRun(id);
  if (run.error instanceof ApiError && run.error.status === 404) notFound();
  return (
    <QueryState
      query={run}
      skeleton={
        <div className="space-y-5">
          <Skeleton className="h-16 w-2/3" />
          <Skeleton className="h-[400px]" />
        </div>
      }
    >
      {(r) => (r.deliverable ? <Evidence run={r} deliverable={r.deliverable} /> : <EvidencePending run={r} />)}
    </QueryState>
  );
}

/** A run that exists but has not produced its deliverable yet: the page says so instead of a 404. */
function EvidencePending({ run }: { run: Run }) {
  const t = useTranslations("run.evidence");
  const ended = ["COMPLETED", "FAILED", "CANCELLED"].includes(run.status);
  return (
    <>
      <title>{`${t("pageTitle")} | New Machines`}</title>
      <PageHeader title={t("pageTitle")} lede={run.title} />
      <div className="panel">
        <EmptyState
          action={
            <ButtonLink href={`/app/runs/${run.id}`} variant="secondary" className="h-10 sm:h-8">
              {t("backToRun")}
            </ButtonLink>
          }
        >
          {ended ? t("pendingEnded") : t("pending")}
        </EmptyState>
      </div>
    </>
  );
}

function Evidence({ run, deliverable: d }: { run: Run; deliverable: NonNullable<Run["deliverable"]> }) {
  const t = useTranslations("run.evidence");
  const tc = useTranslations("common");
  const tt = useTranslations("run.technical");
  const locale = INTL_TAGS[resolveLocale(useLocale())];
  const { dateTime, money } = useFormat();
  const { line } = useCodes();
  const who = useWho();
  // Publisher fees are on the receipt, not in `run.spent`; a demo run has none.
  const fees = useReceipt(run.id, run.status).data?.fees ?? [];
  const feeTotal = sumMoney(...fees.map((f) => f.amount));
  const total = sumMoney(run.spent.ai, run.spent.human, run.spent.tools, feeTotal);

  // PRODUCT.md WORK-04: the evidence viewer answers seven questions.
  const parts = run.timeline.filter((e) => e.actor !== "system");
  // The reconciliation pack's page keeps its written contract and basis; any other pack's are built from the
  // run itself. What the run was permitted to do always comes from its own tool calls.
  const written = run.packSlug === RECONCILIATION_PACK;

  return (
    <>
      <title>{`${t("pageTitle")} | New Machines`}</title>
      <PageHeader title={d.title} lede={d.summary}>
        <div className="mb-2 flex items-center gap-2 text-sm text-muted">
          {t("fromRun")}{" "}
          <Link href={`/app/runs/${run.id}`} className="link">
            {run.title}
          </Link>
        </div>
      </PageHeader>

      <div className="space-y-6">
        <OutcomeRail stages={run.stages} notes={run.stageNotes} />

        <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
          <div className="space-y-6">
            <Section title={t("deliverable")} aside={<span className="text-xs text-muted">{d.kind}</span>}>
              <dl className="grid grid-cols-2 gap-px bg-rule sm:grid-cols-3">
                {d.rows.map((r) => (
                  <div key={r.label} className="bg-paper px-5 py-4">
                    <dt className="label">{r.label}</dt>
                    <dd className="tnum mt-1 text-lg font-semibold tracking-tight">{moneyText(r.value, locale)}</dd>
                  </div>
                ))}
              </dl>
            </Section>

            {d.items && d.items.length > 0 ? (
              <Section
                title={t("items")}
                aside={<span className="text-xs text-muted">{t("itemCount", { n: d.items.length })}</span>}
              >
                <ul className="divide-y divide-rule">
                  {d.items.map((item, i) => (
                    <li key={i} className="px-5 py-3">
                      <div className="text-sm font-medium break-words">{item.label}</div>
                      <p className="mt-1 text-[13px] leading-snug break-words whitespace-pre-line text-grey-700">
                        {item.detail}
                      </p>
                    </li>
                  ))}
                </ul>
              </Section>
            ) : null}

            <Section title={t("requested")}>
              <div className="px-5 py-2">
                <KeyValues
                  rows={[
                    { label: t("input"), value: run.input },
                    // What the contract promises, in words; its version is a technical detail below.
                    ...(written
                      ? [{ label: t("contract"), value: t("contractValue") }]
                      : run.outcome
                        ? [{ label: t("contract"), value: run.outcome }]
                        : []),
                    {
                      label: t("requestedBy"),
                      value: `${who(run.startedBy, "buyer")}, ${dateTime(run.startedAt)}`,
                    },
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
            </Section>

            <Section title={t("whoDid")}>
              <ul className="divide-y divide-rule">
                {parts.map((e, i) => (
                  <li key={i} className="grid grid-cols-[16px_1fr_auto] items-start gap-3 px-5 py-3 text-sm">
                    <ActorGlyph actor={e.actor} className="mt-1 size-3" />
                    <div>
                      <span className="font-medium">{who(e.who, e.actor)}</span>
                      <span className="text-grey-700">: {line(e.title)}</span>
                    </div>
                    <span className="text-xs text-muted">
                      <ActorLabel actor={e.actor} />
                    </span>
                  </li>
                ))}
              </ul>
            </Section>

            <Section title={t("permitted")}>
              <ToolUseList run={run} />
            </Section>
          </div>

          <div className="space-y-6">
            <Section title={t("evidence")}>
              {d.evidence.length > 0 ? (
                <>
                  <ul className="divide-y divide-rule">
                    {d.evidence.map((e) => (
                      <li key={e.id} className="px-5 py-3">
                        <div className="flex items-center gap-2 text-sm font-medium">
                          <ActorGlyph actor={e.by} />
                          {e.label}
                        </div>
                        <div className="mt-0.5 pl-5 text-xs text-muted">{who(e.who, e.by)}</div>
                      </li>
                    ))}
                  </ul>
                  <div className="px-5 pb-4">
                    <TechnicalDetails rows={d.evidence.map((e) => ({ label: e.label, value: e.id }))} />
                  </div>
                </>
              ) : (
                <p className="px-5 py-4 text-sm text-muted">{t("noEvidence")}</p>
              )}
            </Section>
            <Section title={t("open")}>
              {d.unresolved.length > 0 ? (
                <ul className="space-y-2 px-5 py-4 text-sm">
                  {d.unresolved.map((u) => (
                    <li key={u}>{u}</li>
                  ))}
                </ul>
              ) : (
                <p className="px-5 py-4 text-sm text-muted">{t("nothingOpen")}</p>
              )}
            </Section>
            <Section title={t("limitations")}>
              <ul className="list-disc space-y-1.5 py-4 pr-5 pl-9 text-sm text-grey-700">
                {d.limitations.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </Section>
            <Section title={t("billable")} aside={<SimTag />}>
              <div className="px-5 py-2">
                <KeyValues
                  rows={[
                    {
                      label: t("agentsTools"),
                      value: <span className="tnum">{money(sumMoney(run.spent.ai, run.spent.tools))}</span>,
                    },
                    { label: tc("reviewerPay"), value: <span className="tnum">{money(run.spent.human)}</span> },
                    ...(fees.length
                      ? [{ label: t("publisherFees"), value: <span className="tnum">{money(feeTotal)}</span> }]
                      : []),
                    { label: t("total"), value: <span className="tnum font-semibold">{money(total)}</span> },
                    {
                      label: t("basis"),
                      value: written ? <WrittenBasis run={run} /> : <Basis run={run} />,
                    },
                  ]}
                />
              </div>
            </Section>
          </div>
        </div>
      </div>
    </>
  );
}

/** What the run did outside New Machines, from its own tool calls: each app and action, read or write, how
 * many times, whether a write ran after your approval and whether it used sandbox data. */
function ToolUseList({ run }: { run: Run }) {
  const t = useTranslations("run.evidence");
  const gap = sentenceGap(useLocale());
  const uses = toolUse(run);
  return (
    <div className="px-5 py-4 text-sm leading-relaxed">
      {uses.length > 0 ? (
        <ul className="space-y-1.5">
          {uses.map((u) => (
            <li key={toolKey(u)}>
              <span className="font-medium">{t("toolLine", { app: u.app, action: u.action })}</span>
              <span className="text-grey-700">
                {gap}
                {t("toolUse", {
                  kind: u.kind,
                  n: u.ran,
                  approval: u.approval === "n/a" ? "na" : u.approval,
                  sandbox: u.sandbox,
                })}
                {u.notRun > 0 ? `${gap}${t("toolNotRun", { n: u.notRun })}` : null}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      <p className={uses.length > 0 ? "mt-2 text-muted" : "text-muted"}>{t(`changed.${changed(uses)}`)}</p>
    </div>
  );
}

/** Why the run is billable, from its outcome stages. */
function Basis({ run }: { run: Run }) {
  const t = useTranslations("run.evidence");
  const gap = sentenceGap(useLocale());
  const { stages } = run;
  // "not_required": the run ended without a verification node (a pack's nothing-to-do path).
  const parts = [
    stages.verified === "done"
      ? t("basisVerified")
      : stages.verified === "not_required"
        ? t("basisNoCheck")
        : t("basisNotVerified"),
  ];
  if (stages.accepted === "done") parts.push(t("basisAccepted"));
  else if (stages.accepted === "not_required") parts.push(t("basisNoAcceptance"));
  else if (stages.accepted === "pending") parts.push(t("basisPendingAcceptance"));
  else parts.push(t("basisAcceptanceNotGiven"));
  if (reviewerPaid(run)) parts.push(t("basisReviewerPay"));
  return <>{parts.join(gap)}</>;
}

/** The reconciliation pack's written basis; its reviewer pay sentence only when a reviewer was paid. */
function WrittenBasis({ run }: { run: Run }) {
  const t = useTranslations("run.evidence");
  const gap = sentenceGap(useLocale());
  const parts = [t("basisValue", { accepted: run.stages.accepted })];
  if (reviewerPaid(run)) parts.push(t("basisValueReviewerPay"));
  return <>{parts.join(gap)}</>;
}

/** Whether a person was paid to review this run's work. */
const reviewerPaid = (run: Run) => run.spent.human.amountMinor > 0;

/** What goes between two sentences: Japanese sentences run on without a space. */
const sentenceGap = (locale: string) => (locale === "ja" ? "" : " ");
