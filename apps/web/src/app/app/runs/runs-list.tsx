"use client";

import { QueryState } from "@/components/query-state";
import { RunsBrowser } from "@/components/run-row";
import { Skeleton } from "@/components/skeleton";
import { useRuns } from "@/lib/queries/runs";

export function RunsList() {
  const runs = useRuns();
  return (
    <QueryState query={runs} skeleton={<Skeleton className="h-[480px]" />}>
      {(rows) => <RunsBrowser runs={rows} linkable={rows.filter((r) => r.hasDetail).map((r) => r.id)} />}
    </QueryState>
  );
}
