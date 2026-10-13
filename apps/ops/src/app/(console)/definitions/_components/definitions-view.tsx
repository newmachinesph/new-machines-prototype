"use client";

import { Plus } from "lucide-react";
import { parseAsStringLiteral, useQueryState } from "nuqs";
import { useEffect, useMemo } from "react";
import { Select } from "@/components/base";
import { type Column, DataTable } from "@/components/data-table";
import { QueryState } from "@/components/query-state";
import { ReadOnly } from "@/components/read-only";
import { isRuntimeOff, RuntimeOff } from "@/components/runtime-off";
import { Skeleton } from "@/components/skeleton";
import { Button, Id, PageHeader, Pill, Section } from "@/components/ui";
import type { DefinitionSummary } from "@/lib/api/gen/types.gen";
import { dateTime } from "@/lib/format";
import { useDefinitions } from "@/lib/queries/definitions";
import { useCanWrite, useMe } from "@/lib/queries/ops";
import { definitionHref, KIND_LABEL, KINDS } from "./definition-logic";
import { NewDefinitionDialog } from "./new-definition-dialog";

const ALL = "all";

const COLUMNS: Column<DefinitionSummary>[] = [
  {
    key: "definition",
    header: "Definition",
    cell: (d) => (
      <span className="block min-w-0">
        <span className="block font-medium">{d.name}</span>
        <Id>
          {d.kind}/{d.key}
        </Id>
      </span>
    ),
  },
  {
    key: "kind",
    header: "Kind",
    className: "hidden sm:table-cell",
    cell: (d) => <Pill>{KIND_LABEL[d.kind]}</Pill>,
  },
  { key: "version", header: "Version", numeric: true, cell: (d) => `v${d.version}` },
  {
    key: "source",
    header: "Source",
    className: "hidden md:table-cell",
    cell: (d) => (d.source === "console" ? "Console" : "File"),
  },
  {
    key: "by",
    header: "Published by",
    className: "hidden lg:table-cell",
    cell: (d) => <span className="break-all">{d.publishedBy}</span>,
  },
  {
    key: "at",
    header: "Published",
    numeric: true,
    className: "hidden whitespace-nowrap md:table-cell",
    cell: (d) => dateTime(d.publishedAt),
  },
];

export function DefinitionsView() {
  const query = useDefinitions();
  const canWrite = useCanWrite();
  const roleKnown = useMe().isSuccess;
  const [kind, setKind] = useQueryState("kind", parseAsStringLiteral(KINDS));
  const [action, setAction] = useQueryState("action", parseAsStringLiteral(["new"] as const));

  // Support cannot create definitions, so a link carrying ?action=new must not open the dialog for them.
  useEffect(() => {
    if (roleKnown && !canWrite && action) void setAction(null);
  }, [roleKnown, canWrite, action, setAction]);

  const runtimeOff = isRuntimeOff(query.error);
  const newDefinition = canWrite ? (
    <Button onClick={() => void setAction("new")} disabled={runtimeOff}>
      <Plus className="size-4" aria-hidden />
      New definition
    </Button>
  ) : (
    <ReadOnly>
      <Button disabled>
        <Plus className="size-4" aria-hidden />
        New definition
      </Button>
    </ReadOnly>
  );

  return (
    <>
      <PageHeader
        title="Definitions"
        lede="The versioned files every run is built from. Edit one as text, validate it against everything else, and publish it with a reason."
        actions={newDefinition}
      />
      {runtimeOff ? (
        <RuntimeOff what="Definitions" />
      ) : (
        <QueryState query={query} skeleton={<Skeleton className="h-96" />}>
          {(rows) => (
            <>
              <DefinitionTable rows={rows} kind={kind} onKind={(k) => void setKind(k)} />
              {canWrite ? (
                <NewDefinitionDialog
                  open={action === "new"}
                  onOpenChange={(open) => void setAction(open ? "new" : null)}
                  definitions={rows}
                />
              ) : null}
            </>
          )}
        </QueryState>
      )}
    </>
  );
}

function DefinitionTable({
  rows,
  kind,
  onKind,
}: {
  rows: DefinitionSummary[];
  kind: DefinitionSummary["kind"] | null;
  onKind: (kind: DefinitionSummary["kind"] | null) => void;
}) {
  const counts = useMemo(() => {
    const out = new Map<string, number>();
    for (const r of rows) out.set(r.kind, (out.get(r.kind) ?? 0) + 1);
    return out;
  }, [rows]);
  const shown = kind ? rows.filter((r) => r.kind === kind) : rows;
  const items = [
    { value: ALL, label: `All kinds (${rows.length})` },
    ...KINDS.filter((k) => counts.has(k)).map((k) => ({
      value: k as string,
      label: `${KIND_LABEL[k]} (${counts.get(k)})`,
    })),
  ];
  // A kind from the URL with no definitions still needs an item to render as selected.
  if (kind && !counts.has(kind)) items.push({ value: kind, label: `${KIND_LABEL[kind]} (0)` });

  return (
    <div className="space-y-4">
      <Select
        label="Filter by kind"
        value={kind ?? ALL}
        items={items}
        onValueChange={(v) => onKind(v === ALL ? null : (v as DefinitionSummary["kind"]))}
      />
      <Section>
        <DataTable
          label={kind ? `${KIND_LABEL[kind]} definitions` : "Definitions"}
          columns={COLUMNS}
          rows={shown}
          rowKey={(d) => `${d.kind}/${d.key}`}
          rowHref={(d) => definitionHref(d.kind, d.key)}
          empty={kind ? "No definitions of this kind. Pick another kind or create one." : "No definitions yet."}
        />
      </Section>
    </div>
  );
}
