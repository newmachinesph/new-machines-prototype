"use client";

import Link from "next/link";
import { type Column, DataTable } from "@/components/data-table";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Stat } from "@/components/stat";
import { Callout, Id, KeyValues, PageHeader, Pill, RunStatusPill, Section, SimTag } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import type { AuditEntry, Member, OpsRun, TenantConnection, TenantDetail } from "@/lib/api/gen/types.gen";
import { ago, count, date, money, pct } from "@/lib/format";
import { useTenant, useTenantAudit } from "@/lib/queries/tenants";
import { CapUsage } from "./cap-usage";
import { HealthPill, PlanPill, StatusPill } from "./pills";
import { TenantActions } from "./tenant-actions";
import { UsageChart } from "./usage-chart";

const CONNECTION: Record<TenantConnection["status"], { tone: "ink" | "quiet" | "human" | "machine"; label: string }> = {
  connected: { tone: "ink", label: "Connected" },
  not_connected: { tone: "quiet", label: "Not connected" },
  sandbox: { tone: "machine", label: "Sandbox" },
  needs_reauth: { tone: "human", label: "Needs sign-in again" },
};

const memberColumns: Column<Member>[] = [
  {
    key: "name",
    header: "Member",
    cell: (m) => (
      <span className="block">
        <span className="font-medium">{m.name}</span>
        <span className="block text-xs text-muted">{m.email}</span>
      </span>
    ),
  },
  { key: "role", header: "Role", cell: (m) => m.role },
  { key: "via", header: "Joined via", cell: (m) => m.via, className: "hidden sm:table-cell" },
  { key: "pending", header: "Invite", cell: (m) => (m.pending ? <Pill tone="human">Pending</Pill> : null) },
];

const runColumns: Column<OpsRun>[] = [
  {
    key: "id",
    header: "Run",
    cell: (r) => (
      <span className="block">
        <Id>{r.id}</Id>
        <span className="block text-xs text-muted">{r.pack}</span>
      </span>
    ),
  },
  { key: "status", header: "Status", cell: (r) => <RunStatusPill status={r.status} /> },
  { key: "cost", header: "Cost", numeric: true, cell: (r) => money(r.cost) },
  { key: "at", header: "Started", cell: (r) => ago(r.startedAt), className: "hidden md:table-cell" },
];

function AuditList({ entries, tenantId }: { entries: AuditEntry[]; tenantId: string }) {
  if (entries.length === 0)
    return <p className="px-5 py-8 text-sm text-muted">No operator actions on this tenant yet.</p>;
  return (
    <ul className="divide-y divide-rule">
      {entries.map((e) => (
        <li key={e.id} className="px-5 py-3 text-sm">
          <div className="flex items-baseline justify-between gap-3">
            <span className="font-medium">{e.summary}</span>
            <time dateTime={e.at} className="shrink-0 text-xs text-muted">
              {ago(e.at)}
            </time>
          </div>
          <p className="mt-0.5 text-muted">
            {e.actorEmail}: {e.reason}
          </p>
        </li>
      ))}
      <li className="px-5 py-3 text-sm">
        <Link
          href={`/audit?targetType=tenant&targetId=${encodeURIComponent(tenantId)}`}
          className="font-medium text-machine underline-offset-2 hover:underline"
        >
          Open the full audit log for this tenant
        </Link>
      </li>
    </ul>
  );
}

function Header({ t }: { t: TenantDetail }) {
  return (
    <PageHeader
      title={t.name}
      lede={
        <>
          {t.ownerEmail} · {t.region}, {t.country}
        </>
      }
      actions={<TenantActions tenant={t} />}
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Link href="/tenants" className="text-sm text-muted hover:text-ink">
          Tenants
        </Link>
        <span aria-hidden className="text-grey-300">
          /
        </span>
        <StatusPill status={t.status} />
        <PlanPill plan={t.plan} />
        <HealthPill health={t.health} />
      </div>
    </PageHeader>
  );
}

