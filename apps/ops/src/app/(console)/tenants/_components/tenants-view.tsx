"use client";

import { Plus, Search } from "lucide-react";
import { parseAsStringLiteral, useQueryState } from "nuqs";
import { useDeferredValue, useEffect } from "react";
import { Segmented } from "@/components/base";
import { type Column, DataTable } from "@/components/data-table";
import { QueryState } from "@/components/query-state";
import { ReadOnly } from "@/components/read-only";
import { Skeleton } from "@/components/skeleton";
import { Button, PageHeader, Section } from "@/components/ui";
import type { Tenant } from "@/lib/api/gen/types.gen";
import { count, date, money, pct } from "@/lib/format";
import { useCanWrite, useMe, useOpsWorkspace } from "@/lib/queries/ops";
import { useTenants } from "@/lib/queries/tenants";
import { CapUsage } from "./cap-usage";
import { NewTenantDialog } from "./new-tenant-dialog";
import { HealthPill, PlanPill, StatusPill } from "./pills";

const FILTERS = ["all", "active", "trial", "suspended", "churned"] as const;
const FILTER_LABEL: Record<(typeof FILTERS)[number], string> = {
  all: "All",
  active: "Active",
  trial: "Trial",
  suspended: "Suspended",
  churned: "Churned",
};

const columns: Column<Tenant>[] = [
  {
    key: "name",
    header: "Tenant",
    cell: (t) => (
      <span className="block">
        <span className="font-medium">{t.name}</span>
        <span className="block text-xs text-muted">{t.ownerEmail}</span>
      </span>
    ),
  },
  { key: "status", header: "Status", cell: (t) => <StatusPill status={t.status} /> },
  { key: "plan", header: "Plan", cell: (t) => <PlanPill plan={t.plan} />, className: "hidden md:table-cell" },
  { key: "cap", header: "Cap used", cell: (t) => <CapUsage spent={t.monthSpent} cap={t.monthlyCap} /> },
  {
    key: "spend",
    header: "Spend",
    numeric: true,
    cell: (t) => money(t.monthSpent),
    className: "hidden lg:table-cell",
  },
  {
    key: "runs",
    header: "Runs (30d)",
    numeric: true,
    cell: (t) => count(t.runs30d),
    className: "hidden lg:table-cell",
  },
  {
    key: "success",
    header: "Success",
    numeric: true,
    cell: (t) => pct(t.successRate),
    className: "hidden xl:table-cell",
  },
  { key: "health", header: "Health", cell: (t) => <HealthPill health={t.health} /> },
  { key: "created", header: "Created", cell: (t) => date(t.createdAt), className: "hidden xl:table-cell" },
];

export function TenantsView() {
  const canWrite = useCanWrite();
  const [status, setStatus] = useQueryState("status", parseAsStringLiteral(FILTERS).withDefault("all"));
  const [q, setQ] = useQueryState("q", { defaultValue: "", clearOnDefault: true });
  const [action, setAction] = useQueryState("action", { clearOnDefault: true });
  const roleKnown = useMe().isSuccess;
  const live = useOpsWorkspace() === "live";
  // The live workspace creates orgs at sign-up, so only the demo creates tenants here.
  const canCreate = canWrite && !live;
  const dq = useDeferredValue(q);

  // Support and the live workspace cannot create tenants, so a link carrying ?action=new must not linger.
  useEffect(() => {
    if (roleKnown && !canCreate && action) void setAction(null);
  }, [roleKnown, canCreate, action, setAction]);
  const query = useTenants({ status: status === "all" ? undefined : status, q: dq.trim() });

  const newButton = (
    <Button disabled={!canWrite} onClick={() => setAction("new")}>
      <Plus className="size-4" aria-hidden />
      New tenant
    </Button>
  );

  return (
    <>
      <PageHeader
        title="Tenants"
        lede="Every customer workspace, its plan, spend and health."
        actions={live ? undefined : canWrite ? newButton : <ReadOnly>{newButton}</ReadOnly>}
      />
      <Section>
        <div className="flex flex-col gap-3 border-b border-rule px-5 py-3.5 sm:flex-row sm:items-center sm:justify-between">
          <h2 className="h-section">All tenants</h2>
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
            <div className="max-w-full overflow-x-auto">
              <Segmented
                label="Filter by status"
                value={status}
                onValueChange={(v) => setStatus(v)}
                options={FILTERS.map((f) => ({ value: f, label: FILTER_LABEL[f] }))}
              />
            </div>
            <div className="relative w-full sm:w-56">
              <Search className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-grey-500" aria-hidden />
              <input
                type="search"
                aria-label="Search tenants"
                placeholder="Search name or owner"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                className="h-9 w-full rounded-md border border-rule bg-paper pr-3 pl-8 text-sm placeholder:text-grey-500 hover:border-grey-300 focus:border-grey-500"
              />
            </div>
          </div>
        </div>
        <QueryState query={query} skeleton={<Skeleton className="m-5 h-64" />}>
          {(rows) => (
            <DataTable
              label="Tenants"
              columns={columns}
              rows={rows}
              rowKey={(t) => t.id}
              rowHref={(t) => `/tenants/${t.id}`}
              empty={
                dq.trim() || status !== "all"
                  ? "No tenants match these filters. Clear the search or choose All."
                  : live
                    ? "No tenants yet. Orgs appear here when people sign up."
                    : "No tenants yet. Create one with New tenant."
              }
              maxHeight="max-h-[70vh]"
            />
          )}
        </QueryState>
      </Section>
      {live ? null : (
        <NewTenantDialog open={action === "new" && canWrite} onOpenChange={(o) => setAction(o ? "new" : null)} />
      )}
    </>
  );
}
