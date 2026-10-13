"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { type Column, DataTable } from "@/components/data-table";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Amount, Id, KeyValues, PageHeader, Pill, RunStatusPill, Section, SimTag, type Tone } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import type { DecisionRecord, OpsRunDetail, Receipt, ReceiptItem, RunNode, ToolCall } from "@/lib/api/gen/types.gen";
import { dateTime, time } from "@/lib/format";
import { useOpsRun } from "@/lib/queries/runs";
import { definitionHref, isKind } from "../../definitions/_components/definition-logic";

/** Enough of a SHA-256 to tell entries apart at a glance; the full hash is in the title. */
const HASH_PREFIX = 12;
const prefix = (hash: string) => hash.slice(0, HASH_PREFIX);

const NODE_STATUS: Record<RunNode["status"], { label: string; tone: Tone }> = {
  CREATED: { label: "Not started", tone: "quiet" },
  READY: { label: "Ready", tone: "quiet" },
  RUNNING: { label: "Running", tone: "machine" },
  WAITING: { label: "Waiting", tone: "human" },
  VALIDATING: { label: "Validating", tone: "machine" },
  COMPLETED: { label: "Completed", tone: "ink" },
  FAILED: { label: "Failed", tone: "blocked" },
  REJECTED: { label: "Rejected", tone: "blocked" },
  TIMED_OUT: { label: "Timed out", tone: "blocked" },
  CANCELLED: { label: "Cancelled", tone: "quiet" },
  COMPENSATING: { label: "Compensating", tone: "machine" },
  ESCALATED: { label: "Escalated", tone: "human" },
  BLOCKED: { label: "Blocked", tone: "blocked" },
  SKIPPED: { label: "Skipped", tone: "quiet" },
};

const NODE_TYPE: Record<RunNode["type"], string> = {
  trigger: "Trigger",
  connector: "Connector",
  parallel: "Parallel",
  join: "Join",
  agent: "Agent",
  decision: "Decision",
  human_workforce: "Reviewer",
  approval: "Approval",
  verification: "Verification",
  memory: "Memory",
  end: "End",
};

const VERDICT: Record<DecisionRecord["verdict"], { label: string; tone: Tone }> = {
  APPROVED: { label: "Approved", tone: "ink" },
  REJECTED: { label: "Rejected", tone: "blocked" },
  REVISION_REQUIRED: { label: "Revision required", tone: "human" },
  HUMAN_REVIEW: { label: "Human review", tone: "human" },
  ESCALATED: { label: "Escalated", tone: "human" },
  ERROR: { label: "Error", tone: "blocked" },
  TIMED_OUT: { label: "Timed out", tone: "blocked" },
  BLOCKED: { label: "Blocked", tone: "blocked" },
};

const POLICY: Record<ToolCall["policy"], string> = {
  PERMIT: "permitted",
  DENY: "denied",
  REQUIRE_APPROVAL: "needs approval",
};

const sentence = (s: string) => s.charAt(0) + s.slice(1).toLowerCase().replaceAll("_", " ");

/** A real run as the runtime recorded it: its projection and its hash-chained work receipt, verified on load. */
export function RunDetail({ id }: { id: string }) {
  const query = useOpsRun(id);
  if (query.error instanceof ApiError && query.error.status === 404) {
    return (
      <>
        <BackLink />
        <Section className="p-6">
          <h1 tabIndex={-1} className="h-page outline-none">
            No real run {id}
          </h1>
          <p className="mt-2 max-w-[60ch] text-sm text-muted">
            Only runs started on the local runtime have a step record and a receipt here. Demo runs from fixtures do
            not, and neither does anything while the runtime is off.
          </p>
        </Section>
      </>
    );
  }
  return (
    <QueryState query={query} skeleton={<Skeleton className="h-96" />}>
      {(detail) => <RunBody detail={detail} />}
    </QueryState>
  );
}

function BackLink() {
  return (
    <Link href="/runs" className="mb-3 inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink">
      <ArrowLeft className="size-4" aria-hidden />
      Runs
    </Link>
  );
}

function RunBody({ detail }: { detail: OpsRunDetail }) {
  const { run, receipt } = detail;
  const total = run.spent.ai.amountMinor + run.spent.human.amountMinor + run.spent.tools.amountMinor;
  return (
    <>
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {run.title}
            <RunStatusPill status={run.status} />
          </span>
        }
        lede={run.summary}
      >
        <BackLink />
      </PageHeader>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-4">
          <Section title="Steps">
            <DataTable
              label="Steps"
              columns={STEP_COLUMNS}
              rows={run.nodes}
              rowKey={(n) => n.id}
              empty="No steps recorded yet."
              maxHeight="max-h-none"
            />
          </Section>
          <ReceiptSection receipt={receipt} />
        </div>
        <div className="space-y-4">
          <Section title="Run">
            <KeyValues
              className="px-5"
              rows={[
                { label: "Run", value: <Id>{run.id}</Id> },
                {
                  label: "Pack",
                  value: (
                    <Link href={`/marketplace/${run.packSlug}`} className="underline-offset-2 hover:underline">
                      {run.packSlug}
                    </Link>
                  ),
                },
                { label: "Started by", value: <span className="break-all">{run.startedBy}</span> },
                { label: "Started", value: dateTime(run.startedAt) },
                ...(run.endedAt ? [{ label: "Ended", value: dateTime(run.endedAt) }] : []),
                { label: "Input", value: run.input },
                { label: "Workflow", value: <Id>{run.workflowRef}</Id> },
                { label: "Contract", value: <Id>{run.contractRef}</Id> },
              ]}
            />
          </Section>
          <Section title="Spend">
            <KeyValues
              className="px-5"
              rows={[
                { label: "Budget", value: <Amount value={run.budget} /> },
                { label: "AI work", value: <Amount value={run.spent.ai} /> },
                { label: "People", value: <Amount value={run.spent.human} /> },
                { label: "Tools", value: <Amount value={run.spent.tools} /> },
                {
                  label: "Total",
                  value: (
                    <Amount value={{ amountMinor: total, currency: run.budget.currency }} className="font-medium" />
                  ),
                },
              ]}
            />
          </Section>
        </div>
      </div>
    </>
  );
}

