"use client";

import { useQuery } from "@tanstack/react-query";
import { opsGetRunOptions, opsListRunsOptions, opsListTenantsOptions } from "@/lib/api/gen/@tanstack/react-query.gen";
import type { OpsRunDetail } from "@/lib/api/gen/types.gen";
import type { RunStatus } from "@/lib/types";

/** Statuses of a run that is still moving: running, waiting on a person or an event, or being verified. */
export const ACTIVE_STATUSES: readonly RunStatus[] = ["RUNNING", "WAITING_FOR_HUMAN", "WAITING_FOR_EVENT", "VERIFYING"];
export const RUN_POLL_MS = 2_000;

/** Poll a run while it is active; stop once it has finished (or before there is anything to show). */
export const runPollInterval = (detail: OpsRunDetail | undefined): number | false =>
  detail && ACTIVE_STATUSES.includes(detail.run.status) ? RUN_POLL_MS : false;

export const useRuns = (q: { status?: RunStatus | null; tenant?: string | null }) =>
  useQuery(opsListRunsOptions({ query: { status: q.status ?? undefined, tenant: q.tenant ?? undefined } }));

/** Tenants for the filter's options. */
export const useTenantOptions = () => useQuery(opsListTenantsOptions());

/**
 * A real run's projection and its hash-chained receipt, refreshed every 2 s while the run is active. 404 for
 * fixture runs and while the runtime is off.
 */
export const useOpsRun = (id: string) =>
  useQuery({
    ...opsGetRunOptions({ path: { run_id: id } }),
    refetchInterval: (query) => runPollInterval(query.state.data),
  });
