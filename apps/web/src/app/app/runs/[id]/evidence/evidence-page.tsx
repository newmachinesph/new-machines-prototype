"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { notFound } from "next/navigation";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { ActorGlyph, ActorLabel, Id, KeyValues, OutcomeRail, PageHeader, Section, SimTag } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import { sumMoney } from "@/lib/format";
import { useRun } from "@/lib/queries/runs";
import type { Run } from "@/lib/types";
import { useFormat } from "@/lib/use-format";

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
      {(r) => <Evidence run={r} />}
    </QueryState>
  );
}

function Evidence({ run }: { run: Run }) {
  const t = useTranslations("run.evidence");
  const tc = useTranslations("common");
  const { dateTime, money } = useFormat();
  const d = run.deliverable;
  if (!d) notFound();
  const total = sumMoney(run.spent.ai, run.spent.human, run.spent.tools);

  // PRODUCT.md WORK-04: the evidence viewer answers seven questions.
  const who = run.timeline.filter((e) => e.actor !== "system");

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
                    <dd className="tnum mt-1 text-lg font-semibold tracking-tight">{r.value}</dd>
                  </div>
                ))}
              </dl>
            </Section>

            <Section title={t("requested")}>
              <div className="px-5 py-2">
                <KeyValues
                  rows={[
                    { label: t("input"), value: run.input },
                    {
                      label: t("contract"),
                      value: (
                        <span>
                          {t.rich("contractValue", {
                            ref: run.contractRef,
                            mono: (chunks) => <Id>{chunks}</Id>,
                          })}
                        </span>
                      ),
                    },
                    { label: t("requestedBy"), value: `${run.startedBy}, ${dateTime(run.startedAt)}` },
                  ]}
                />
              </div>
            </Section>

            <Section title={t("whoDid")}>
              <ul className="divide-y divide-rule">
                {who.map((e, i) => (
                  <li key={i} className="grid grid-cols-[16px_1fr_auto] items-start gap-3 px-5 py-3 text-sm">
                    <ActorGlyph actor={e.actor} className="mt-1 size-3" />
                    <div>
                      <span className="font-medium">{e.who}</span>
                      <span className="text-grey-700">: {e.title}</span>
                    </div>
                    <span className="text-xs text-muted">
                      <ActorLabel actor={e.actor} />
                    </span>
                  </li>
                ))}
              </ul>
            </Section>

            <Section title={t("permitted")}>
              <div className="px-5 py-4 text-sm leading-relaxed">
                <p>{t("permittedBody")}</p>
                <p className="mt-2 text-muted">{t("permittedNote")}</p>
              </div>
            </Section>
          </div>

          <div className="space-y-6">
            <Section title={t("evidence")}>
              <ul className="divide-y divide-rule">
                {d.evidence.map((e) => (
                  <li key={e.id} className="px-5 py-3">
                    <div className="flex items-center gap-2 text-sm font-medium">
                      <ActorGlyph actor={e.by} />
                      {e.label}
                    </div>
                    <div className="mt-0.5 flex items-center gap-2 pl-5 text-xs text-muted">
                      {e.who} <Id className="text-[11px]">{e.id}</Id>
                    </div>
                  </li>
                ))}
              </ul>
            </Section>
            <Section title={t("open")}>
              <ul className="space-y-2 px-5 py-4 text-sm">
                {d.unresolved.map((u) => (
                  <li key={u}>{u}</li>
                ))}
              </ul>
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
                    { label: t("total"), value: <span className="tnum font-semibold">{money(total)}</span> },
                    {
                      label: t("basis"),
                      value: t("basisValue"),
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
