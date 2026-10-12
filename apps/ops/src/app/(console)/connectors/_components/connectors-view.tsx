"use client";

import { Plus } from "lucide-react";
import { parseAsString, parseAsStringLiteral, useQueryState } from "nuqs";
import { useEffect } from "react";
import { type Column, DataTable } from "@/components/data-table";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Button, PageHeader, Pill, Section, SimTag } from "@/components/ui";
import { cn } from "@/lib/cn";
import type { ConnectorEntry } from "@/lib/api/gen/types.gen";
import { ago, count, pct } from "@/lib/format";
import { useConnectors } from "@/lib/queries/connectors";
import { useCanWrite, useMe } from "@/lib/queries/ops";
import { AddConnector } from "./add-connector";
import { AUTH_LABEL, isHighErrorRate, STATUS_LABEL } from "./connector-state";
import { ConnectorDrawer, STATUS_TONE } from "./connector-drawer";
import { ReadOnly } from "@/components/read-only";

const COLUMNS: Column<ConnectorEntry>[] = [
  {
    key: "app",
    header: "Connector",
    cell: (c) => (
      <span className="block min-w-0">
        <span className="block font-medium">{c.app}</span>
        <span className="block text-xs text-muted">{c.category}</span>
      </span>
    ),
  },
  { key: "status", header: "Status", cell: (c) => <Pill tone={STATUS_TONE[c.status]}>{STATUS_LABEL[c.status]}</Pill> },
  { key: "auth", header: "Sign-in", className: "hidden md:table-cell", cell: (c) => AUTH_LABEL[c.authType] },
  {
    key: "tenants",
    header: "Tenants",
    numeric: true,
    className: "hidden sm:table-cell",
    cell: (c) => count(c.tenantsConnected),
  },
  {
    key: "calls",
    header: "Calls today",
    numeric: true,
    className: "hidden sm:table-cell",
    cell: (c) => count(c.callsToday),
  },
  {
    key: "errors",
    header: "Error rate",
    numeric: true,
    cell: (c) =>
      isHighErrorRate(c.errorRate) ? (
        <span className="inline-flex items-center justify-end gap-1.5">
          <Pill tone="blocked">High</Pill>
          <span className="font-medium text-blocked">{pct(c.errorRate)}</span>
        </span>
      ) : (
        pct(c.errorRate)
      ),
  },
  {
    key: "check",
    header: (
      <span className="inline-flex items-center gap-1.5">
        Last check <SimTag>simulated</SimTag>
      </span>
    ),
    className: "hidden lg:table-cell",
    cell: (c) => (
      <span className={cn("inline-flex items-center gap-1.5", !c.lastHealthCheck.ok && "text-blocked")}>
        {c.lastHealthCheck.ok ? "Passed" : "Failed"}
        <span className="text-muted">{ago(c.lastHealthCheck.at)}</span>
      </span>
    ),
  },
];

export function ConnectorsView() {
  const query = useConnectors();
  const canWrite = useCanWrite();
  const roleKnown = useMe().isSuccess;
  const [selected, setSelected] = useQueryState("c", parseAsString);
  const [action, setAction] = useQueryState("action", parseAsStringLiteral(["add"] as const));

  // Support cannot add connectors, so a link carrying ?action=add must not open the dialog for them.
  useEffect(() => {
    if (roleKnown && !canWrite && action) void setAction(null);
  }, [roleKnown, canWrite, action, setAction]);

  // An id that matches no connector (stale link) is dropped from the URL.
  useEffect(() => {
    if (selected && query.data && !query.data.some((c) => c.id === selected)) void setSelected(null);
  }, [selected, query.data, setSelected]);

  const addButton = canWrite ? (
    <Button onClick={() => void setAction("add")}>
      <Plus className="size-4" aria-hidden />
      Add connector
    </Button>
  ) : (
    <ReadOnly>
      <Button disabled>
        <Plus className="size-4" aria-hidden />
        Add connector
      </Button>
    </ReadOnly>
  );

  return (
    <>
      <PageHeader
        title="Connectors"
        lede="The apps tenants can connect, how healthy each one is, and what packs may do with it by default."
        actions={addButton}
      />
      <QueryState query={query} skeleton={<Skeleton className="h-96" />}>
        {(connectors) => (
          <>
            <Section>
              <DataTable
                label="Connectors"
                columns={COLUMNS}
                rows={connectors}
                rowKey={(c) => c.id}
                rowHref={(c) => `/connectors?c=${encodeURIComponent(c.id)}`}
                empty="No connectors yet. Use Add connector to pick one from the available toolkits."
              />
            </Section>
            <ConnectorDrawer
              connector={connectors.find((c) => c.id === selected)}
              onClose={() => void setSelected(null)}
            />
          </>
        )}
      </QueryState>
      {canWrite ? (
        <AddConnector open={action === "add"} onOpenChange={(open) => void setAction(open ? "add" : null)} />
      ) : null}
    </>
  );
}
