"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { notFound } from "next/navigation";
import { QueryState } from "@/components/query-state";
import { RunView } from "@/components/run-view";
import { Skeleton } from "@/components/skeleton";
import { PageHeader, RunStatusPill, SimTag } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import { usePackName } from "@/lib/queries/catalog";
import { useRun } from "@/lib/queries/runs";

export function RunPage({ id }: { id: string }) {
  // The same label the run list gives a sandbox test, so the run reads the same wherever it is seen.
  const t = useTranslations("run.list");
  const run = useRun(id);
  const packName = usePackName(run.data?.packSlug);
  if (run.error instanceof ApiError && run.error.status === 404) notFound();
  return (
    <QueryState query={run} skeleton={<RunSkeleton />}>
      {(r) => (
        <>
          <title>{`${r.title} | New Machines`}</title>
          <PageHeader title={r.title} lede={r.summary}>
            <div className="mb-2 flex flex-wrap items-center gap-2 text-sm text-muted">
              <Link href={`/app/marketplace/${r.packSlug}`} className="hover:text-ink">
                {packName ?? <Skeleton className="inline-block h-4 w-40 align-middle" />}
              </Link>
              <RunStatusPill status={r.status} />
              {r.sandboxTest ? <SimTag>{t("sandboxTest")}</SimTag> : null}
            </div>
          </PageHeader>
          <RunView run={r} />
        </>
      )}
    </QueryState>
  );
}

function RunSkeleton() {
  return (
    <div className="space-y-5">
      <Skeleton className="h-16 w-2/3" />
      <Skeleton className="h-20" />
      <Skeleton className="h-[400px]" />
    </div>
  );
}
