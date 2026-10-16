"use client";

import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getWorkflowRunOptions,
  getWorkflowRunQueryKey,
  getWorkflowRunReceiptOptions,
  listWorkflowRunsOptions,
  listWorkflowRunsQueryKey,
  startWorkflowRunMutation,
} from "@/lib/api/gen/@tanstack/react-query.gen";
import type { RunStatus } from "@/lib/types";
import { byOperation, useIsLive } from "./me";

export const ACTIVE_STATUSES: RunStatus[] = ["RUNNING", "WAITING_FOR_HUMAN", "WAITING_FOR_EVENT", "VERIFYING"];

export const useRuns = (enabled = true, poll = true) =>
  useQuery({ ...listWorkflowRunsOptions(), refetchInterval: poll ? 10_000 : false, enabled });

export const useRun = (id: string) =>
  useQuery({
    ...getWorkflowRunOptions({ path: { run_id: id } }),
    refetchInterval: (q) => (q.state.data && ACTIVE_STATUSES.includes(q.state.data.status) ? 2_000 : false),
  });

/**
 * The work receipt of a live workspace's run. The demo's fixture runs have none, so it is never requested there
 * (the API would answer 404). No retry, and no polling of a missing receipt, because the interval only runs
 * while the query holds data. When the run's status changes (for example it finishes and the receipt seals),
 * the receipt is fetched once more so it never stays stale.
 */
export function useReceipt(id: string, status: RunStatus) {
  const qc = useQueryClient();
  const options = getWorkflowRunReceiptOptions({ path: { run_id: id } });
  const active = ACTIVE_STATUSES.includes(status);
  const query = useQuery({
    ...options,
    enabled: useIsLive(),
    retry: false,
    refetchInterval: (q) => (active && q.state.data ? 2_000 : false),
  });
  const seen = useRef(status);
  const key = options.queryKey;
  useEffect(() => {
    if (seen.current === status) return;
    seen.current = status;
    void qc.invalidateQueries({ queryKey: key });
  }, [status, qc, key]);
  return query;
}

export function useStartRun() {
  const qc = useQueryClient();
  return useMutation({
    ...startWorkflowRunMutation(),
    onSuccess: (run) => {
      qc.setQueryData(getWorkflowRunQueryKey({ path: { run_id: run.id } }), run);
      void qc.invalidateQueries({ queryKey: listWorkflowRunsQueryKey() });
      // A started run holds budget and moves the month's spend: refresh billing and the org's figures.
      void qc.invalidateQueries({ predicate: byOperation("getUsage") });
      void qc.invalidateQueries({ predicate: byOperation("getOrganization") });
    },
  });
}