function Body({ t }: { t: TenantDetail }) {
  const audit = useTenantAudit(t.id);
  const runsHref = `/runs?tenant=${encodeURIComponent(t.id)}`;
  return (
    <>
      <Header t={t} />
      {t.status === "suspended" ? (
        <div className="mb-4">
          <Callout tone="blocked" title="This tenant is suspended">
            {t.suspendedReason ?? "No reason was recorded."} Runs will not start until you reactivate it.
          </Callout>
        </div>
      ) : null}
      {t.status === "trial" && t.trialEndsAt ? (
        <div className="mb-4">
          <Callout tone="info" title={`Trial ends ${date(t.trialEndsAt)}`}>
            After that the tenant needs a paid plan to keep running workflows.
          </Callout>
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <Stat label="Members" value={count(t.members)} sub={`${count(t.seats)} seats`} />
        <Stat label="Runs (30d)" value={count(t.runs30d)} sub={`${pct(t.successRate)} succeeded`} />
        <Stat label="Open human tasks" value={count(t.openHumanTasks)} tone={t.openHumanTasks ? "human" : "default"} />
        <Stat label="Packs installed" value={count(t.packsInstalled)} />
        <Stat label="Connectors" value={count(t.connectors)} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Section title="Spend this month" className="xl:col-span-1">
          <div className="space-y-4 px-5 py-4">
            <CapUsage spent={t.monthSpent} cap={t.monthlyCap} showAmounts />
            <KeyValues rows={[{ label: "Created", value: date(t.createdAt) }]} />
            {t.notes ? <p className="text-sm text-grey-700">{t.notes}</p> : null}
          </div>
        </Section>
        <Section title="Daily spend, last 14 days" aside={<SimTag />} className="xl:col-span-2">
          <UsageChart points={t.usageByDay} />
        </Section>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Section title="Members">
          <DataTable
            label="Members"
            columns={memberColumns}
            rows={t.membersList}
            rowKey={(m) => m.email}
            empty="No members yet. The owner has not accepted the invitation."
            maxHeight="max-h-80"
          />
        </Section>
        <Section title="Installed packs">
          {t.installedPacks.length === 0 ? (
            <p className="px-5 py-8 text-sm text-muted">
              No packs installed. The tenant can install one from the marketplace.
            </p>
          ) : (
            <ul className="divide-y divide-rule">
              {t.installedPacks.map((slug) => (
                <li key={slug} className="px-5 py-2.5 text-sm">
                  <Id>{slug}</Id>
                </li>
              ))}
            </ul>
          )}
        </Section>
        <Section title="Connectors">
          {t.connectorsList.length === 0 ? (
            <p className="px-5 py-8 text-sm text-muted">No connectors set up.</p>
          ) : (
            <ul className="divide-y divide-rule">
              {t.connectorsList.map((c) => (
                <li key={c.app} className="flex items-center justify-between gap-3 px-5 py-2.5 text-sm">
                  <span className="font-medium">{c.app}</span>
                  <Pill tone={CONNECTION[c.status].tone}>{CONNECTION[c.status].label}</Pill>
                </li>
              ))}
            </ul>
          )}
        </Section>
        <Section
          title="Recent runs"
          aside={
            <Link href={runsHref} className="text-sm font-medium text-machine underline-offset-2 hover:underline">
              All runs for this tenant
            </Link>
          }
        >
          <DataTable
            label="Recent runs"
            columns={runColumns}
            rows={t.recentRuns}
            rowKey={(r) => r.id}
            empty="No runs yet for this tenant."
            maxHeight="max-h-80"
          />
        </Section>
      </div>

      <Section title="Audit log" className="mt-4">
        <QueryState query={audit} skeleton={<Skeleton className="m-5 h-32" />}>
          {(entries) => <AuditList entries={entries} tenantId={t.id} />}
        </QueryState>
      </Section>
    </>
  );
}

export function TenantDetailView({ id }: { id: string }) {
  const query = useTenant(id);
  if (query.error instanceof ApiError && query.error.status === 404) {
    return (
      <>
        <Link href="/tenants" className="mb-3 inline-block text-sm text-muted hover:text-ink">
          Tenants
        </Link>
        <Section className="p-6">
          <h1 tabIndex={-1} className="h-page outline-none">
            No tenant with the id {id}
          </h1>
          <p className="mt-2 max-w-[60ch] text-sm text-muted">
            It may have been removed or the link is wrong. Go back to the tenant list and pick it from there.
          </p>
        </Section>
      </>
    );
  }
  return (
    <QueryState query={query} skeleton={<Skeleton className="h-96" />}>
      {(t) => <Body t={t} />}
    </QueryState>
  );
}
