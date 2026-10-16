"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { PublisherFeeRows } from "@/components/publisher-fee-rows";
import type { FeeItem } from "@/lib/api/gen";
import { Amount, ButtonLink, EmptyState, Id, KeyValues, PageHeader, Pill, Section, SimTag } from "@/components/ui";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { useNow } from "@/lib/clock";
import { usd } from "@/lib/format";
import { useIsDemo } from "@/lib/queries/me";
import { useUsage } from "@/lib/queries/workspace";
import { monthOf, spendSplit } from "@/lib/spend";
import type { LedgerTxn, Organization } from "@/lib/types";
import { useFormat } from "@/lib/use-format";

const STATUS_TONE = { POSTED: "ink", ELIGIBLE: "machine", PENDING: "quiet", HELD: "human" } as const;
/** A ledger cell with no amount on its side, so a line with only a debit or only a credit never reads as blank. */
const NO_AMOUNT = "—";

function UsageHeader() {
  const t = useTranslations("usage");
  const demo = useIsDemo();
  return (
    <PageHeader
      title={t("title")}
      lede={demo ? t("lede") : t("ledeLive")}
      actions={<SimTag className="px-2 py-1 text-xs">{t("simulated")}</SimTag>}
    />
  );
}

/** The itemized publisher fees behind a run's "Publisher fees" ledger line, folded until asked for. */
function FeeItems({ txnId, fees }: { txnId: string; fees: FeeItem[] }) {
  const t = useTranslations("publisherFees");
  const [open, setOpen] = useState(false);
  const regionId = `fees-${txnId}`;
  return (
    <div className="mx-5 mb-3 text-xs">
      <button
        type="button"
        className="link inline-flex min-h-10 items-center py-2 sm:min-h-8 sm:py-1"
        aria-expanded={open}
        aria-controls={open ? regionId : undefined}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? t("hide") : t("show")}
      </button>
      {open ? (
        <div id={regionId} className="mt-1">
          <div className="flex items-center justify-between gap-2">
            <span className="label">{t("title")}</span>
            <SimTag>{t("simulated")}</SimTag>
          </div>
          <PublisherFeeRows fees={fees} />
        </div>
      ) : null}
    </div>
  );
}

// The ledger's accounts, by the English name the API sends, keyed for translation; any other account shows as it came.
type AccountKey = "aiUsage" | "toolUsage" | "humanReview" | "publisherFees";
const ACCOUNT_KEYS: Record<string, AccountKey | undefined> = {
  "AI usage": "aiUsage",
  "Tool usage": "toolUsage",
  "Human review": "humanReview",
  "Publisher fees": "publisherFees",
};

function Ledger({ ledger }: { ledger: LedgerTxn[] }) {
  const t = useTranslations("usage");
  const { dateTime, money } = useFormat();
  const accountText = (account: string) => {
    const key = ACCOUNT_KEYS[account];
    return key ? t(`accounts.${key}`) : account;
  };
  if (ledger.length === 0) {
    return (
      <EmptyState
        action={
          <ButtonLink href="/app/runs/new" variant="secondary" className="h-10 sm:h-8">
            {t("startRun")}
          </ButtonLink>
        }
      >
        {t("emptyLedger")}
      </EmptyState>
    );
  }
  return (
    <ul className="divide-y divide-rule">
      {ledger.map((txn) => (
        <li key={txn.id}>
          <details className="group">
            <summary className="grid cursor-pointer list-none grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1 px-5 py-3 hover:bg-grey-50/60 sm:grid-cols-[150px_1fr_110px_100px]">
              <span className="order-3 text-xs text-muted sm:order-none">{dateTime(txn.at)}</span>
              {/* The link to the run lives in the opened panel, not in the summary, so tapping the title only toggles. */}
              <span className="min-w-0 text-sm">
                {txn.description}
                {txn.runId && !txn.description.includes(txn.runId) ? (
                  <Id className="mt-0.5 block text-[11px] text-muted">{txn.runId}</Id>
                ) : null}
              </span>
              <span className="hidden sm:block">
                <Pill tone={STATUS_TONE[txn.status]}>{t(`status.${txn.status}`)}</Pill>
              </span>
              <Amount value={txn.amount} className="text-right text-sm font-medium" />
            </summary>
            {txn.runId ? (
              <p className="mx-5 mb-2 text-xs">
                <Link className="link" href={`/app/runs/${txn.runId}`}>
                  {t("viewRun")}
                </Link>
              </p>
            ) : null}
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
                    <td className="py-1.5">{accountText(l.account)}</td>
                    <td className="tnum py-1.5 text-right text-muted">{l.debit ? money(l.debit) : NO_AMOUNT}</td>
                    <td className="tnum py-1.5 text-right text-muted">{l.credit ? money(l.credit) : NO_AMOUNT}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {txn.fees && txn.fees.length > 0 ? <FeeItems txnId={txn.id} fees={txn.fees} /> : null}
          </details>
        </li>
      ))}
    </ul>
  );
}

