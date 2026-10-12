"use client";

import Link from "next/link";
import { DataTable, type Column } from "@/components/data-table";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Stat } from "@/components/stat";
import { Amount, Id, Pill, Section, type Tone } from "@/components/ui";
import type { Invoice, Payout } from "@/lib/api/gen/types.gen";
import { money, pct } from "@/lib/format";
import { useBilling } from "@/lib/queries/billing";

const INVOICE_TONE: Record<Invoice["status"], Tone> = {
  overdue: "blocked",
  open: "human",
  paid: "ink",
  void: "quiet",
};
const INVOICE_LABEL: Record<Invoice["status"], string> = {
  overdue: "Overdue",
  open: "Open",
  paid: "Paid",
  void: "Void",
};
const PAYOUT_TONE: Record<Payout["status"], Tone> = { held: "human", paid: "ink", scheduled: "quiet" };
const PAYOUT_LABEL: Record<Payout["status"], string> = { held: "Held", paid: "Paid", scheduled: "Scheduled" };

const invoiceColumns: Column<Invoice>[] = [
  { key: "id", header: "Invoice", cell: (i) => <Id>{i.id}</Id> },
  {
    key: "tenant",
    header: "Tenant",
    cell: (i) => (
      <Link href={`/tenants/${i.tenantId}`} className="font-medium underline-offset-2 hover:underline">
        {i.tenantName}
      </Link>
    ),
  },
  { key: "period", header: "Period", cell: (i) => <span className="tnum">{i.period}</span> },
  { key: "amount", header: "Amount", numeric: true, cell: (i) => <Amount value={i.amount} /> },
  {
    key: "status",
    header: "Status",
    cell: (i) => <Pill tone={INVOICE_TONE[i.status]}>{INVOICE_LABEL[i.status]}</Pill>,
  },
];

const payoutColumns: Column<Payout>[] = [
  { key: "id", header: "Payout", cell: (p) => <Id>{p.id}</Id> },
  { key: "reviewer", header: "Reviewer", cell: (p) => <span className="font-medium">{p.reviewerName}</span> },
  { key: "amount", header: "Amount", numeric: true, cell: (p) => <Amount value={p.amount} /> },
  {
    key: "status",
    header: "Status",
    cell: (p) => <Pill tone={PAYOUT_TONE[p.status]}>{PAYOUT_LABEL[p.status]}</Pill>,
  },
];

export function BillingView() {
  const q = useBilling();
  return (
    <QueryState
      query={q}
      skeleton={
        <div className="space-y-6">
          <Skeleton className="h-24" />
          <Skeleton className="h-72" />
        </div>
      }
    >
      {(b) => (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
            <Stat label="MRR" value={money(b.mrr)} simulated />
            <Stat label="ARR" value={money(b.arr)} simulated />
            <Stat label="AI cost this month" value={money(b.aiCostMonth)} simulated />
            <Stat label="Gross margin" value={pct(b.grossMargin)} simulated />
            <Stat label="Reviewer payouts" value={money(b.reviewerPayoutsMonth)} sub="This month" simulated />
          </div>
          <Section
            title="Invoices"
            aside={<span className="tnum text-xs text-muted">{b.invoices.length} invoices</span>}
          >
            <DataTable
              label="Invoices"
              columns={invoiceColumns}
              rows={b.invoices}
              rowKey={(i) => i.id}
              empty="No invoices yet. They appear here once a tenant is billed."
            />
          </Section>
          <Section
            title="Reviewer payouts"
            aside={<span className="tnum text-xs text-muted">{b.payouts.length} payouts</span>}
          >
            <DataTable
              label="Reviewer payouts"
              columns={payoutColumns}
              rows={b.payouts}
              rowKey={(p) => p.id}
              empty="No payouts yet. They appear once a reviewer completes paid work."
            />
          </Section>
        </div>
      )}
    </QueryState>
  );
}