const STEP_COLUMNS: Column<RunNode>[] = [
  {
    key: "step",
    header: "Step",
    cell: (n) => (
      <span className="block min-w-0">
        <span className="block font-medium">{n.label}</span>
        <span className="block text-xs text-muted">
          {NODE_TYPE[n.type]} · <Id>{n.id}</Id>
        </span>
      </span>
    ),
  },
  {
    key: "status",
    header: "Status",
    cell: (n) => (
      <Pill tone={NODE_STATUS[n.status].tone} live={n.status === "RUNNING"}>
        {NODE_STATUS[n.status].label}
      </Pill>
    ),
  },
  { key: "detail", header: "Detail", cell: (n) => <StepDetail node={n} /> },
  {
    key: "cost",
    header: "Cost",
    numeric: true,
    className: "hidden md:table-cell",
    cell: (n) => (n.cost ? <Amount value={n.cost} /> : <span className="text-muted">None</span>),
  },
];

function StepDetail({ node }: { node: RunNode }) {
  const calls = node.toolCalls ?? [];
  const decision = node.decision;
  if (!decision && !calls.length && !node.note && !node.subtitle) return <span className="text-muted">None</span>;
  return (
    <div className="max-w-[60ch] space-y-1.5">
      {decision ? (
        <div>
          <Pill tone={VERDICT[decision.verdict].tone}>{VERDICT[decision.verdict].label}</Pill>
          <p className="mt-1 text-grey-700">{decision.explanation}</p>
        </div>
      ) : null}
      {calls.length ? (
        <ul className="space-y-1">
          {calls.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
              <span className="font-medium">
                {c.app} {c.action}
              </span>
              <span className="text-xs text-muted">
                {sentence(c.status)}, {POLICY[c.policy]}
              </span>
              {c.mocked ? <SimTag /> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {(node.note ?? node.subtitle) ? <p className="text-xs text-muted">{node.note ?? node.subtitle}</p> : null}
    </div>
  );
}

const RECEIPT_COLUMNS: Column<ReceiptItem>[] = [
  { key: "seq", header: "#", numeric: true, cell: (i) => i.seq },
  {
    key: "at",
    header: "At",
    className: "hidden whitespace-nowrap sm:table-cell",
    cell: (i) => <time dateTime={i.at}>{time(i.at)}</time>,
  },
  {
    key: "entry",
    header: "Entry",
    cell: (i) => (
      <span className="block min-w-0">
        <Id>{i.type}</Id>
        <span className="block">{i.summary}</span>
      </span>
    ),
  },
  {
    key: "step",
    header: "Step",
    className: "hidden md:table-cell",
    cell: (i) => (i.nodeId ? <Id>{i.nodeId}</Id> : <span className="text-muted">Run</span>),
  },
  {
    key: "hash",
    header: "Hash",
    cell: (i) => (
      <span title={i.hash}>
        <Id>{prefix(i.hash)}</Id>
      </span>
    ),
  },
];

function ReceiptSection({ receipt }: { receipt: Receipt }) {
  return (
    <Section
      title="Work receipt"
      aside={receipt.verified ? <Pill tone="ink">Verified</Pill> : <Pill tone="blocked">Not verified</Pill>}
    >
      <div className="space-y-3 border-b border-rule px-5 py-4 text-sm">
        <p className="text-grey-700">
          {receipt.verified
            ? "Every entry's hash covers the one before it, and the chain checked out when this page loaded."
            : "The chain did not check out when this page loaded: an entry was changed or is missing. Treat this run's record as untrusted."}{" "}
          <span className="tnum">{receipt.entries}</span> entries, head{" "}
          <span title={receipt.headHash}>
            <Id>{prefix(receipt.headHash)}</Id>
          </span>
          .
        </p>
        {receipt.pinned.length ? (
          <div>
            <h3 className="font-medium">Pinned definitions</h3>
            <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
              {receipt.pinned.map((p) => (
                <li key={`${p.kind}/${p.key}`}>
                  {isKind(p.kind) ? (
                    <Link
                      href={definitionHref(p.kind, p.key, p.version)}
                      className="font-mono text-[12px] underline-offset-2 hover:underline"
                    >
                      {p.kind}/{p.key} v{p.version}
                    </Link>
                  ) : (
                    <Id>
                      {p.kind}/{p.key} v{p.version}
                    </Id>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
      <DataTable
        label="Receipt entries"
        columns={RECEIPT_COLUMNS}
        rows={receipt.items}
        rowKey={(i) => String(i.seq)}
        empty="No entries yet."
        maxHeight="max-h-[60vh]"
      />
    </Section>
  );
}
