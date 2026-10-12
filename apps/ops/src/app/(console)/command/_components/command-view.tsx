"use client";

import Link from "next/link";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { PageHeader, Section } from "@/components/ui";
import { useOverview } from "@/lib/queries/overview";
import { AttentionQueue } from "./attention-queue";
import { AuditFeed } from "./audit-feed";
import { KpiStrip } from "./kpi-strip";
import { QuickActions } from "./quick-actions";
import { RunsChart } from "./runs-chart";

function CommandSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading the command center" className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Skeleton className="h-80" />
        <Skeleton className="h-80" />
      </div>
    </div>
  );
}

export function CommandView() {
  const overview = useOverview();
  return (
    <>
      <PageHeader
        title="Command center"
        lede="What needs an operator now, across every tenant."
        actions={<QuickActions />}
      />
      <QueryState query={overview} skeleton={<CommandSkeleton />}>
        {(o) => (
          <div className="space-y-4">
            <KpiStrip overview={o} />
            <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
              <Section title="Needs attention" aside={<span className="label tnum">{o.attention.length} open</span>}>
                <AttentionQueue items={o.attention} />
              </Section>
              <div className="space-y-4">
                <Section title="Runs by hour today">
                  <RunsChart points={o.runsByHour} />
                </Section>
                <Section
                  title="Recent operator actions"
                  aside={
                    <Link href="/audit" className="link text-sm">
                      View audit log
                    </Link>
                  }
                >
                  <AuditFeed entries={o.recentAudit} />
                </Section>
              </div>
            </div>
          </div>
        )}
      </QueryState>
    </>
  );
}
