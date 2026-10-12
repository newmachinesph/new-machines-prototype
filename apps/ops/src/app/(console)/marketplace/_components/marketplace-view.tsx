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
import { useCanWrite, useMe } from "@/lib/queries/ops";
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
  const [tabParam, setTab] = useQueryState("tab", parseAsStringLiteral(TABS));
  const [action, setAction] = useQueryState("action", parseAsStringLiteral(["new"] as const));

  // Support cannot create packs, so a link carrying ?action=new must not open the dialog for them.
  useEffect(() => {
    if (roleKnown && !canWrite && action) void setAction(null);
  }, [roleKnown, canWrite, action, setAction]);

  const newPack = canWrite ? (
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
        lede="Workflow packs by listing status. Approve what is ready, retire what is not."
        actions={newPack}
      />
      <QueryState query={packsQuery} skeleton={<Skeleton className="h-96" />}>
        {(packs) => <PackTabs packs={packs} tabParam={tabParam} onTab={(t) => void setTab(t)} />}
      </QueryState>
      {canWrite ? (
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
