"use client";

import { Plus } from "lucide-react";
import { parseAsStringLiteral, useQueryState } from "nuqs";
import { useEffect, useMemo } from "react";
import { Segmented } from "@/components/base";
import { type Column, DataTable } from "@/components/data-table";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Button, Id, PageHeader, Pill, Section, type Tone } from "@/components/ui";
import { ago, count, pct } from "@/lib/format";
import { usePacks } from "@/lib/queries/marketplace";
import { LiveSampleNote } from "@/components/live-sample-note";
import { useCanWrite, useMe, useOpsWorkspace } from "@/lib/queries/ops";
import type { PackListing } from "@/lib/api/gen/types.gen";
import { NewPackDialog } from "./new-pack-dialog";
import { defaultTab, STATUS_LABEL, TAB_EMPTY, TAB_LABEL, TABS, tabCounts, tabFor } from "./pack-state";
import { ReadOnly } from "@/components/read-only";

const STATUS_TONE: Record<PackListing["status"], Tone> = {
  draft: "quiet",
  in_review: "human",
  published: "machine",
  deprecated: "quiet",
  rejected: "blocked",
};
const RISK_TONE: Record<PackListing["riskClass"], Tone> = { low: "quiet", medium: "human", high: "blocked" };

const COLUMNS: Column<PackListing>[] = [
  {
    key: "pack",
    header: "Pack",
    cell: (p) => (
      <span className="block min-w-0">
        <span className="block font-medium">{p.name}</span>
        <Id>
          {p.slug} v{p.version}
        </Id>
      </span>
    ),
  },
  {
    key: "publisher",
    header: "Publisher",
    className: "hidden md:table-cell",
    cell: (p) => (
      <span className="block">
        {p.publisher}
        <span className="block text-xs text-muted">{p.category}</span>
      </span>
    ),
  },
  {
    key: "function",
    header: "Function",
    className: "hidden lg:table-cell",
    cell: (p) =>
      p.function ? (
        <span className="block">
          {p.function.name}
          {p.industries?.length ? (
            <span className="block text-xs text-muted">{p.industries.map((i) => i.name).join(", ")}</span>
          ) : null}
        </span>
      ) : (
        <span className="text-muted">Not classified</span>
      ),
  },
  {
    key: "status",
    header: "Status",
    cell: (p) => (
      <span className="flex flex-wrap items-center gap-1.5">
        <Pill tone={STATUS_TONE[p.status]}>{STATUS_LABEL[p.status]}</Pill>
        {p.certified ? <Pill tone="ink">Certified</Pill> : null}
      </span>
    ),
  },
  {
    key: "risk",
    header: "Risk",
    className: "hidden lg:table-cell",
    cell: (p) => <Pill tone={RISK_TONE[p.riskClass]}>{p.riskClass[0]?.toUpperCase() + p.riskClass.slice(1)}</Pill>,
  },
  {
    key: "installs",
    header: "Installs",
    numeric: true,
    className: "hidden sm:table-cell",
    cell: (p) => count(p.installs),
  },
  {
    key: "runs",
    header: "Runs (30d)",
    numeric: true,
    className: "hidden lg:table-cell",
    cell: (p) => count(p.runs30d),
  },
  {
    key: "success",
    header: "Success",
    numeric: true,
    className: "hidden lg:table-cell",
    cell: (p) => (p.runs30d > 0 ? pct(p.successRate) : "None yet"),
  },
  {
    key: "updated",
    header: "Updated",
    numeric: true,
    className: "hidden md:table-cell",
    cell: (p) => ago(p.updatedAt),
  },
];

export function MarketplaceView() {
  const packsQuery = usePacks();
  const canWrite = useCanWrite();
  const roleKnown = useMe().isSuccess;
  const live = useOpsWorkspace() === "live";
  // Listings are fixtures in the live workspace, where packs are published as definitions instead.
  const canCreate = canWrite && !live;
  const [tabParam, setTab] = useQueryState("tab", parseAsStringLiteral(TABS));
  const [action, setAction] = useQueryState("action", parseAsStringLiteral(["new"] as const));

  // Support and the live workspace cannot create packs, so a link carrying ?action=new must not linger.
  useEffect(() => {
    if (roleKnown && !canCreate && action) void setAction(null);
  }, [roleKnown, canCreate, action, setAction]);

  const newPack = live ? undefined : canWrite ? (
    <Button onClick={() => void setAction("new")}>
      <Plus className="size-4" aria-hidden />
      New pack
    </Button>
  ) : (
    <ReadOnly>
      <Button disabled>
        <Plus className="size-4" aria-hidden />
        New pack
      </Button>
    </ReadOnly>
  );

  return (
    <>
      <PageHeader
        title="Marketplace"
        lede={
          live
            ? "Workflow packs by listing status. In the live workspace, packs are published from Definitions, so listings are read-only here."
            : "Workflow packs by listing status. Approve what is ready, retire what is not."
        }
        actions={newPack}
        below={<LiveSampleNote>Pack listings here are sample data, not the live catalog.</LiveSampleNote>}
      />
      <QueryState query={packsQuery} skeleton={<Skeleton className="h-96" />}>
        {(packs) => <PackTabs packs={packs} tabParam={tabParam} onTab={(t) => void setTab(t)} />}
      </QueryState>
      {canCreate ? (
        <NewPackDialog open={action === "new"} onOpenChange={(open) => void setAction(open ? "new" : null)} />
      ) : null}
    </>
  );
}

function PackTabs({
  packs,
  tabParam,
  onTab,
}: {
  packs: PackListing[];
  tabParam: (typeof TABS)[number] | null;
  onTab: (tab: (typeof TABS)[number]) => void;
}) {
  const tab = tabParam ?? defaultTab(packs);
  const counts = useMemo(() => tabCounts(packs), [packs]);
  const rows = useMemo(
    () =>
      packs
        .filter((p) => tabFor(p.status) === tab)
        .toSorted((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt)),
    [packs, tab],
  );

  return (
    <div className="space-y-4">
      <div className="max-w-full overflow-x-auto">
        <Segmented
          label="Pack status"
          value={tab}
          onValueChange={onTab}
          options={TABS.map((t) => ({ value: t, label: TAB_LABEL[t], count: counts[t] }))}
        />
      </div>
      <Section>
        <DataTable
          label={`${TAB_LABEL[tab]} packs`}
          columns={COLUMNS}
          rows={rows}
          rowKey={(p) => p.slug}
          rowHref={(p) => `/marketplace/${p.slug}`}
          empty={TAB_EMPTY[tab]}
        />
      </Section>
    </div>
  );
}