function UsageBody({ ORG, LEDGER }: { ORG: Organization; LEDGER: LedgerTxn[] }) {
  const t = useTranslations("usage");
  const tc = useTranslations("common");
  const { money, monthName } = useFormat();
  const demo = useIsDemo();
  const now = new Date(useNow());
  const split = spendSplit(ORG, LEDGER, monthOf(now));
  const cap = ORG.monthlyCap.amountMinor;
  const pct = cap > 0 ? Math.round((ORG.monthSpent.amountMinor / cap) * 100) : 0;
  const heldRun = split.heldRuns.length === 1 ? split.heldRuns[0] : undefined;
  const hasPlanFee = split.plan.amountMinor > 0;
  return (
    <>
      <UsageHeader />
      <div className="space-y-6">
        <div className="grid gap-px overflow-hidden rounded-[12px] border border-rule bg-rule sm:grid-cols-2 xl:grid-cols-4">
          <div className="bg-paper px-5 py-4">
            <div className="label">{t("spent", { month: monthName(now) })}</div>
            <Amount value={ORG.monthSpent} className="mt-1 block text-2xl font-semibold tracking-tight" />
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-grey-100" aria-hidden>
              <div className="h-full bg-ink" style={{ width: `${Math.min(100, pct)}%` }} />
            </div>
            <div className="mt-1.5 text-xs text-muted">{t("ofCap", { pct, cap: money(ORG.monthlyCap) })}</div>
          </div>
          <div className="bg-paper px-5 py-4">
            <div className="label">{t("held")}</div>
            <Amount value={split.held} className="mt-1 block text-2xl font-semibold tracking-tight" />
            <div className="mt-1.5 text-xs text-muted">
              {heldRun
                ? t.rich("heldNote", {
                    id: heldRun,
                    run: (chunks) => (
                      <Link className="link" href={`/app/runs/${heldRun}`}>
                        {chunks}
                      </Link>
                    ),
                  })
                : split.heldRuns.length > 1
                  ? t("heldNoteMany", { n: split.heldRuns.length })
                  : t("heldNone")}
            </div>
          </div>
          <div className="bg-paper px-5 py-4">
            <div className="label">{tc("agentsModelsTools")}</div>
            {/* Publisher fees get their own line here rather than being folded into this figure. */}
            <Amount value={split.agentsExclFees} className="mt-1 block text-2xl font-semibold tracking-tight" />
            <div className="mt-1.5 text-xs text-muted">
              {hasPlanFee ? t("agentsToolsNote", { plan: money(split.plan) }) : t("agentsToolsNoteNoPlan")}
            </div>
            {split.fees.amountMinor > 0 ? (
              <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs">
                <span>{t("publisherFeesLine", { fees: money(split.fees) })}</span>
                <SimTag />
              </div>
            ) : null}
          </div>
          <div className="bg-paper px-5 py-4">
            <div className="label">{t("reviewerPay")}</div>
            <Amount value={split.reviewerPayTotal} className="mt-1 block text-2xl font-semibold tracking-tight" />
            <div className="mt-1.5 text-xs text-muted">
              {t("reviewerPayNote", { n: split.reviewerPayments })}
              {split.absorbed.amountMinor > 0
                ? ` ${t("reviewerPayAbsorbed", { absorbed: money(split.absorbed) })}`
                : ""}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 items-start gap-6 2xl:grid-cols-[minmax(0,1fr)_420px]">
          <Section title={t("ledger")} aside={<span className="text-xs text-muted">{t("ledgerNote")}</span>}>
            <Ledger ledger={LEDGER} />
          </Section>

          <Section title={t("planTitle")}>
            <div className="px-5 py-2">
              <KeyValues
                rows={[
                  {
                    label: t("plan"),
                    value: hasPlanFee
                      ? t("planValue", { plan: ORG.plan, price: money(split.plan) })
                      : t("planValueFree", { plan: ORG.plan }),
                  },
                  ...(demo ? [{ label: t("includes"), value: t("includesValue") }] : []),
                  { label: t("payment"), value: demo ? t("paymentValue") : t("paymentValueLive") },
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
