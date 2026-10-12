"use client";

import Link from "next/link";
import { parseAsString, parseAsStringLiteral, useQueryStates } from "nuqs";
import { useEffect, useState } from "react";
import { Select } from "@/components/base";
import { DataTable, type Column } from "@/components/data-table";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Id, Section } from "@/components/ui";
import type { AuditEntry } from "@/lib/api/gen/types.gen";
import { dateTime } from "@/lib/format";
import { AUDIT_LIMIT, AUDIT_TARGET_TYPES, useAudit } from "@/lib/queries/audit";
import { filterEntries, targetHref } from "./audit-logic";

const TYPE_VALUES = ["all", ...AUDIT_TARGET_TYPES] as const;
const TYPE_ITEMS = TYPE_VALUES.map((v) => ({
  value: v,
  label: v === "all" ? "All targets" : v[0].toUpperCase() + v.slice(1),
}));

const columns: Column<AuditEntry>[] = [
  { key: "at", header: "When (UTC)", cell: (e) => <span className="tnum whitespace-nowrap">{dateTime(e.at)}</span> },
  {
    key: "operator",
    header: "Operator",
    className: "min-w-48",
    cell: (e) => (
      <div className="min-w-0">
        <div className="break-all">{e.actorEmail}</div>
        <div className="text-xs text-muted">{e.actorRole}</div>
      </div>
    ),
  },
  { key: "action", header: "Action", cell: (e) => <Id className="whitespace-nowrap">{e.action}</Id> },
  {
    key: "target",
    header: "Target",
    cell: (e) => (
      <Link href={targetHref(e.targetType, e.targetId)} className="underline-offset-2 hover:underline">
        <span className="text-xs text-muted">{e.targetType}</span>
        <span className="block font-mono text-[12px] break-all">{e.targetId}</span>
      </Link>
    ),
  },
  { key: "reason", header: "Reason", className: "min-w-48", cell: (e) => e.reason },
  { key: "summary", header: "Summary", className: "min-w-56", cell: (e) => e.summary },
];

export function AuditView() {
  const [f, setF] = useQueryStates({
    targetType: parseAsStringLiteral(TYPE_VALUES).withDefault("all"),
    targetId: parseAsString.withDefault(""),
    q: parseAsString.withDefault(""),
  });

  // The server filters on targetId, so wait for a pause in typing before asking again.
  const [debouncedId, setDebouncedId] = useState(f.targetId);
  useEffect(() => {
    const t = setTimeout(() => setDebouncedId(f.targetId), 300);
    return () => clearTimeout(t);
  }, [f.targetId]);

  const query = useAudit({
    targetType: f.targetType === "all" ? undefined : f.targetType,
    targetId: debouncedId.trim(),
  });
  const filtered = f.targetType !== "all" || f.targetId !== "" || f.q !== "";
  const inputClass =
    "h-9 w-full rounded-md border border-rule bg-paper px-3 text-sm outline-none placeholder:text-grey-500 hover:border-grey-300 focus:border-ink";

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-end">
        <div>
          <label htmlFor="audit-type" className="label mb-1.5 block">
            Target type
          </label>
          <Select
            id="audit-type"
            label="Target type"
            value={f.targetType}
            onValueChange={(v) => void setF({ targetType: v })}
            items={TYPE_ITEMS}
          />
        </div>
        <div className="md:w-56">
          <label htmlFor="audit-target" className="label mb-1.5 block">
            Target id
          </label>
          <input
            id="audit-target"
            value={f.targetId}
            onChange={(e) => void setF({ targetId: e.target.value || null })}
            placeholder="org_hp01"
            className={`${inputClass} font-mono`}
          />
        </div>
        <div className="md:w-80">
          <label htmlFor="audit-q" className="label mb-1.5 block">
            Search summary, reason or operator
          </label>
          <input
            id="audit-q"
            type="search"
            value={f.q}
            onChange={(e) => void setF({ q: e.target.value || null })}
            placeholder="Chargeback, hana.okada, cap"
            className={inputClass}
          />
        </div>
        {filtered ? (
          <button
            type="button"
            onClick={() => void setF({ targetType: null, targetId: null, q: null })}
            className="h-9 rounded-md px-3 text-sm text-grey-700 hover:bg-grey-100 hover:text-ink"
          >
            Clear filters
          </button>
        ) : null}
      </div>
      <QueryState query={query} skeleton={<Skeleton className="h-96" />}>
        {(entries) => {
          const rows = filterEntries(entries, f.q);
          return (
            <Section
              title="Changes"
              aside={
                <span className="tnum text-xs text-muted">
                  {rows.length} of {entries.length}
                  {entries.length >= AUDIT_LIMIT ? `, newest ${AUDIT_LIMIT} only` : ""}
                </span>
              }
            >
              <DataTable
                label="Audit log"
                columns={columns}
                rows={rows}
                rowKey={(e) => e.id}
                maxHeight="max-h-[75vh]"
                empty={
                  filtered
                    ? "No changes match these filters. Clear a filter or widen the search."
                    : "No changes recorded yet. Changes made in this console appear here."
                }
              />
            </Section>
          );
        }}
      </QueryState>
    </div>
  );
}
