"use client";

import { useTranslations } from "next-intl";
import { QueryState } from "@/components/query-state";
import { RunsBrowser } from "@/components/run-row";
import { Skeleton } from "@/components/skeleton";
import { ButtonLink, EmptyState } from "@/components/ui";
import { useRuns } from "@/lib/queries/runs";

export function RunsList() {
  const t = useTranslations("runs");
  const runs = useRuns();
  return (
    <QueryState query={runs} skeleton={<Skeleton className="h-[480px]" />}>
      {(rows) =>
        rows.length ? (
          <RunsBrowser runs={rows} linkable={rows.filter((r) => r.hasDetail).map((r) => r.id)} />
        ) : (
          <div className="panel">
            <EmptyState
              action={
                <ButtonLink href="/app/runs/new" variant="secondary" className="h-8">
                  {t("startRun")}
                </ButtonLink>
              }
            >
              {t("empty")}
            </EmptyState>
          </div>
        )
      }
    </QueryState>
  );
}
