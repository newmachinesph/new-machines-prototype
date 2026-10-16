"use client";

import { parseAsStringLiteral, useQueryState } from "nuqs";
import type { ReactNode } from "react";
import { Segmented } from "@/components/base";
import { type Column, DataTable } from "@/components/data-table";
import { ErrorPanel } from "@/components/error-panel";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Id, PageHeader, Pill, Section, SimTag, type Tone } from "@/components/ui";
import type { OpsListing } from "@/lib/api/gen/types.gen";
import { ago } from "@/lib/format";
import { useListings } from "@/lib/queries/listings";
import { useMe, useOpsWorkspace } from "@/lib/queries/ops";
import {
  priceText,
  queuePrice,
  STATUS_LABEL,
  TAB_EMPTY,
  TAB_LABEL,
  TABS,
  type Tab,
  tabStatus,
} from "./listing-state";

export const LIVE_ONLY = "Listings are part of the live workspace.";

const STATUS_TONE: Record<OpsListing["status"], Tone> = { pending: "human", listed: "machine", unlisted: "quiet" };

const COLUMNS: Column<OpsListing>[] = [
  {
    key: "name",
    header: "Name",
    cell: (l) => (
      <span className="block min-w-0">
        <span className="block font-medium">{l.name}</span>
        <Id>{l.key}</Id>
      </span>
    ),
  },
  { key: "kind", header: "Kind", className: "hidden sm:table-cell", cell: (l) => (l.kind === "pack" ? "Pack" : "Agent") },
  { key: "publisher", header: "Publisher", className: "hidden md:table-cell", cell: (l) => l.publisher },
  {
    key: "price",
    header: "Price",
    numeric: true,
    cell: (l) => priceText(queuePrice(l), l.kind),
  },
  {
    key: "status",
    header: "Status",
    cell: (l) => <Pill tone={STATUS_TONE[l.status]}>{STATUS_LABEL[l.status]}</Pill>,
  },
  {
    key: "waiting",
    header: "Waiting version",
    className: "hidden lg:table-cell",
    cell: (l) => (l.pending ? `v${l.pending.definitionVersion}` : <span className="text-muted">None</span>),
  },
  { key: "updated", header: "Updated", numeric: true, className: "hidden md:table-cell", cell: (l) => ago(l.updatedAt) },
];

/**
 * Waits for the operator's profile before choosing a workspace, so a live user never sees the demo message while
 * it loads, and a failed profile shows an error with retry instead of the demo message.
 */
export function LiveGate({ children, demoHeader }: { children: ReactNode; demoHeader?: ReactNode }) {
  const me = useMe();
  const workspace = useOpsWorkspace();
  if (me.isPending) return <Skeleton className="h-96" />;
  if (me.isError && !me.data) {
    return <ErrorPanel title="Could not load your profile" error={me.error} reset={() => void me.refetch()} />;
  }
  if (workspace === "live") return <>{children}</>;
  return (
    <>
      {demoHeader}
      <p className="text-sm text-muted">{LIVE_ONLY}</p>
    </>
  );
}

export function ListingsView() {
  return (
    <>
      <PageHeader
        title="Review queue"
        lede="Listings that workspaces have submitted, by status. Approve what is ready, ask for changes on the rest."
      />
      <LiveGate>
        <Queue />
      </LiveGate>
    </>
  );
}

function Queue() {
  const [tabParam, setTab] = useQueryState("tab", parseAsStringLiteral(TABS));
  const tab: Tab = tabParam ?? "in_review";
  const query = useListings(tabStatus(tab));

  return (
    <div className="space-y-4">
      <p className="flex items-center gap-2 text-xs text-muted">
        <SimTag /> Prices are simulated: no money moves.
      </p>
      <div className="max-w-full overflow-x-auto">
        <Segmented
          label="Listing status"
          value={tab}
          onValueChange={(t) => void setTab(t)}
          options={TABS.map((t) => ({ value: t, label: TAB_LABEL[t] }))}
        />
      </div>
      <Section>
        <QueryState query={query} skeleton={<Skeleton className="h-96" />}>
          {(rows) => (
            <DataTable
              label={`${TAB_LABEL[tab]} listings`}
              columns={COLUMNS}
              rows={rows.toSorted((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))}
              rowKey={(l) => l.id}
              rowHref={(l) => `/listings/${l.id}`}
              empty={TAB_EMPTY[tab]}
            />
          )}
        </QueryState>
      </Section>
    </div>
  );
}
