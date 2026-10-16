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
import { useCanWrite, useMe, useOpsWorkspace } from "@/lib/queries/ops";
import { AddConnector } from "./add-connector";
import { AUTH_LABEL, isHighErrorRate, STATUS_LABEL } from "./connector-state";
import { ConnectorDrawer, STATUS_TONE } from "./connector-drawer";
import { ReadOnly } from "@/components/read-only";

const CHECK_KEY = "check";
const LIVE_ADD_NOTE = "Connectors are added by publishing a definition.";

const COLUMNS: Column<ConnectorEntry>[] = [
  {
    key: "app",
    header: "Connector",
    cell: (c) => (
      <span className="block min-w-0">
        <span className="block font-medium">{c.app}</span>
        <span className="block text-xs text-muted">{c.category}</span>
        {c.ownerOrgName ? (
          <span className="block text-xs text-muted">Own MCP server of {c.ownerOrgName}</span>
        ) : null}
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
    key: CHECK_KEY,
    header: (
      <span className="inline-flex items-center gap-1.5">
        Last check <SimTag>simulated</SimTag>
      </span>
    ),
    className: "hidden lg:table-cell",
    cell: (c) => {
      const check = c.lastHealthCheck;
      if (!check) return null;
      return (
        <span className={cn("inline-flex items-center gap-1.5", !check.ok && "text-blocked")}>
          {check.ok ? "Passed" : "Failed"}
          <span className="text-muted">{ago(check.at)}</span>
        </span>
      );
    },
  },
];

/** Health checks are simulated and the live workspace has none, so its table has no Last check column. */
const LIVE_COLUMNS = COLUMNS.filter((c) => c.key !== CHECK_KEY);

export function ConnectorsView() {
  const query = useConnectors();
  const canWrite = useCanWrite();
  const roleKnown = useMe().isSuccess;
  const live = useOpsWorkspace() === "live";
  // Only the demo adds connectors in the console; the live workspace publishes connector definitions.
  const canAdd = canWrite && !live;
  const [selected, setSelected] = useQueryState("c", parseAsString);
  const [action, setAction] = useQueryState("action", parseAsStringLiteral(["add"] as const));

  // Support and the live workspace cannot add connectors, so a link carrying ?action=add must not linger.
  useEffect(() => {
    if (roleKnown && !canAdd && action) void setAction(null);
  }, [roleKnown, canAdd, action, setAction]);

  // An id that matches no connector (stale link) is dropped from the URL.
  useEffect(() => {
    if (selected && query.data && !query.data.some((c) => c.id === selected)) void setSelected(null);
  }, [selected, query.data, setSelected]);

  const addButton = live ? (
    <p className="max-w-[32ch] text-sm text-muted">{LIVE_ADD_NOTE}</p>
  ) : canWrite ? (
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
        lede={
          live
            ? "The apps tenants can connect, how much they are used, and what packs may do with each by default."
            : "The apps tenants can connect, how healthy each one is, and what packs may do with it by default."
        }
        actions={addButton}
      />
      <QueryState query={query} skeleton={<Skeleton className="h-96" />}>
        {(connectors) => (
          <>
            <Section>
              <DataTable
                label="Connectors"
                columns={live ? LIVE_COLUMNS : COLUMNS}
                rows={connectors}
                rowKey={(c) => c.id}
                rowHref={(c) => `/connectors?c=${encodeURIComponent(c.id)}`}
                empty={
                  live
                    ? `No connectors yet. ${LIVE_ADD_NOTE}`
                    : "No connectors yet. Use Add connector to pick one from the available toolkits."
                }
              />
            </Section>
            <ConnectorDrawer
              connector={connectors.find((c) => c.id === selected)}
              onClose={() => void setSelected(null)}
            />
          </>
        )}
      </QueryState>
      {canAdd ? (
        <AddConnector open={action === "add"} onOpenChange={(open) => void setAction(open ? "add" : null)} />
      ) : null}
    </>
  );
}
