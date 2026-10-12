"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { Amount, Id, KeyValues, PageHeader, Pill, Section, SimTag } from "@/components/ui";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { useUsage } from "@/lib/queries/workspace";
import type { LedgerTxn, Organization } from "@/lib/types";
import { useFormat } from "@/lib/use-format";

const STATUS_TONE = { POSTED: "ink", ELIGIBLE: "machine", PENDING: "quiet", HELD: "human" } as const;

function UsageHeader() {
  const t = useTranslations("usage");
  return (
    <PageHeader
      title={t("title")}
      lede={t("lede")}
      actions={<SimTag className="px-2 py-1 text-xs">{t("simulated")}</SimTag>}
    />
  );
}

function UsageBody({ ORG, LEDGER }: { ORG: Organization; LEDGER: LedgerTxn[] }) {
  const t = useTranslations("usage");
  const tc = useTranslations("common");
  const { dateTime, money } = useFormat();
  const pct = Math.round((ORG.monthSpent.amountMinor / ORG.monthlyCap.amountMinor) * 100);
  return (
    <>
      <UsageHeader />
      <div className="space-y-6">
        <div className="grid gap-px overflow-hidden rounded-[12px] border border-rule bg-rule sm:grid-cols-2 xl:grid-cols-4">
          <div className="bg-paper px-5 py-4">
            <div className="label">{t("spent")}</div>
            <Amount value={ORG.monthSpent} className="mt-1 block text-2xl font-semibold tracking-tight" />
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-grey-100" aria-hidden>
              <div className="h-full bg-ink" style={{ width: `${pct}%` }} />
            </div>
            <div className="mt-1.5 text-xs text-muted">{t("ofCap", { pct, cap: money(ORG.monthlyCap) })}</div>
          </div>
          <div className="bg-paper px-5 py-4">
            <div className="label">{t("held")}</div>
            <Amount value={5000} className="mt-1 block text-2xl font-semibold tracking-tight" />
            <div className="mt-1.5 text-xs text-muted">
              {t.rich("heldNote", {
                run: (chunks) => (
                  <Link className="link" href="/app/runs/run_1047">
                    {chunks}
                  </Link>
                ),
              })}
            </div>
          </div>
          <div className="bg-paper px-5 py-4">
            <div className="label">{tc("agentsModelsTools")}</div>
            <Amount
              value={ORG.monthSpent.amountMinor - 4900 - 750}
              className="mt-1 block text-2xl font-semibold tracking-tight"
            />
            <div className="mt-1.5 text-xs text-muted">{t("agentsToolsNote", { plan: money(4900) })}</div>
          </div>
          <div className="bg-paper px-5 py-4">
            <div className="label">{t("reviewerPay")}</div>
            <Amount value={1150} className="mt-1 block text-2xl font-semibold tracking-tight" />
            <div className="mt-1.5 text-xs text-muted">{t("reviewerPayNote", { n: 2, absorbed: money(400) })}</div>
          </div>
        </div>

        <div className="grid grid-cols-1 items-start gap-6 2xl:grid-cols-[minmax(0,1fr)_420px]">
          <Section title={t("ledger")} aside={<span className="text-xs text-muted">{t("ledgerNote")}</span>}>
            <ul className="divide-y divide-rule">
              {LEDGER.map((txn) => (
                <li key={txn.id}>
                  <details className="group">
                    <summary className="grid cursor-pointer list-none grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1 px-5 py-3 hover:bg-grey-50/60 sm:grid-cols-[150px_1fr_110px_100px]">
                      <span className="order-3 text-xs text-muted sm:order-none">{dateTime(txn.at)}</span>
                      <span className="text-sm">
                        {txn.description}
                        {txn.runId ? <Id className="ml-2 text-[11px]">{txn.runId}</Id> : null}
                      </span>
                      <span className="hidden sm:block">
                        <Pill tone={STATUS_TONE[txn.status]}>{t(`status.${txn.status}`)}</Pill>
                      </span>
                      <Amount value={txn.amount} className="text-right text-sm font-medium" />
                    </summary>
                    <table className="mx-5 mb-3 w-[calc(100%-2.5rem)] text-xs">
                      <thead>
                        <tr className="text-left text-muted">
                          <th className="py-1 font-medium">{t("account")}</th>
                          <th className="py-1 text-right font-medium">{t("debit")}</th>
                          <th className="py-1 text-right font-medium">{t("credit")}</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-rule">
                        {txn.lines.map((l, i) => (
                          <tr key={i}>
                            <td className="py-1.5">{l.account}</td>
                            <td className="tnum py-1.5 text-right">{l.debit ? money(l.debit) : ""}</td>
                            <td className="tnum py-1.5 text-right">{l.credit ? money(l.credit) : ""}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </details>
                </li>
              ))}
            </ul>
          </Section>

          <Section title={t("plan")}>
            <div className="px-5 py-2">
              <KeyValues
                rows={[
                  { label: t("plan"), value: t("planValue", { plan: ORG.plan, price: money(4900) }) },
                  { label: t("includes"), value: t("includesValue") },
                  { label: t("payment"), value: t("paymentValue") },
                ]}
              />
            </div>
          </Section>
        </div>
      </div>
    </>
  );
}

export function UsageView() {
  const usage = useUsage();
  return (
    <QueryState
      query={usage}
      skeleton={
        <>
          <UsageHeader />
          <Skeleton className="h-96" />
        </>
      }
    >
      {({ org, ledger }) => <UsageBody ORG={org} LEDGER={ledger} />}
    </QueryState>
  );
}
