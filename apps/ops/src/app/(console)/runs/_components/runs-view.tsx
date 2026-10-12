"use client";

import Link from "next/link";
import { parseAsString, parseAsStringLiteral, useQueryState } from "nuqs";
import { Select } from "@/components/base";
import { type Column, DataTable } from "@/components/data-table";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Amount, Id, Pill, RunStatusPill, Section, type Tone } from "@/components/ui";
import type { OpsRun } from "@/lib/api/gen/types.gen";
import { dateTime, duration } from "@/lib/format";
import { useRuns, useTenantOptions } from "@/lib/queries/runs";
import type { RunStatus } from "@/lib/types";

const STATUSES = [
  "RUNNING",
  "WAITING_FOR_HUMAN",
  "WAITING_FOR_EVENT",
  "VERIFYING",
  "COMPLETED",
  "FAILED",
  "CANCELLED",
  "NEEDS_ATTENTION",
] as const satisfies readonly RunStatus[];

const STATUS_LABEL: Record<RunStatus, string> = {
  RUNNING: "Running",
  WAITING_FOR_HUMAN: "Waiting for a reviewer",
  WAITING_FOR_EVENT: "Waiting for approval",
  VERIFYING: "Verifying",
  COMPLETED: "Completed",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
  NEEDS_ATTENTION: "Needs attention",
};

const ALL = "all";

const WAITING: Record<NonNullable<OpsRun["waitingOn"]>, { tone: Tone; label: string }> = {
  human: { tone: "human", label: "Human" },
  approval: { tone: "ink", label: "Approval" },
  policy: { tone: "policy", label: "Policy" },
};

const columns: Column<OpsRun>[] = [
  { key: "id", header: "Run", cell: (r) => <Id>{r.id}</Id> },
  {
    key: "tenant",
    header: "Tenant",
    cell: (r) => (
      <Link href={`/tenants/${r.tenantId}`} className="font-medium underline-offset-2 hover:underline">
        {r.tenantName}
      </Link>
    ),
  },
  { key: "pack", header: "Pack", className: "hidden md:table-cell", cell: (r) => <Id>{r.pack}</Id> },
  { key: "status", header: "Status", cell: (r) => <RunStatusPill status={r.status} /> },
  {
    key: "waiting",
    header: "Waiting on",
    cell: (r) =>
      r.waitingOn ? (
        <Pill tone={WAITING[r.waitingOn].tone}>{WAITING[r.waitingOn].label}</Pill>
      ) : (
        <span className="text-muted">Nothing</span>
      ),
  },
  {
    key: "started",
    header: "Started",
    className: "hidden whitespace-nowrap md:table-cell",
    cell: (r) => dateTime(r.startedAt),
  },
  {
    key: "duration",
    header: "Duration",
    numeric: true,
    className: "hidden sm:table-cell",
    cell: (r) =>
      r.durationSeconds === undefined ? <span className="text-muted">In progress</span> : duration(r.durationSeconds),
  },
  { key: "cost", header: "Cost", numeric: true, cell: (r) => <Amount value={r.cost} /> },
];

export function RunsView() {
  const [status, setStatus] = useQueryState("status", parseAsStringLiteral(STATUSES));
  const [tenant, setTenant] = useQueryState("tenant", parseAsString);
  const runs = useRuns({ status, tenant });
  const tenants = useTenantOptions();

  const statusItems = [
    { value: ALL, label: "All statuses" },
    ...STATUSES.map((s) => ({ value: s as string, label: STATUS_LABEL[s] })),
  ];
  const tenantItems = [
    { value: ALL, label: "All tenants" },
    ...(tenants.data ?? []).map((t) => ({ value: t.id, label: t.name })),
  ];
  // A tenant id from the URL that is not in the list yet still needs an item to render as selected.
  if (tenant && !tenantItems.some((i) => i.value === tenant)) tenantItems.push({ value: tenant, label: tenant });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3">
        <Select
          label="Filter by status"
          value={status ?? ALL}
          items={statusItems}
          onValueChange={(v) => void setStatus(v === ALL ? null : (v as RunStatus))}
        />
        <Select
          label="Filter by tenant"
          value={tenant ?? ALL}
          items={tenantItems}
          onValueChange={(v) => void setTenant(v === ALL ? null : v)}
        />
      </div>
      <QueryState query={runs} skeleton={<Skeleton className="h-96" />}>
        {(rows) => (
          <Section>
            <DataTable
              label="Runs"
              columns={columns}
              rows={rows}
              rowKey={(r) => r.id}
              empty={status || tenant ? "No runs match these filters. Clear a filter to see more." : "No runs yet."}
              maxHeight="max-h-[70vh]"
            />
          </Section>
        )}
      </QueryState>
    </div>
  );
}
